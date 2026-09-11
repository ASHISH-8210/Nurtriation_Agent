# NutriMind — Project Plan
**AI-Powered Personalized Nutrition Assistant on IBM watsonx Orchestrate**

> **Live deployment:** `https://au-syd.watson-orchestrate.cloud.ibm.com`
> Agent ID: `c7225708-c2da-45be-a606-2f9037b55bec` · Region: `au-syd`

---

## Phase 0 — Discovery & Scope Lock

### Problem Statement
Generic diet apps deliver one-size-fits-all recommendations that fail for users with
medical conditions, cultural constraints, or dynamic fitness goals. Registered dieticians
are expensive and inaccessible. NutriMind closes that gap with a conversational,
reasoning-capable AI agent grounded in real nutrition data.

### Constraints
| Constraint | Decision |
|---|---|
| LLM | IBM Granite 3-8b-instruct (text) + granite-vision for images, served via watsonx.ai |
| Orchestration | watsonx Orchestrate Agent (ADK) |
| Persistent store | IBM Cloudant (Lite — 1 GB, 20 req/s) |
| Object storage | IBM Cloud Object Storage (Lite — 25 GB) |
| Voice transcription | IBM Watson Speech-to-Text (Lite — 500 min/month) |
| Nutrition dataset | USDA FoodData Central (public REST API, no cost) |
| RAG index | watsonx.ai Embeddings + in-process FAISS (avoids Watson Discovery cost on Lite) |
| Deployment | IBM Code Engine (Lite — 100k vCPU-s/month) |

### Out of Scope (v1)
- Real-time CGM / wearable integration
- Prescription-level medical nutrition therapy
- Payment / subscription management

---

## Phase 1 — Agent Design

### Agent Identity
```
name: NutriMind
model: ibm/granite-3-8b-instruct
persona: >
  You are NutriMind, a personalized AI nutrition assistant. You give evidence-based,
  culturally sensitive meal plans and food recommendations grounded in retrieved
  nutrition data. You always explain WHY a food is good or bad for this specific user.
  You refuse to recommend anything that conflicts with a stated allergy or medical
  condition. You escalate to a human dietician when signs of eating disorders, complex
  medical nutrition therapy, or medication interactions are present.
```

### System Prompt Design Principles
1. **Profile-first**: always hydrate with `get_user_profile` before generating any plan.
2. **RAG-grounded**: every macro/micro claim must cite a retrieved nutrition fact row.
3. **Explain-then-recommend**: lead with the "why", follow with the meal.
4. **Safety filter**: explicit allergy/condition check before any food mention.
5. **Escalation clause**: hardcoded patterns trigger a "Please consult a dietician" response.

### Tool Dependency Graph
```
User input
    │
    ├─ voice → [Watson STT] → text
    ├─ image → [analyze_food_image] → food list + nutrition
    │
    ▼
[get_user_profile]          ← always first
    │
    ├─ [get_nutrition_data]  ← per food item, feeds RAG context
    ├─ [generate_meal_plan]  ← core planning, uses RAG + profile
    ├─ [suggest_food_swap]   ← swap engine
    └─ [log_feedback]        ← after user rates/rejects
         └─ [update_user_profile]  ← persists learned preferences
```

---

## Phase 2 — Tool Specifications

### `analyze_food_image(image_base64, mime_type)`
- **Model**: `ibm/granite-vision-3-2-2b` via watsonx.ai `/ml/v1/text/chat`
- **Input**: base64-encoded image (JPEG/PNG) or COS signed URL
- **Output**: `{ foods: [{name, quantity_estimate, unit}], nutrition_per_serving: {...} }`
- **Prompt pattern**: structured extraction prompt asking for JSON output

### `get_nutrition_data(food_name, quantity_g)`
- **Backend**: USDA FoodData Central REST API (`/v1/foods/search`)
- **Output**: `{ calories, protein_g, carbs_g, fat_g, fiber_g, key_micronutrients: [...] }`
- **Caching**: Cloudant document with TTL tag to avoid re-fetching common foods

### `generate_meal_plan(user_id, plan_type, days)`
- **Pattern**: RAG — retrieve relevant nutrition facts + condition guidelines, inject into Granite prompt
- **plan_type**: `daily` | `weekly`
- **Output**: structured JSON with meals, quantities, macros, and per-meal "why" explanations
- **Safety**: pre-flight allergy/condition guard before generation

### `suggest_food_swap(food_item, user_id)`
- **Logic**: fetch user constraints → retrieve 5 candidate alternatives from USDA → rank by nutritional fitness → explain top 3
- **Output**: `[{ food, reason, nutrition_delta }]`

