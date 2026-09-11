# NutriMind 🥗
**AI-Powered Personalized Nutrition Assistant**
*Built on IBM watsonx Orchestrate · Powered by IBM Granite · IBM Cloud Lite*

---

## What Is NutriMind?

NutriMind is a conversational AI agent that delivers personalized, evidence-based nutrition
guidance — closing the gap between generic diet apps and one-on-one dietician consultations.

Users describe their health goals, medical conditions, allergies, dietary preferences, and
budget. NutriMind generates structured daily/weekly meal plans, explains every recommendation
in plain language, analyzes food photos, suggests healthier food swaps, and continuously
adapts based on user feedback.

---

## IBM Component Usage (Hackathon Rubric)

This section explicitly documents how each mandatory IBM component is used in NutriMind.

### 1. IBM Granite (Core Reasoning & Generation)

**Model**: `ibm/granite-3-8b-instruct`
**Served via**: watsonx.ai (`/ml/v1/text/generate`)
**Used in**:

| Tool / Component | What Granite Does |
|---|---|
| `generate_meal_plan` | Generates the full structured JSON meal plan + per-meal "why this works" explanations, grounded in RAG-retrieved nutrition facts |
| `suggest_food_swap` | Reasons over candidate swap foods, ranks by nutritional fitness for the user's specific conditions, writes the explanation |
| Agent orchestration layer | All reasoning, tool-calling decisions, and conversational responses are handled by Granite 3-8b-instruct as the agent's LLM |

**Configuration** (`agent/agent.yaml`):
```yaml
model:
  provider: watsonx
  model_id: ibm/granite-3-8b-instruct
  parameters:
    temperature: 0.3   # Low temp for consistent nutrition facts
    max_new_tokens: 2048
```

**Why Granite?** Granite 3-8b-instruct has strong instruction-following, is explicitly
enterprise-safe (no harmful content), and its lower temperature generation is well-suited
to factual nutrition tasks where hallucinated numbers cause real harm.

---

### 2. IBM Granite Vision (Food Image Analysis)

**Model**: `ibm/granite-vision-3-2-2b`
**Served via**: watsonx.ai chat completions API (`/ml/v1/text/chat`)
**Used in**: `analyze_food_image` tool

When a user uploads a photo of their meal or a grocery label, NutriMind sends the
base64-encoded image to Granite Vision, which identifies foods, estimates portion sizes,
and returns a structured JSON with approximate nutrition content.

```python
# tools/nutrimind_tools.py — analyze_food_image()
payload = {
    "model_id": "ibm/granite-vision-3-2-2b",
    "messages": [{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}"}},
            {"type": "text", "text": extraction_prompt}
        ]
    }]
}
```

---

### 3. watsonx.ai (Model Serving + Embeddings)

**Service**: IBM watsonx.ai (Lite plan)
**URL**: Configured via `WATSONX_URL` environment variable
**Project ID**: `WATSONX_PROJECT_ID`

**Used for**:
1. **Text generation** — Granite 3-8b-instruct inference for meal planning and swap reasoning
2. **Vision inference** — Granite Vision for food image analysis
3. **Embeddings** — `ibm/slate-125m-english-rtrvr` for RAG document embedding and query embedding

The `slate-125m-english-rtrvr` embedding model converts nutrition documents and user queries
into 768-dimensional vectors, stored in a FAISS index for semantic retrieval.

```python
# rag/ingest.py + tools/nutrimind_tools.py — _rag_retrieve()
payload = {
    "model_id": "ibm/slate-125m-english-rtrvr",
    "project_id": os.environ["WATSONX_PROJECT_ID"],
    "inputs": [query_text],
}
# POST to /ml/v1/text/embeddings?version=2024-05-01
```

---

### 4. watsonx Orchestrate (Agent Orchestration)

**Service**: IBM watsonx Orchestrate
**Integration**: ADK (Agent Development Kit)
**Definition file**: `agent/agent.yaml`

watsonx Orchestrate is the orchestration layer that:
- Routes user messages to the NutriMind agent
- Manages multi-turn conversation memory (session + long-term via Cloudant)
- Calls MCP tools (the Python functions in `tools/nutrimind_tools.py`) when the agent needs data
- Enforces the guardrails (allergy conflict checks, medical escalation)
- Applies the Granite model with the NutriMind system prompt

