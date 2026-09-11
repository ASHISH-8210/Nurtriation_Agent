"""
NutriMind RAG Knowledge Base Ingestion Script
==============================================
Ingests nutrition documents into a FAISS vector index
backed by IBM watsonx.ai embeddings (slate-125m-english-rtrvr).

Sources ingested:
  1. USDA FoodData Central CSV export (foundation foods)
  2. ADA Diabetes dietary guidelines (PDF or text)
  3. Allergy-safe substitution list (Markdown)
  4. PCOS nutrition guidelines (text)
  5. Cultural dietary rules (Halal / Jain / Kosher / Vegan)

Outputs:
  rag/nutrition.index   — FAISS flat-IP index
  rag/metadata.jsonl    — one JSON object per chunk: {id, source, text}
  (Both uploaded to IBM COS bucket: nutrimind-rag)

Usage:
  python rag/ingest.py [--sources-dir ./rag/sources] [--output-dir ./rag]
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Iterator

import httpx
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("nutrimind-ingest")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
EMBEDDING_MODEL_ID = "ibm/slate-125m-english-rtrvr"
EMBEDDING_DIMENSIONS = 768
CHUNK_SIZE_TOKENS = 512       # approximate; we split by characters (4 chars ≈ 1 token)
CHUNK_OVERLAP_CHARS = 256
CHARS_PER_TOKEN = 4
CHUNK_SIZE_CHARS = CHUNK_SIZE_TOKENS * CHARS_PER_TOKEN   # 2048 chars
EMBED_BATCH_SIZE = 32          # watsonx.ai accepts up to 100 per batch


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

def extract_text_from_pdf(path: Path) -> str:
    """Extract plain text from a PDF using pypdf (optional dep)."""
    try:
        from pypdf import PdfReader  # type: ignore
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except ImportError:
        logger.warning("pypdf not installed — skipping PDF: %s", path.name)
        return ""


def extract_text_from_csv_usda(path: Path, max_rows: int = 5000) -> list[str]:
    """
    Convert USDA FoodData Central CSV rows into descriptive text chunks.
    Each row → one paragraph describing the food and its nutrient profile.
    """
    texts: list[str] = []
    with path.open(encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if i >= max_rows:
                break
            description = row.get("description") or row.get("name") or row.get("long_name", "")
            if not description:
                continue
            nutrients = []
            for key in row:
                if any(n in key.lower() for n in ["energy", "protein", "carb", "fat", "fiber",
                                                    "sugar", "sodium", "calcium", "iron",
                                                    "vitamin"]):
                    val = row[key].strip()
                    if val and val not in ("", "0", "0.0"):
                        nutrients.append(f"{key}: {val}")

            text = f"Food: {description}.\nNutrients per 100g: {'; '.join(nutrients[:12])}."
            texts.append(text)
    return texts


def load_markdown_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def load_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_text(text: str, source: str) -> list[dict]:
    """
    Split text into overlapping chunks.
    Returns list of {id, source, text} dicts.
    """
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    chunks: list[dict] = []
    start = 0
    chunk_idx = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE_CHARS, len(text))
        # Try to break at sentence boundary
        if end < len(text):
            boundary = text.rfind(". ", start, end)
            if boundary > start + CHUNK_SIZE_CHARS // 2:
                end = boundary + 1
        chunk = text[start:end].strip()
        if len(chunk) > 50:  # skip tiny fragments
            chunks.append({
                "id": f"{source}::chunk{chunk_idx:05d}",
                "source": source,
                "text": chunk,
            })
            chunk_idx += 1
        start = end - CHUNK_OVERLAP_CHARS
    return chunks


# ---------------------------------------------------------------------------
# IBM watsonx.ai Embeddings
# ---------------------------------------------------------------------------

def _get_iam_token() -> str:
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            "https://iam.cloud.ibm.com/identity/token",
            data={
                "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                "apikey": os.environ["WATSONX_APIKEY"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


def embed_texts(texts: list[str], iam_token: str) -> np.ndarray:
    """
    Embed a list of texts using IBM watsonx.ai slate-125m-english-rtrvr.
    Returns float32 ndarray of shape (len(texts), EMBEDDING_DIMENSIONS).
    """
    url = (
        f"{os.environ['WATSONX_URL'].rstrip('/')}"
        "/ml/v1/text/embeddings?version=2024-05-01"
    )
    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i : i + EMBED_BATCH_SIZE]
        payload = {
            "model_id": EMBEDDING_MODEL_ID,
            "project_id": os.environ["WATSONX_PROJECT_ID"],
            "inputs": batch,
        }
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {iam_token}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            results = resp.json()["results"]
            all_embeddings.extend(r["embedding"] for r in results)

        logger.info("Embedded batch %d/%d (%d chunks)", i + len(batch), len(texts), len(all_embeddings))
        time.sleep(0.3)  # be kind to the Lite rate limit

    return np.array(all_embeddings, dtype="float32")


# ---------------------------------------------------------------------------
# FAISS index builder
# ---------------------------------------------------------------------------

def build_faiss_index(embeddings: np.ndarray) -> "faiss.IndexFlatIP":
    try:
        import faiss  # type: ignore
    except ImportError:
        logger.error("faiss-cpu not installed. Run: pip install faiss-cpu")
        sys.exit(1)

    # Normalize for cosine similarity via inner product
    faiss.normalize_L2(embeddings)
    index = faiss.IndexFlatIP(EMBEDDING_DIMENSIONS)
    index.add(embeddings)
    logger.info("FAISS index built: %d vectors, dim=%d", index.ntotal, EMBEDDING_DIMENSIONS)
    return index


# ---------------------------------------------------------------------------
# IBM COS upload
# ---------------------------------------------------------------------------

def upload_to_cos(local_path: Path, object_key: str) -> None:
    """Upload a file to IBM Cloud Object Storage nutrimind-rag bucket."""
    try:
        import ibm_boto3  # type: ignore
        from ibm_botocore.client import Config  # type: ignore

        cos = ibm_boto3.client(
            "s3",
            ibm_api_key_id=os.environ["COS_APIKEY"],
            ibm_service_instance_id=os.environ["COS_INSTANCE_CRN"],
            config=Config(signature_version="oauth"),
            endpoint_url=os.environ["COS_ENDPOINT"],
        )
        cos.upload_file(str(local_path), "nutrimind-rag", object_key)
        logger.info("Uploaded %s → cos://nutrimind-rag/%s", local_path.name, object_key)
    except ImportError:
        logger.warning("ibm-cos-sdk not installed — skipping COS upload for %s", local_path.name)
    except Exception as exc:
        logger.error("COS upload failed for %s: %s", local_path.name, exc)


# ---------------------------------------------------------------------------
# Curated inline knowledge (no external file needed)
# ---------------------------------------------------------------------------

INLINE_KNOWLEDGE: dict[str, str] = {
    "halal_rules": """
