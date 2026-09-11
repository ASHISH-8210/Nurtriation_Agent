"""
NutriMind MCP Tools — IBM watsonx Orchestrate ADK
==================================================
All nutrition assistant tools exposed as MCP endpoints.

IBM Components used:
  - IBM Granite 3-8b-instruct (text generation, swap reasoning)
  - IBM Granite Vision 3-2-2b (food image analysis)
  - IBM watsonx.ai (model serving + embeddings)
  - IBM Cloudant (user profiles, feedback, audit logs)
  - IBM Cloud Object Storage (uploaded images)
  - USDA FoodData Central API (nutrition data)
"""

import os
import json
import time
import hashlib
import logging
import base64
from datetime import datetime, timezone
from typing import Any

import httpx
from ibm_watsonx_ai import Credentials
from ibm_watsonx_ai.foundation_models import ModelInference
from ibm_watsonx_ai.metanames import GenTextParamsMetaNames as GenParams
from ibmcloudant.cloudant_v1 import CloudantV1, Document
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nutrimind-tools")

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------
mcp = FastMCP("nutrimind-tools")

# ---------------------------------------------------------------------------
# IBM Service Clients (lazy-initialized singletons)
# ---------------------------------------------------------------------------

_cloudant_client: CloudantV1 | None = None
_watsonx_creds: Credentials | None = None


def get_cloudant() -> CloudantV1:
    global _cloudant_client
    if _cloudant_client is None:
        authenticator = IAMAuthenticator(os.environ["CLOUDANT_APIKEY"])
        _cloudant_client = CloudantV1(authenticator=authenticator)
        _cloudant_client.set_service_url(os.environ["CLOUDANT_URL"])
    return _cloudant_client


def get_watsonx_creds() -> Credentials:
    global _watsonx_creds
    if _watsonx_creds is None:
        _watsonx_creds = Credentials(
            url=os.environ["WATSONX_URL"],
            api_key=os.environ["WATSONX_APIKEY"],
        )
    return _watsonx_creds


def granite_generate(prompt: str, max_tokens: int = 1024, temperature: float = 0.3) -> str:
    """Single call to IBM Granite 3-8b-instruct via watsonx.ai."""
    model = ModelInference(
        model_id="ibm/granite-3-8b-instruct",
        credentials=get_watsonx_creds(),
        project_id=os.environ["WATSONX_PROJECT_ID"],
        params={
            GenParams.MAX_NEW_TOKENS: max_tokens,
            GenParams.TEMPERATURE: temperature,
            GenParams.TOP_P: 0.9,
            GenParams.REPETITION_PENALTY: 1.1,
            GenParams.STOP_SEQUENCES: ["<|endoftext|>"],
        },
    )
    response = model.generate_text(prompt=prompt)
    return response