```yaml
# agent/agent.yaml
spec:
  model:
    provider: watsonx
    model_id: ibm/granite-3-8b-instruct
  tools:
    - name: generate_meal_plan
      mcp_server: nutrimind-tools
    - name: analyze_food_image
      mcp_server: nutrimind-tools
    # ... (all 7 tools)
  mcp_servers:
    - name: nutrimind-tools
      transport: streamable_http
      url: "${MCP_SERVER_URL}"
```

---

### 5. IBM Cloudant (Persistent Storage)

**Service**: IBM Cloudant (Lite plan — 1 GB, 20 req/s)
**Used for**:

| Database | Content |
|---|---|
| `nutrimind-profiles` | User health profiles (conditions, allergies, goals, macro targets, learned preferences) |
| `nutrimind-feedback` | Meal ratings, notes, and symptom reports from users |
| `nutrimind-sessions` | Agent conversation session state for long-term memory |
| `nutrimind-audit` | Tool call audit log (hashed user IDs, no PII) |

All CRUD operations are performed via the `ibmcloudant` Python SDK with IAM authentication.

```python
# tools/nutrimind_tools.py
authenticator = IAMAuthenticator(os.environ["CLOUDANT_APIKEY"])
client = CloudantV1(authenticator=authenticator)
client.set_service_url(os.environ["CLOUDANT_URL"])
```

---

### 6. IBM Cloud Object Storage (Image + RAG Index Storage)

**Service**: IBM Cloud Object Storage (Lite plan — 25 GB)
**Buckets**:

| Bucket | Content |
|---|---|
| `nutrimind-rag` | FAISS vector index (`nutrition.index`), metadata (`metadata.jsonl`), versioned by date prefix, Cloudant backups |
| `nutrimind-images` | User-uploaded food photos (base64 decoded, for audit/reanalysis) |

The RAG index is built by `rag/ingest.py` and uploaded to COS. At startup, Code Engine pulls
the latest index from COS into the container's working directory.

---

### 7. IBM Watson Speech to Text (Voice Input)

**Service**: IBM Watson Speech to Text (Lite plan — 500 min/month)
**Used for**: transcribing voice messages before they reach the agent

When a user sends a voice note, the client app forwards the audio to the STT service.
The transcript is then passed to the NutriMind agent as a text input, enabling hands-free
meal logging ("I just had a bowl of oatmeal with berries").

```python
# Voice preprocessing (client-side or gateway)
from ibm_watson import SpeechToTextV1
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator

stt = SpeechToTextV1(authenticator=IAMAuthenticator(os.environ["STT_APIKEY"]))
stt.set_service_url(os.environ["STT_URL"])
result = stt.recognize(audio=audio_file, content_type="audio/mp3").get_result()
transcript = result["results"][0]["alternatives"][0]["transcript"]
```

---

### 8. IBM Code Engine (Deployment)

**Service**: IBM Code Engine (Lite plan — 100k vCPU-seconds/month)
**Used for**: hosting the NutriMind MCP tools server as a containerized application

The `tools/nutrimind_tools.py` FastMCP server is containerized (`scripts/Dockerfile`) and
deployed to Code Engine. Code Engine's scale-to-zero capability keeps it within the free tier
for development and demo loads.

---

## Architecture Overview

```
User (text / voice / image)
         │
         ▼
IBM Watson STT (voice → text)
         │
         ▼
watsonx Orchestrate Agent
  ├── IBM Granite 3-8b-instruct (reasoning + generation)
  ├── Session memory (in-context, 20 turns)
  └── Long-term memory (Cloudant)
         │
         ├── MCP Tool: get_user_profile / update_user_profile
         │     └── IBM Cloudant (nutrimind-profiles DB)
         │
         ├── MCP Tool: analyze_food_image
         │     └── IBM Granite Vision 3-2-2b (watsonx.ai)
         │
         ├── MCP Tool: get_nutrition_data
         │     └── USDA FoodData Central REST API
         │
         ├── MCP Tool: generate_meal_plan
         │     ├── RAG retrieval (FAISS + IBM slate embeddings)
         │     │     └── IBM COS (nutrition.index)
         │     └── IBM Granite 3-8b-instruct (plan generation)
         │
         ├── MCP Tool: suggest_food_swap
         │     └── IBM Granite 3-8b-instruct (swap ranking + explanation)
         │
         └── MCP Tool: log_feedback
               └── IBM Cloudant (nutrimind-feedback DB)
                     └── update_user_profile (preference learning)
```