# Halal Dietary Rules
Foods permitted (halal) and prohibited (haram) in Islamic dietary law:

PROHIBITED (Haram):
- Pork and all pork by-products (lard, gelatin from pork, etc.)
- Alcohol in any form, including cooking wine, vanilla extract with alcohol, beer-battered foods
- Blood and blood products
- Animals not slaughtered according to Islamic rites
- Carnivorous animals and birds of prey

PERMITTED (Halal):
- All vegetables, fruits, grains, legumes, nuts, and seeds
- Seafood (fish, shrimp, etc.) — permitted by most schools
- Beef, lamb, chicken slaughtered with bismillah
- Dairy from permitted animals

HIDDEN SOURCES TO AVOID:
- Gelatin (often pork-derived) in desserts, marshmallows, jell-o
- Rennet in cheese (must be microbial or plant-based)
- Emulsifiers E471 (may be pork-derived)
- Carmine (E120) — from insects, not halal for all
""",

    "jain_rules": """
# Jain Dietary Rules
Jainism prohibits foods that involve harming living beings, especially those with many senses.

PROHIBITED:
- All meat, fish, and eggs (involves direct harm to animals)
- Root vegetables: onion, garlic, potato, carrot, beetroot, radish, turnip, leek
  (uprooting kills the entire plant and soil microorganisms)