def _audit_log(tool: str, user_id: str, input_hash: str) -> None:
    """Write an audit record to Cloudant. Fire-and-forget; never raises."""
    try:
        db = get_cloudant()
        doc = Document(
            id=f"{tool}:{int(time.time()*1000)}",
            tool=tool,
            user_id_hash=hashlib.sha256(user_id.encode()).hexdigest()[:16],
            input_hash=input_hash,
            ts=datetime.now(timezone.utc).isoformat(),
        )
        db.post_document(db="nutrimind-audit", document=doc)
    except Exception as exc:
        logger.warning("Audit log failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# ALLERGY GUARD
# ---------------------------------------------------------------------------

ALLERGY_SYNONYMS: dict[str, list[str]] = {
    "peanuts": ["peanut", "groundnut", "arachis"],
    "tree_nuts": ["almond", "cashew", "walnut", "pecan", "pistachio", "hazelnut", "macadamia"],
    "milk": ["dairy", "lactose", "whey", "casein", "butter", "cream", "cheese", "yogurt"],
    "eggs": ["egg", "albumin", "mayonnaise"],
    "fish": ["salmon", "tuna", "cod", "tilapia", "halibut", "bass", "flounder", "anchovy"],
    "shellfish": ["shrimp", "crab", "lobster", "prawn", "crayfish"],
    "wheat": ["gluten", "flour", "bread", "pasta", "semolina", "spelt", "farro"],
    "soy": ["soya", "tofu", "edamame", "miso", "tempeh"],
    "sesame": ["tahini", "sesame seed", "sesame oil"],
}


def check_allergy_conflict(food_name: str, allergies: list[str]) -> str | None:
    """Return the allergen name if food_name conflicts with any allergy, else None."""
    food_lower = food_name.lower()
    for allergen in allergies:
        terms = [allergen.replace("_", " ")] + ALLERGY_SYNONYMS.get(allergen, [])
        for term in terms:
            if term in food_lower:
                return allergen
    return None


# ---------------------------------------------------------------------------
# TOOL: get_user_profile
# ---------------------------------------------------------------------------

@mcp.tool()
def get_user_profile(user_id: str) -> dict[str, Any]:
    """
    Retrieve the stored NutriMind profile for a user.

    Returns health goals, medical conditions, allergies, dietary preferences,
    fitness routine, calorie/macro targets, and aggregated feedback signals.
    Returns a default skeleton profile if the user is new.
    """
    _audit_log("get_user_profile", user_id, hashlib.md5(user_id.encode()).hexdigest())
    db = get_cloudant()
    try:
        doc = db.get_document(db="nutrimind-profiles", doc_id=user_id).get_result()
        return {k: v for k, v in doc.items() if not k.startswith("_")}
    except Exception:
        # New user — return empty skeleton
        return {
            "user_id": user_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "demographics": {},
            "health_goals": [],
            "medical_conditions": [],
            "allergies": [],
            "intolerances": [],
            "dietary_pattern": "omnivore",
            "cuisine_preferences": [],
            "disliked_foods": [],
            "budget_usd_per_day": None,
            "calorie_target": None,
            "macro_targets": {},
            "fitness_routine": {},
            "feedback_summary": {
                "avg_rating": None,
                "total_meals_rated": 0,
                "preferred_ingredients": [],
                "avoided_ingredients": [],
                "reported_symptoms": [],
            },
        }


# ---------------------------------------------------------------------------
# TOOL: update_user_profile
# ---------------------------------------------------------------------------

@mcp.tool()
def update_user_profile(user_id: str, delta: dict[str, Any]) -> dict[str, Any]:
    """
    Persist changes to a user's NutriMind profile.

    Performs a deep merge of `delta` into the existing profile document.
    Creates the profile document if it does not yet exist.
    Returns the full updated profile.
    """
    db = get_cloudant()
    _audit_log("update_user_profile", user_id, hashlib.md5(json.dumps(delta, sort_keys=True).encode()).hexdigest())

    try:
        existing = db.get_document(db="nutrimind-profiles", doc_id=user_id).get_result()
        rev = existing["_rev"]
    except Exception:
        existing = {"_id": user_id}
        rev = None

    # Deep merge delta into existing
    def deep_merge(base: dict, update: dict) -> dict:
        for k, v in update.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                base[k] = deep_merge(base[k], v)
            elif isinstance(v, list) and isinstance(base.get(k), list):
                # For lists: union (dedup) for strings, replace for objects
                if all(isinstance(i, str) for i in v + base.get(k, [])):
                    base[k] = list(dict.fromkeys(base[k] + v))
                else:
                    base[k] = v
            else:
                base[k] = v
        return base

    updated = deep_merge(dict(existing), delta)
    updated["updated_at"] = datetime.now(timezone.utc).isoformat()
    updated["_id"] = user_id
    if rev:
        updated["_rev"] = rev

    doc = Document.from_dict(updated)
    db.put_document(db="nutrimind-profiles", doc_id=user_id, document=doc)
    return {k: v for k, v in updated.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# TOOL: analyze_food_image
# ---------------------------------------------------------------------------

@mcp.tool()
def analyze_food_image(
    image_base64: str,
    mime_type: str = "image/jpeg",
    context_hint: str = "",
) -> dict[str, Any]:
    """
    Analyze a food photo or grocery label image using IBM Granite Vision.

    Identifies foods, estimates portion sizes, and returns approximate nutrition
    data per serving. Uses ibm/granite-vision-3-2-2b via watsonx.ai chat API.
    """
    hint_text = f"\nAdditional context: {context_hint}" if context_hint else ""
    extraction_prompt = f"""You are a nutrition analysis AI. Analyze this food image and return a JSON object with exactly this structure:
{{
  "foods": [
    {{
      "name": "<food name>",
      "quantity_estimate": <number>,
      "unit": "<g|ml|piece|cup|tbsp>",
      "confidence": "<high|medium|low>"
    }}
  ],
  "total_nutrition_estimate": {{
    "calories_kcal": <number>,
    "protein_g": <number>,
    "carbs_g": <number>,
    "fat_g": <number>,
    "fiber_g": <number>
  }},
  "is_nutrition_label": <true|false>,
  "notes": "<any caveats about the estimate>"
}}
{hint_text}
Return ONLY the JSON object, no other text."""

    # Call watsonx.ai vision endpoint directly (chat completions API with image)
    api_url = (
        f"{os.environ['WATSONX_URL'].rstrip('/')}"
        "/ml/v1/text/chat?version=2024-05-01"
    )
    iam_token = _get_iam_token()

    payload = {
        "model_id": "ibm/granite-vision-3-2-2b",
        "project_id": os.environ["WATSONX_PROJECT_ID"],
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{image_base64}"},
                    },
                    {"type": "text", "text": extraction_prompt},
                ],
            }
        ],
        "max_tokens": 512,
        "temperature": 0.1,
    }

    with httpx.Client(timeout=60) as client:
        resp = client.post(
            api_url,
            json=payload,
            headers={
                "Authorization": f"Bearer {iam_token}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]

    # Parse JSON from model output
    try:
        # Strip markdown fences if present
        clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(clean)
    except json.JSONDecodeError:
        result = {"raw_analysis": raw, "parse_error": "Model output was not valid JSON"}

    return result


def _get_iam_token() -> str:
    """Obtain a short-lived IAM bearer token for direct REST calls."""
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


# ---------------------------------------------------------------------------
# TOOL: get_nutrition_data
# ---------------------------------------------------------------------------

USDA_BASE = "https://api.nal.usda.gov/fdc/v1"
_NUTRITION_CACHE: dict[str, dict] = {}   # in-process cache (food_name → data)

_NUTRIENT_IDS = {
    "calories_kcal": 1008,
    "protein_g": 1003,
    "carbs_g": 1005,
    "fat_g": 1004,
    "fiber_g": 1079,
    "sugar_g": 2000,
    "sodium_mg": 1093,
    "potassium_mg": 1092,
    "calcium_mg": 1087,
    "iron_mg": 1089,
    "vitamin_c_mg": 1162,
    "vitamin_d_iu": 1114,
    "saturated_fat_g": 1258,
}


@mcp.tool()
def get_nutrition_data(food_name: str, quantity_g: float = 100.0) -> dict[str, Any]:
    """
    Look up detailed nutrition data for a food item from USDA FoodData Central.

    Returns calories, macronutrients, and key micronutrients per 100g baseline
    and scaled to the requested quantity. Results are cached in-process.
    """
    cache_key = food_name.lower().strip()
    if cache_key not in _NUTRITION_CACHE:
        params = {
            "query": food_name,
            "dataType": ["SR Legacy", "Foundation", "Branded"],
            "pageSize": 3,
            "api_key": os.environ.get("USDA_API_KEY", "DEMO_KEY"),
        }
        with httpx.Client(timeout=15) as client:
            resp = client.get(f"{USDA_BASE}/foods/search", params=params)
            resp.raise_for_status()
            data = resp.json()

        foods = data.get("foods", [])
        if not foods:
            return {"error": f"No USDA data found for '{food_name}'"}

        # Pick first result and extract nutrients
        food = foods[0]
        nutrients_raw = {n["nutrientId"]: n["value"] for n in food.get("foodNutrients", [])}

        per_100g: dict[str, Any] = {
            "food_name": food.get("description", food_name),
            "fdc_id": food.get("fdcId"),
            "data_source": food.get("dataType"),
        }
        for label, nid in _NUTRIENT_IDS.items():
            per_100g[label] = round(nutrients_raw.get(nid, 0.0), 2)

        _NUTRITION_CACHE[cache_key] = per_100g
    else:
        per_100g = _NUTRITION_CACHE[cache_key]

    # Scale to requested quantity
    scale = quantity_g / 100.0
    scaled: dict[str, Any] = {
        "food_name": per_100g["food_name"],
        "fdc_id": per_100g["fdc_id"],
        "quantity_g": quantity_g,
        "per_100g": {k: v for k, v in per_100g.items() if k not in ("food_name", "fdc_id", "data_source")},
        "for_quantity": {
            k: round(v * scale, 2)
            for k, v in per_100g.items()
            if k not in ("food_name", "fdc_id", "data_source")
        },
    }
    return scaled


# ---------------------------------------------------------------------------
# TOOL: generate_meal_plan
# ---------------------------------------------------------------------------

def _rag_retrieve(query: str, top_k: int = 5) -> str:
    """
    Retrieve relevant nutrition knowledge chunks from FAISS index.
    Falls back to an empty string if the index is not yet available.
    """
    try:
        import faiss  # type: ignore
        import numpy as np

        index = faiss.read_index("rag/nutrition.index")
        with open("rag/metadata.jsonl") as f:
            metadata = [json.loads(line) for line in f]

        # Embed query with watsonx.ai
        embed_url = (
            f"{os.environ['WATSONX_URL'].rstrip('/')}"
            "/ml/v1/text/embeddings?version=2024-05-01"
        )
        iam_token = _get_iam_token()
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                embed_url,
                json={
                    "model_id": "ibm/slate-125m-english-rtrvr",
                    "project_id": os.environ["WATSONX_PROJECT_ID"],
                    "inputs": [query],
                },
                headers={"Authorization": f"Bearer {iam_token}", "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            vec = np.array(resp.json()["results"][0]["embedding"], dtype="float32").reshape(1, -1)

        _, indices = index.search(vec, top_k)
        chunks = [metadata[i]["text"] for i in indices[0] if i < len(metadata)]
        return "\n\n---\n\n".join(chunks)
    except Exception as exc:
        logger.warning("RAG retrieval failed (non-fatal): %s", exc)
        return ""


@mcp.tool()
def generate_meal_plan(
    user_id: str,
    plan_type: str = "daily",
    days: int = 1,
    special_instructions: str = "",
) -> dict[str, Any]:
    """
    Generate a personalized meal plan for the user.

    Retrieves the user profile, runs RAG over the nutrition knowledge base,
    then calls IBM Granite to produce a structured JSON meal plan with per-meal
    macros and plain-language 'why this works for you' explanations.
    """
    profile = get_user_profile(user_id)

    # Safety: check calorie target sanity
    calorie_target = profile.get("calorie_target")
    if calorie_target and calorie_target < 800:
        return {
            "error": "SAFETY_ESCALATION",
            "message": (
                "I can see this situation needs personalized clinical guidance that goes "
                "beyond what I can safely provide. Please consult a registered dietician "
                "or your healthcare provider."
            ),
        }

    conditions = profile.get("medical_conditions", [])
    allergies = profile.get("allergies", [])
    dietary_pattern = profile.get("dietary_pattern", "omnivore")
    goals = profile.get("health_goals", [])
    disliked = profile.get("disliked_foods", [])
    cuisines = profile.get("cuisine_preferences", [])
    macros = profile.get("macro_targets", {})
    demo = profile.get("demographics", {})

    rag_query = (
        f"meal plan for {', '.join(goals) or 'general wellness'} "
        f"with conditions {', '.join(conditions) or 'none'} "
        f"diet {dietary_pattern}"
    )
    rag_context = _rag_retrieve(rag_query)

    prompt = f"""<|system|>
You are NutriMind, a personalized nutrition AI. Generate a structured {plan_type} meal plan
for {days} day(s). Return ONLY a JSON object with no prose outside the JSON.

USER PROFILE SUMMARY:
- Goals: {', '.join(goals) or 'general wellness'}
- Medical conditions: {', '.join(conditions) or 'none'}
- Allergies (HARD BLOCK — never include): {', '.join(allergies) or 'none'}
- Dietary pattern: {dietary_pattern}
- Disliked foods (avoid): {', '.join(disliked) or 'none'}
- Cuisine preferences: {', '.join(cuisines) or 'any'}
- Calorie target: {calorie_target or 'calculate from profile'} kcal/day
- Protein target: {macros.get('protein_g', 'calculate')} g
- Carbs target: {macros.get('carbs_g', 'calculate')} g
- Fat target: {macros.get('fat_g', 'calculate')} g
- Age: {demo.get('age', 'unknown')}, Sex: {demo.get('sex', 'unknown')}
- Activity level: {demo.get('activity_level', 'unknown')}
{f'- Special instructions: {special_instructions}' if special_instructions else ''}

NUTRITION KNOWLEDGE BASE CONTEXT (use to ground your recommendations):
{rag_context or '(no RAG context available — use general nutrition knowledge)'}

OUTPUT FORMAT — return this exact JSON structure:
{{
  "plan_type": "{plan_type}",
  "days": [
    {{
      "day": 1,
      "total_nutrition": {{"calories_kcal": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": 0}},
      "meals": [
        {{
          "meal_id": "day1_breakfast",
          "meal_type": "breakfast",
          "time_suggestion": "7:30 AM",
          "foods": [
            {{
              "name": "<food>",
              "quantity": "<amount + unit>",
              "calories_kcal": 0,
              "protein_g": 0,
              "carbs_g": 0,
              "fat_g": 0
            }}
          ],
          "meal_nutrition": {{"calories_kcal": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}},
          "why_this_works": "<2-3 sentence explanation specific to this user's conditions and goals>"
        }}
      ]
    }}
  ],
  "general_notes": "<any important caveats or tips for this specific user>",
  "safety_note": "<only include if there is a medical condition requiring extra care>"
}}
<|assistant|>
"""

    raw = granite_generate(prompt, max_tokens=2048, temperature=0.3)

    try:
        clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        plan = json.loads(clean)
    except json.JSONDecodeError:
        plan = {"raw_plan": raw, "parse_error": "Could not parse structured JSON from model output"}

    # Post-flight allergy check on all food names in the plan
    if "days" in plan:
        for day in plan["days"]:
            for meal in day.get("meals", []):
                for food in meal.get("foods", []):
                    conflict = check_allergy_conflict(food.get("name", ""), allergies)
                    if conflict:
                        return {
                            "error": "ALLERGY_CONFLICT",
                            "food": food["name"],
                            "allergen": conflict,
                            "message": (
                                f"I detected a potential allergy conflict: '{food['name']}' "
                                f"may contain {conflict.replace('_', ' ')}. "
                                "I've blocked this plan for your safety. "
                                "Please clarify your allergy details and I'll regenerate."
                            ),
                        }

    _audit_log("generate_meal_plan", user_id, hashlib.md5(str(goals).encode()).hexdigest())
    return plan


# ---------------------------------------------------------------------------
# TOOL: suggest_food_swap
# ---------------------------------------------------------------------------

@mcp.tool()
def suggest_food_swap(
    food_item: str,
    user_id: str,
    swap_reason: str = "",
) -> dict[str, Any]:
    """
    Suggest 3 healthier or condition-appropriate alternatives to a given food.

    Fetches user constraints, retrieves candidate alternatives from USDA,
    ranks by nutritional fitness using IBM Granite reasoning, and returns
    the top 3 swaps with a nutritional delta and plain-language explanation.
    """
    profile = get_user_profile(user_id)
    allergies = profile.get("allergies", [])
    conditions = profile.get("medical_conditions", [])
    dietary_pattern = profile.get("dietary_pattern", "omnivore")

    # Get nutrition data for the original food
    original_nutrition = get_nutrition_data(food_item)

    # Check original food for allergy conflict
    conflict = check_allergy_conflict(food_item, allergies)
    if conflict:
        allergy_note = f"Note: '{food_item}' itself conflicts with your {conflict.replace('_', ' ')} allergy."
    else:
        allergy_note = ""

    prompt = f"""<|system|>
You are a nutrition swap AI. The user wants to replace '{food_item}'.
{f'Swap reason: {swap_reason}' if swap_reason else ''}
{allergy_note}

User constraints:
- Medical conditions: {', '.join(conditions) or 'none'}
- Allergies (NEVER suggest): {', '.join(allergies) or 'none'}
- Dietary pattern: {dietary_pattern}

Original food nutrition (per 100g):
{json.dumps(original_nutrition.get('per_100g', {}), indent=2)}

Suggest exactly 3 food swaps. Return ONLY this JSON:
{{
  "original_food": "{food_item}",
  "swap_reason": "{swap_reason}",
  "suggestions": [
    {{
      "rank": 1,
      "food": "<swap food name>",
      "quantity_suggestion": "<serving size>",
      "why": "<2 sentence explanation specific to this user's conditions>",
      "nutrition_delta": {{
        "calories_kcal": <delta vs original per equivalent serving>,
        "protein_g": 0,
        "carbs_g": 0,
        "fat_g": 0,
        "fiber_g": 0
      }},
      "benefit_tags": ["<e.g. lower_gi>", "<e.g. high_fiber>"]
    }}
  ]
}}
<|assistant|>
"""

    raw = granite_generate(prompt, max_tokens=800, temperature=0.3)
    try:
        clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(clean)
    except json.JSONDecodeError:
        result = {"raw_suggestions": raw, "parse_error": "Model output was not valid JSON"}

    # Allergy guard on suggestions
    if "suggestions" in result:
        safe = []
        for s in result["suggestions"]:
            c = check_allergy_conflict(s.get("food", ""), allergies)
            if not c:
                safe.append(s)
            else:
                logger.info("Filtered unsafe swap suggestion: %s (conflict: %s)", s["food"], c)
        result["suggestions"] = safe

    _audit_log("suggest_food_swap", user_id, hashlib.md5(food_item.encode()).hexdigest())
    return result


# ---------------------------------------------------------------------------
# TOOL: log_feedback
# ---------------------------------------------------------------------------

@mcp.tool()
def log_feedback(
    user_id: str,
    meal_id: str,
    rating: int,
    notes: str = "",
    symptoms_reported: str = "",
) -> dict[str, Any]:
    """
    Record user feedback on a meal recommendation.

    Writes to the nutrimind-feedback Cloudant database and triggers
    an update to the user's feedback_summary in their profile.
    Rating scale: 1 (disliked) to 5 (loved).
    """
    if not (1 <= rating <= 5):
        return {"error": "rating must be between 1 and 5"}

    db = get_cloudant()
    feedback_id = f"{user_id}:{meal_id}:{int(time.time()*1000)}"
    doc = Document(
        id=feedback_id,
        user_id=user_id,
        meal_id=meal_id,
        rating=rating,
        notes=notes,
        symptoms_reported=symptoms_reported,
        ts=datetime.now(timezone.utc).isoformat(),
    )
    db.post_document(db="nutrimind-feedback", document=doc)

    # Update user profile feedback summary
    profile = get_user_profile(user_id)
    summary = profile.get("feedback_summary", {})
    total = summary.get("total_meals_rated", 0) + 1
    prev_avg = summary.get("avg_rating") or 0.0
    new_avg = round(((prev_avg * (total - 1)) + rating) / total, 2)

    # Update preference lists based on rating
    delta: dict[str, Any] = {
        "feedback_summary": {
            "avg_rating": new_avg,
            "total_meals_rated": total,
        }
    }
    if rating <= 2:
        avoided = summary.get("avoided_ingredients", [])
        avoided.append(meal_id)
        delta["feedback_summary"]["avoided_ingredients"] = avoided
    if rating >= 4:
        preferred = summary.get("preferred_ingredients", [])
        preferred.append(meal_id)
        delta["feedback_summary"]["preferred_ingredients"] = preferred
    if symptoms_reported:
        sym = summary.get("reported_symptoms", [])
        sym.append(symptoms_reported)
        delta["feedback_summary"]["reported_symptoms"] = sym

    update_user_profile(user_id, delta)

    return {
        "status": "logged",
        "feedback_id": feedback_id,
        "new_avg_rating": new_avg,
        "total_meals_rated": total,
        "profile_updated": True,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(mcp.http_app, host="0.0.0.0", port=8080)