---

## Project Structure

```
nutrimind/
├── agent/
│   ├── agent.yaml              # watsonx Orchestrate agent definition
│   └── profile_schema.json     # JSON Schema for user profiles
├── tools/
│   └── nutrimind_tools.py      # All MCP tools (FastMCP server)
├── rag/
│   ├── ingest.py               # RAG knowledge base ingestion
│   └── sources/                # Drop nutrition docs/CSVs here
├── tests/
│   └── test_conversations.py   # 4 test scenarios with expected outputs
├── scripts/
│   ├── Dockerfile              # Container image for Code Engine
│   ├── deploy.sh               # Full deployment script
│   ├── rollback.sh             # Revision rollback
│   ├── register_agent.sh       # watsonx Orchestrate agent registration
│   └── backup_cloudant.sh      # Cloudant backup to COS
├── docs/
│   └── plan.md                 # Full project plan (discovery → deployment)
├── requirements.txt
└── README.md
```

---

## Quick Start

### 1. Clone and install dependencies
```bash
cd nutrimind
pip install -r requirements.txt
```

### 2. Set environment variables
```bash
export WATSONX_APIKEY="your-watsonx-api-key"
export WATSONX_URL="https://us-south.ml.cloud.ibm.com"
export WATSONX_PROJECT_ID="your-project-id"
export CLOUDANT_URL="https://your-instance.cloudantnosqldb.appdomain.cloud"
export CLOUDANT_APIKEY="your-cloudant-apikey"
export COS_APIKEY="your-cos-apikey"
export COS_INSTANCE_CRN="crn:v1:bluemix:public:cloud-object-storage:..."
export COS_ENDPOINT="https://s3.us-south.cloud-object-storage.appdomain.cloud"
export STT_APIKEY="your-stt-apikey"
export STT_URL="https://api.us-south.speech-to-text.watson.cloud.ibm.com"
export MCP_SERVER_API_KEY="your-mcp-server-secret-key"
export USDA_API_KEY="your-usda-api-key"  # free at https://fdc.nal.usda.gov/api-guide.html
```

### 3. Run RAG ingestion
```bash
# Optional: drop extra CSVs/PDFs into rag/sources/ first
python rag/ingest.py
```

### 4. Start the MCP tools server locally
```bash
cd tools
python nutrimind_tools.py
# Server starts on http://0.0.0.0:8080
```

### 5. Run test conversations (dry run)
```bash
python tests/test_conversations.py
```

### 6. Run test conversations (live)
```bash
python tests/test_conversations.py --live
```

### 7. Deploy to IBM Code Engine
```bash
bash scripts/deploy.sh
```

---

## Safety Design

NutriMind has three layers of safety:

1. **Allergy guard** (`check_allergy_conflict`): runs before every tool output.
   Any food matching the user's allergen list (including synonyms like peanut ↔ groundnut)
   is blocked and returns an `ALLERGY_CONFLICT` error instead of a recommendation.

2. **Medical escalation**: the system prompt contains hardcoded patterns that override
   Granite's generation — very low calorie targets, eating disorder language, medication
   interactions, and active medical treatment trigger a "consult your healthcare provider"
   response with no plan generated.

3. **Audit trail**: every tool call writes a hashed, PII-free record to Cloudant
   `nutrimind-audit` for post-hoc review.

---

## Lite Plan Constraints & Mitigations

| Service | Lite Limit | NutriMind Mitigation |
|---|---|---|
| Cloudant | 1 GB storage, 20 req/s | Compact small JSON docs; audit logs use short hashes |
| COS | 25 GB | FAISS index ~50 MB; images stored temporarily and purged |
| Code Engine | 100k vCPU-s/month | Scale-to-zero; 0.25 CPU allocation |
| Watson STT | 500 min/month | Voice is optional; text input always available |
| watsonx.ai | Rate limits apply | In-process USDA cache; RAG uses lite `slate-125m` embedder |

---

## License

Apache 2.0 — see LICENSE file.

---

## Hackathon Notes

- All AI reasoning is done exclusively through **IBM Granite models** — no OpenAI, Anthropic, or other third-party LLMs.
- All infrastructure is on **IBM Cloud Lite** services — no paid tier required for demo.
- The RAG knowledge base uses **IBM slate-125m-english-rtrvr** embeddings, an IBM-built model.
- Orchestration is via **watsonx Orchestrate ADK** — the standard IBM agent framework.