- Brinjal (eggplant) — many tiny seeds, considered to have many microorganisms
- Honey (involves harming bees)
- Eating after sunset (traditional strictness varies)
- Alcohol

PERMITTED:
- All above-ground vegetables (spinach, tomato, capsicum, pumpkin, cabbage, etc.)
- Fruits
- Grains, lentils, legumes
- Dairy (milk, ghee, paneer — most Jains are lacto-vegetarian)
- Most nuts and seeds

HIGH-PROTEIN JAIN SOURCES:
- Moong dal, chana dal, masoor dal (green), rajma, chickpeas
- Paneer, curd, milk, buttermilk
- Quinoa, amaranth, tofu (check for no animal rennet)
""",

    "diabetes_guidelines": """
# Type 2 Diabetes Dietary Guidelines (ADA 2024 Summary)

CARBOHYDRATE MANAGEMENT:
- No single ideal carbohydrate percentage; individualize based on glucose response
- Focus on carbohydrate quality: choose high-fiber, low-GI sources
- Prioritize: legumes, whole grains, vegetables, low-GI fruits
- Minimize: refined grains, added sugars, sugar-sweetened beverages, white rice in large portions
- Total carbs: typically 45-60g per meal as a starting point; monitor with CGM/blood glucose

PROTEIN:
- No need to restrict protein unless chronic kidney disease present
- 15-20% of calories from lean protein supports satiety and stable glucose
- Preferred: fish (2x/week), legumes, skinless poultry, low-fat dairy

FAT:
- Emphasize mono- and polyunsaturated fats: olive oil, avocado, nuts, fatty fish
- Limit saturated fat < 10% of calories
- Avoid trans fats entirely

FIBER:
- Target ≥ 25-35g/day
- Soluble fiber (oats, psyllium, legumes) slows glucose absorption

GLYCEMIC INDEX GUIDANCE:
- Low GI (< 55): most vegetables, legumes, oats, barley, whole grain pasta, apple, pear
- Medium GI (56-69): whole wheat bread, brown rice, sweet potato
- High GI (≥ 70): white rice, white bread, watermelon, cornflakes — minimize

MEAL TIMING:
- Regular meal timing helps stabilize blood glucose
- Avoid very large meals; prefer smaller, more frequent eating if glucose spikes occur
- Pre-workout snack if on insulin (risk of hypoglycemia)
""",

    "pcos_guidelines": """
# PCOS (Polycystic Ovary Syndrome) Nutrition Guidelines

CORE PRINCIPLE:
PCOS is associated with insulin resistance in ~70% of cases. A diet that improves
insulin sensitivity is the foundation of nutrition therapy.

BENEFICIAL DIETARY PATTERNS:
- Low glycemic index (Low-GI) diet: shown to improve insulin sensitivity and reduce androgens
- Anti-inflammatory diet: Mediterranean pattern (olive oil, fish, colorful vegetables, nuts)
- Higher protein intake (25-30% of calories) to support satiety and lean mass

SPECIFIC RECOMMENDATIONS:
- Refined carbs: limit white bread, pasta, sugary cereals, candy, soda
- Added sugars: keep < 25g/day (AHA recommendation for women)
- Fiber: aim for 30-35g/day from vegetables, legumes, whole grains
- Omega-3 fatty acids: fatty fish 2x/week or flaxseed, walnuts daily
- Magnesium-rich foods: dark leafy greens, pumpkin seeds, almonds, dark chocolate (improves insulin)
- Zinc: important for hormonal balance; sources: pumpkin seeds, beef, chickpeas
- Inositol: found in citrus fruits, cantaloupe, legumes; may improve ovarian function

WHAT TO LIMIT:
- Dairy: some evidence links dairy to increased androgens; trial reduction for 4 weeks
- Processed soy: may affect hormones; fermented soy (miso, tempeh) preferred
- Alcohol: disrupts liver's ability to regulate hormones