### `log_feedback(user_id, meal_id, rating, notes)`
- **Backend**: Cloudant document in `nutrimind-feedback` DB
- **rating**: 1–5 integer
- **Side effect**: triggers preference weight update in user profile

### `get_user_profile(user_id)` / `update_user_profile(user_id, delta)`
- **Backend**: Cloudant `nutrimind-profiles` DB
- **Profile schema**: see `agent/profile_schema.json`

---

## Phase 3 — RAG Knowledge Base Setup

### Corpus
| Document set | Source | Format |
|---|---|---|
| USDA FoodData Central export | `fdc.nal.usda.gov` | CSV → chunked |
| ADA Diabetes dietary guidelines 2024 | ADA website | PDF → text chunks |
| Allergy-safe substitution list | FARE / custom | Markdown |
| PCOS nutrition guidelines | NIH | PDF |
| Jain / Halal / Kosher food rules | Curated | Markdown |

### Ingestion Pipeline (`rag/ingest.py`)
1. Load source documents (CSV, PDF, Markdown)
2. Chunk to ≤ 512 tokens with 64-token overlap
3. Embed with `ibm/slate-125m-english-rtrvr` via watsonx.ai Embeddings API
4. Store vectors in FAISS index (`rag/nutrition.index`) + metadata in `rag/metadata.jsonl`
5. Upload index + metadata to IBM COS bucket `nutrimind-rag`

### Retrieval at Inference
- Query embedded with same `slate-125m` model
- Top-k=5 chunks retrieved from FAISS
- Injected as `<context>` block in Granite system prompt

---

## Phase 4 — Deployment Steps

### Prerequisites
```bash
ibmcloud login --apikey $IBMCLOUD_API_KEY -r us-south
ibmcloud plugin install code-engine
ibmcloud plugin install cloud-object-storage
```

### Step-by-Step
1. **Provision Cloudant Lite** → note service credentials → set `CLOUDANT_URL` + `CLOUDANT_APIKEY`
2. **Provision COS Lite** → create bucket `nutrimind-rag` and `nutrimind-images`
3. **Provision Watson STT Lite** → note API key → set `STT_APIKEY` + `STT_URL`
4. **watsonx.ai project** → note `WATSONX_PROJECT_ID` + `WATSONX_APIKEY` + `WATSONX_URL`
5. **Run RAG ingestion**: `python rag/ingest.py` → uploads index to COS
6. **Deploy MCP server** to Code Engine: `scripts/deploy.sh`
7. **Register agent** in watsonx Orchestrate: `scripts/register_agent.sh`
8. **Smoke test**: `python tests/test_conversations.py`

### Environment Variables Required
```
WATSONX_APIKEY, WATSONX_URL, WATSONX_PROJECT_ID
CLOUDANT_URL, CLOUDANT_APIKEY
COS_APIKEY, COS_INSTANCE_CRN, COS_ENDPOINT
STT_APIKEY, STT_URL
USDA_API_KEY
```

---

## Phase 5 — Safety & Guardrails Implementation

### Allergy Guard (pre-flight check in every tool)
- `user_profile.allergies` list is checked against every food item before it enters any output
- Match is case-insensitive + synonym-aware (peanut ↔ groundnut, etc.)
- On match: tool returns `{"error": "ALLERGY_CONFLICT", "food": "...", "allergen": "..."}` → agent surfaces escalation message

### Medical Escalation Patterns
Hardcoded in system prompt + post-processing filter:
- Calorie targets < 1000 kcal/day requested
- Mentions of laxatives, purging, extreme restriction
- Request for nutrition therapy for active chemotherapy
- Mention of medication interaction ("metformin + ...") → "Please consult your prescribing physician"

### Logging & Audit
- Every tool call logged to Cloudant `nutrimind-audit` with timestamp, user_id (hashed), tool name, input hash
- No raw PII stored in logs

---

## Phase 6 — Rollback Plan
- Code Engine revision pinning: `scripts/rollback.sh <previous-revision-id>`
- Cloudant: point-in-time backup via `scripts/backup_cloudant.sh` before each deploy
- FAISS index versioned in COS with date prefix (`rag/YYYYMMDD/nutrition.index`)

---

## Approval Gate
Before proceeding to implementation, confirm:
- [ ] Nutrition dataset choice (USDA FoodData Central — free, comprehensive)
- [ ] RAG vector store (FAISS in-process on Code Engine — avoids Watson Discovery cost)
- [ ] Persistent store (Cloudant Lite)
- [ ] Deployment target (IBM Code Engine Lite)