WEIGHT MANAGEMENT:
- Even 5-10% weight loss significantly improves menstrual regularity and insulin sensitivity
- Focus on sustainable deficit (250-500 kcal/day) rather than crash diets
""",

    "allergy_substitutions": """
# Food Allergy Substitution Guide

## Milk / Dairy Allergy Substitutes
- Cow's milk → oat milk (cooking), soy milk (protein-matched), rice milk (light), almond milk
- Butter → vegan butter (Miyoko's), coconut oil, olive oil
- Cheese → nutritional yeast for flavor, cashew-based cheese (if no tree nut allergy)
- Yogurt → coconut yogurt, soy yogurt, oat yogurt
- Cream → full-fat coconut milk, oat cream

## Egg Allergy Substitutes (per egg)
- Binding: 1 tbsp ground flaxseed + 3 tbsp water (flax egg), chia seed egg
- Leavening: 1 tsp baking soda + 1 tbsp vinegar
- Moisture: ¼ cup mashed banana, ¼ cup unsweetened applesauce
- Commercial: JUST Egg (mung bean protein), aquafaba (3 tbsp per egg)

## Wheat / Gluten Allergy Substitutes
- All-purpose flour → rice flour, oat flour (certified GF), almond flour, cassava flour
- Bread → certified gluten-free bread (rice + tapioca base)
- Pasta → rice pasta, chickpea pasta (higher protein), lentil pasta
- Soy sauce → tamari (GF), coconut aminos
- Breadcrumbs → crushed rice crackers, certified GF oats

## Peanut Allergy Substitutes
- Peanut butter → sunflower seed butter (SunButter), pumpkin seed butter, tahini
- Peanuts in cooking → toasted sunflower seeds, roasted pumpkin seeds

## Tree Nut Allergy Substitutes
- Almond milk → oat milk, soy milk, rice milk
- Cashew cream → sunflower seed cream, silken tofu blended
- Walnut topping → sunflower seeds, pumpkin seeds, hemp seeds

## Soy Allergy Substitutes
- Tofu → hemp tofu, extra-firm jackfruit, seitan (if no wheat allergy)
- Soy milk → oat milk, rice milk, pea protein milk (Ripple)
- Edamame → green peas (different protein profile)
- Miso → chickpea miso (soy-free)
""",

    "hypertension_guidelines": """
# Hypertension (High Blood Pressure) Dietary Guidelines — DASH Diet

THE DASH DIET FRAMEWORK:
Dietary Approaches to Stop Hypertension (DASH) is the gold standard for blood pressure management.

DAILY TARGETS:
- Sodium: < 2300 mg/day (ideal: < 1500 mg for stage 2 hypertension)
- Potassium: 3500-5000 mg/day (helps counter sodium effect)
- Magnesium: 420 mg/day for men, 320 mg for women
- Calcium: 1000-1200 mg/day
- Fiber: > 30g/day

FOODS TO EMPHASIZE:
- Fruits: 4-5 servings/day (especially banana, avocado, cantaloupe — potassium-rich)
- Vegetables: 4-5 servings/day (leafy greens, sweet potato, squash)
- Whole grains: 6-8 servings/day (oats, quinoa, brown rice)
- Lean protein: fish (especially fatty fish for omega-3), skinless poultry, legumes
- Low-fat dairy: 2-3 servings/day (source of calcium and magnesium)
- Nuts and seeds: 4-5 servings/week (unsalted)

FOODS TO LIMIT:
- Processed and canned foods (high sodium)
- Deli meats, smoked meats, sausages
- Fast food and restaurant meals
- Salty snacks (chips, pretzels, salted nuts)
- Pickled foods
- Full-fat dairy, fatty cuts of meat
- Alcohol: ≤ 1 drink/day for women, ≤ 2 for men

BLOOD PRESSURE LOWERING FOODS WITH EVIDENCE:
- Beets (nitrates → nitric oxide)
- Dark chocolate ≥ 70% cocoa (flavanols)
- Hibiscus tea
- Pomegranate juice
- Garlic (allicin)
- Olive oil (oleic acid)
""",
}


# ---------------------------------------------------------------------------
# Main ingestion pipeline
# ---------------------------------------------------------------------------

def collect_chunks(sources_dir: Path) -> list[dict]:
    all_chunks: list[dict] = []

    # 1. Inline knowledge
    for name, text in INLINE_KNOWLEDGE.items():
        all_chunks.extend(chunk_text(text, source=name))
        logger.info("Chunked inline knowledge '%s': %d chunks", name, len(all_chunks))

    # 2. USDA CSV files (if present)
    for csv_path in sources_dir.glob("*.csv"):
        logger.info("Processing USDA CSV: %s", csv_path.name)
        texts = extract_text_from_csv_usda(csv_path)
        for t in texts:
            all_chunks.extend(chunk_text(t, source=csv_path.stem))

    # 3. PDF files
    for pdf_path in sources_dir.glob("*.pdf"):
        logger.info("Processing PDF: %s", pdf_path.name)
        text = extract_text_from_pdf(pdf_path)
        all_chunks.extend(chunk_text(text, source=pdf_path.stem))

    # 4. Markdown files
    for md_path in sources_dir.glob("*.md"):
        logger.info("Processing Markdown: %s", md_path.name)
        text = load_markdown_file(md_path)
        all_chunks.extend(chunk_text(text, source=md_path.stem))

    # 5. Plain text files
    for txt_path in sources_dir.glob("*.txt"):
        logger.info("Processing text: %s", txt_path.name)
        text = load_text_file(txt_path)
        all_chunks.extend(chunk_text(text, source=txt_path.stem))

    logger.info("Total chunks collected: %d", len(all_chunks))
    return all_chunks


def run(sources_dir: Path, output_dir: Path, date_prefix: str) -> None:
    import faiss  # type: ignore (ensure import works before heavy work)

    output_dir.mkdir(parents=True, exist_ok=True)
    sources_dir.mkdir(parents=True, exist_ok=True)

    # Collect and chunk all documents
    chunks = collect_chunks(sources_dir)
    if not chunks:
        logger.error("No chunks to embed — nothing to ingest.")
        sys.exit(1)

    # Embed with IBM watsonx.ai
    logger.info("Obtaining IAM token...")
    iam_token = _get_iam_token()

    texts = [c["text"] for c in chunks]
    logger.info("Embedding %d chunks with %s ...", len(texts), EMBEDDING_MODEL_ID)
    embeddings = embed_texts(texts, iam_token)

    # Build FAISS index
    index = build_faiss_index(embeddings)

    # Save locally
    index_path = output_dir / "nutrition.index"
    metadata_path = output_dir / "metadata.jsonl"

    faiss.write_index(index, str(index_path))
    with metadata_path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    logger.info("Saved FAISS index: %s (%d vectors)", index_path, index.ntotal)
    logger.info("Saved metadata: %s (%d rows)", metadata_path, len(chunks))

    # Upload to IBM COS
    for local_path, cos_key in [
        (index_path, f"rag/{date_prefix}/nutrition.index"),
        (metadata_path, f"rag/{date_prefix}/metadata.jsonl"),
    ]:
        upload_to_cos(local_path, cos_key)
        # Also upload as "latest" for easy retrieval
        upload_to_cos(local_path, f"rag/latest/{local_path.name}")

    logger.info("Ingestion complete. Total vectors: %d", index.ntotal)


if __name__ == "__main__":
    import faiss  # noqa: F401 — fail fast if not installed

    parser = argparse.ArgumentParser(description="NutriMind RAG Knowledge Base Ingestion")
    parser.add_argument("--sources-dir", default="./rag/sources", help="Directory with source documents")
    parser.add_argument("--output-dir", default="./rag", help="Output directory for index files")
    parser.add_argument("--date-prefix", default=time.strftime("%Y%m%d"), help="COS versioning prefix")
    args = parser.parse_args()

    run(
        sources_dir=Path(args.sources_dir),
        output_dir=Path(args.output_dir),
        date_prefix=args.date_prefix,
    )
