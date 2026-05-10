# 🚌 OSTA — Routing Agent for Alexandria Public Transport

> An AI-powered multi-modal transport assistant for Alexandria, Egypt.  
> Understands Arabic, English, and mixed queries — returns ranked journey options with fares, times, and maps.

---

## 📸 Preview

```
User: عايز اروح من العصافرة لسيدي بشر بارخص طريق

OSTA: أفضل 3 رحلة من العصافرة لـسيدي بشر:
  #1. ميكروباص  ⏱ 43 دقيقة | 💰 8 جنيه  | 🔄 0 تحويلة
  #2. ميكروباص  ⏱ 50 دقيقة | 💰 10 جنيه | 🔄 1 تحويلة
  #3. ميكروباص  ⏱ 54 دقيقة | 💰 10 جنيه | 🔄 1 تحويلة
```

---

## 🧠 What Makes It Smart

| Component      | Technology                     | Role                                  |
| -------------- | ------------------------------ | ------------------------------------- |
| Intent Parser  | Qwen2.5-3B + QLoRA             | Understands Arabic/English queries    |
| Geo Resolver   | PostgreSQL + PostGIS + pg_trgm | Converts stop names → GPS coordinates |
| Routing Engine | Azure (external API)           | Finds all possible routes             |
| Fare Model     | Linear Regression              | Predicts fare in EGP                  |
| Ranker         | MNL + LambdaRank (XGBoost)     | Sorts routes by user preference       |
| Memory         | Sliding-window session store   | Handles follow-ups naturally          |
| Frontend       | Streamlit + Folium             | Chat UI + interactive map             |

---

## 🗂 Project Structure

```
OSTA/
├── main.py                          # FastAPI entry point
├── config.py                        # All settings (env-driven)
│
├── model/                           # AI & ML models (this report covers this)
│   ├── intent/                      # Language understanding
│   │   ├── schema.py                # Pydantic data contracts (single source of truth)
│   │   ├── dataset.py               # Training data generator (1200+ examples)
│   │   ├── trainer.py               # QLoRA fine-tuning pipeline
│   │   ├── inference.py             # Runtime intent parser (3-layer fallback)
│   │   └── lora_adapter/            # Trained LoRA weights (included)
│   │       ├── adapter_config.json
│   │       ├── adapter_model.safetensors
│   │       ├── tokenizer.json
│   │       ├── tokenizer_config.json
│   │       └── chat_template.jinja
│   ├── fare/                        # Fare prediction
│   │   ├── price_predictor.py       # Linear regression wrapper
│   │   └── model.pkl                # Trained fare model (included)
│   ├── ranking/                     # Journey ranking
│   │   ├── mnl.py                   # Multinomial Logit baseline
│   │   ├── lambdarank.py            # XGBoost LambdaRank LTR model
│   │   ├── __init__.py              # RankingLayer orchestrator
│   │   ├── lambdarank_model.pkl     # Trained LTR model (included)
│   │   ├── lambdarank_scaler.pkl    # Feature scaler (included)
│   │   └── lambdarank_meta.json     # Model metadata & NDCG scores
│   └── memory/
│       └── conversation.py          # Sliding-window session memory
│
├── controller/                      # Business logic & tools
│   ├── agent.py                     # Main agent orchestrator
│   ├── tools/
│   │   ├── geo_tool.py              # Stop name → coordinates
│   │   ├── routing_tool.py          # Azure routing API client
│   │   └── db_tool.py               # PostgreSQL query layer
│   └── router.py                    # Intent → handler routing
│
├── view/                            # Frontend
│   └── streamlit_app/
│       ├── app.py                   # Main Streamlit UI
│       ├── journey_card.py          # Journey card components
│       └── map_view.py              # Folium map renderer
│
├── scripts/
│   └── train_ltr.py                 # Retrain LambdaRank model
│
├── final-project-database/          # PostgreSQL + PostGIS via Docker
│   └── docker-compose.yml
│
├── requirements.txt
└── .env.example
```

---

## ⚙️ Requirements

- Python **3.10**
- Docker & Docker Compose
- CUDA-capable GPU (**required** for intent model inference)
  - Tested on NVIDIA GPU with CUDA 11.8+
  - CPU-only mode works but intent parsing will be ~10× slower
- ~6GB free disk space (for Qwen2.5-3B base model, downloaded automatically on first run)

---

## 🚀 Quick Start

### Step 1 — Clone the repository

```bash
git clone https://github.com/your-username/osta-routing-agent.git
cd osta-routing-agent
```

### Step 2 — Create and activate virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux / macOS
source venv/bin/activate
```

### Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

### Step 4 — Configure environment

```bash
cp .env.example .env
```

Open `.env` and set the required values based in .env.example

### Step 5 — Start the database

Open **Terminal 1**:

```bash
cd final-project-database
docker compose up
```

Wait until you see:

```
database system is ready to accept connections
```

The database comes pre-loaded with:

- **441 stops** across Alexandria (with Arabic + English names)
- Full route, trip, and stop-time data
- PostGIS and pg_trgm extensions enabled

### Step 6 — Start the backend

Open **Terminal 2**:

```bash
python -m uvicorn main:app --host 0.0.0.0 --port 5000
```

Wait until you see:

```
TRANSPORT AGENT READY
Uvicorn running on http://0.0.0.0:5000
```

> ⚠️ First startup takes **~30 seconds** — the Qwen2.5-3B base model is loaded into GPU memory. Subsequent starts are faster due to caching.

### Step 7 — Start the frontend

Open **Terminal 3**:

```bash
python -m streamlit run view/streamlit_app/app.py
```

Open your browser at **http://localhost:8501**

---

## 💬 Example Queries

### Arabic

```
عايز اروح من العصافرة لسيدي بشر بارخص طريق
عايز اروح من محطة الرمل للمنتزه باسرع شكل ممكن
أقل تحويلات من سيدي جابر لأبو قير
عايز أروح من كرموز للمنشية بس مش أكتر من 15 جنيه
```

### English

```
cheapest route from Raml Station to Montaza
fastest way from Sidi Gaber to Abu Qir
minimum transfers from Ibrahimia to Asafra
```

### Mixed (Arabic + English)

```
أسرع route من العصافرة لـMontaza
cheapest طريقة من سيدي بشر للعصافرة
```

### Follow-ups (after an initial query)

```
طب وإيه لو أرخص؟          → re-rank by cheapest
وريني أكتر                 → show next 3 options
تفاصيل الأولى              → step-by-step for journey #1
باسرع شكل؟                 → re-rank by fastest
```

---

## 🤖 Model Details

### Intent Model — Qwen2.5-3B + QLoRA

The LoRA adapter weights are included in this repository (`model/intent/lora_adapter/`).  
The base model (`Qwen/Qwen2.5-3B-Instruct`) is downloaded automatically from HuggingFace on first run.

| Parameter         | Value                     |
| ----------------- | ------------------------- |
| Base model        | Qwen/Qwen2.5-3B-Instruct  |
| LoRA rank         | 8                         |
| LoRA alpha        | 16                        |
| Target layers     | q/k/v/o/gate/up/down_proj |
| Training examples | 1,200+ bilingual          |
| Adapter size      | 28.6 MB                   |

### Ranking Model — LambdaRank

Pre-trained model included (`model/ranking/lambdarank_model.pkl`).

| Metric           | Value                                      |
| ---------------- | ------------------------------------------ |
| Val NDCG@3       | **0.9982**                                 |
| Features         | 12 (8 journey + 4 user preference weights) |
| Training samples | 16,000 synthetic journeys                  |
| Trees            | 91                                         |

To retrain the ranking model from scratch:

```bash
python scripts/train_ltr.py
```

### Fare Model — Linear Regression

```
fare (EGP) = ceil(5.24 + 0.281 × distance_meters + (-0.113) × passengers)
```

Pre-trained model included (`model/fare/model.pkl`).

---

## 🏗 System Architecture

```
User Message
     │
     ▼
FastAPI /chat endpoint
     │
     ▼
IntentParser (Qwen2.5 + LoRA)
  → query_type, origin, destination, optimization, weights
     │
     ▼
ConversationMemory.resolve_intent()
  → fills missing fields from session history
     │
     ▼
GeoTool (pg_trgm + Nominatim fallback)
  → stop names → lat/lon coordinates
     │
     ▼
RoutingTool → Azure Routing Engine
  → raw journey list (up to 10 options)
     │
     ▼
FarePredictor → estimated EGP per journey
     │
     ▼
RankingLayer (MNL + LambdaRank)
  → sorted journeys with scores and reasons
     │
     ▼
ResponseBuilder → Arabic/English text
     │
     ▼
Streamlit UI → Journey cards + Folium map
```

---

## 🔄 Retraining

### Retrain LambdaRank (ranking model)

```bash
python scripts/train_ltr.py
```

Expected output:

```
Training LambdaRank model...
Training complete!
  Train NDCG@3: 0.9916
  Val   NDCG@3: 0.9982
  Trees:        91
```

### Retrain Intent Model (requires GPU + HuggingFace token)

```bash
# First generate training data
python model/intent/dataset.py

# Then fine-tune (runs on Google Colab T4 or local GPU)
python model/intent/trainer.py
```

> ⚠️ Intent model retraining requires ~16GB VRAM. Recommended: Google Colab with T4 GPU.  
> Set `HF_WRITE_TOKEN` in `.env` to push the adapter to HuggingFace Hub after training.

---

## 🗄 Database

The database runs in Docker and comes fully pre-loaded. No import steps needed.

```bash
cd final-project-database
docker compose up        # start
docker compose down      # stop (data persists)
docker compose down -v   # stop and delete all data
```

**Connection details (defaults):**

| Setting  | Value        |
| -------- | ------------ |
| Host     | localhost    |
| Port     | 5433         |
| Database | transport_db |
| User     | postgres     |
| Password | postgres     |

**What's inside:**

| Table          | Records | Description                                      |
| -------------- | ------- | ------------------------------------------------ |
| stop           | 441     | All Alexandria stops with Arabic + English names |
| route          | —       | Bus, microbus, metro, tram routes                |
| trip           | —       | Individual trips per route                       |
| route_stop     | —       | Stop sequences with arrival/departure times      |
| route_geometry | —       | PostGIS geometries for map display               |

---

## 🧪 Running Tests

```bash
# Install test dependencies
pip install pytest

# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_intent.py -v
```

### Manual test queries (copy-paste into the UI)

| Query                                        | Expected                      |
| -------------------------------------------- | ----------------------------- |
| `عايز اروح من العصافرة لسيدي بشر بارخص طريق` | journey_request, min_cost, AR |
| `fastest from Raml Station to Montaza`       | journey_request, min_time, EN |
| `طب وإيه لو أرخص؟`                           | followup, min_cost            |
| `وريني أكتر`                                 | show_more                     |
| `تفاصيل الأولى`                              | show_detail, result_index=1   |
| `كام تعريفة خط 42؟`                          | info_request, fare            |

---

## ⚠️ Known Limitations

- **سموحة and some neighbourhood names** are not in the 441-stop database. The system falls back to Nominatim (OpenStreetMap) which may return a nearby street instead of the exact neighbourhood.
- **Line names** from the routing engine are sometimes `None`. The system falls back to displaying the transport mode name (ميكروباص / Microbus).
- **Intent model inference** takes ~18–22 seconds per query on GPU. This is a known limitation of running a 3B parameter model locally.
- **LambdaRank** is trained on synthetic data generated by MNL — it learns to refine MNL rankings, not from real user preference data.
- **Fare model** uses fixed mode-based passenger counts (no real-time occupancy data).

---

## 📋 Environment Variables Reference

| Variable             | Required | Default                     | Description                                            |
| -------------------- | -------- | --------------------------- | ------------------------------------------------------ |
| `ROUTING_ENGINE_URL` | ✅       | —                           | Azure routing engine base URL                          |
| `DB_HOST`            | ✅       | `localhost`                 | PostgreSQL host                                        |
| `DB_PORT`            | ✅       | `5433`                      | PostgreSQL port                                        |
| `DB_NAME`            | ✅       | `transport_db`              | Database name                                          |
| `DB_USER`            | ✅       | `postgres`                  | Database user                                          |
| `DB_PASSWORD`        | ✅       | `postgres`                  | Database password                                      |
| `ADAPTER_SOURCE`     | ✅       | `local`                     | `local`, `hf`, or `none`                               |
| `LORA_ADAPTER_PATH`  | ✅       | `model/intent/lora_adapter` | Path to LoRA adapter                                   |
| `FARE_MODEL_PATH`    | ✅       | `model/fare/model.pkl`      | Path to fare model                                     |
| `HF_READ_TOKEN`      | ❌       | —                           | HuggingFace read token (for private repos)             |
| `HF_WRITE_TOKEN`     | ❌       | —                           | HuggingFace write token (for pushing after retraining) |
| `GEO_THRESHOLD`      | ❌       | `0.3`                       | Minimum pg_trgm similarity score                       |
| `GEO_NEAREST_RADIUS` | ❌       | `800`                       | Nearest stop search radius in meters                   |
| `MEMORY_WINDOW`      | ❌       | `5`                         | Conversation turns to keep in memory                   |
| `MAX_DISPLAYED`      | ❌       | `3`                         | Journeys shown per response                            |
| `TOP_K`              | ❌       | `10`                        | Routes requested from routing engine                   |

---

## 🛠 Tech Stack

| Layer       | Technology                                            |
| ----------- | ----------------------------------------------------- |
| Language    | Python 3.10                                           |
| Backend API | FastAPI + Uvicorn                                     |
| Frontend    | Streamlit + Folium                                    |
| Database    | PostgreSQL 15 + PostGIS + pg_trgm                     |
| Container   | Docker + Docker Compose                               |
| LLM         | Qwen2.5-3B-Instruct                                   |
| Fine-tuning | PEFT (LoRA) + TRL (SFTTrainer) + BitsAndBytes (4-bit) |
| Ranking     | XGBoost (LambdaRank) + scikit-learn                   |
| Fare model  | scikit-learn (LinearRegression)                       |
| Validation  | Pydantic v2                                           |
| Logging     | structlog                                             |
| HTTP client | httpx                                                 |

---

## 📄 License

This project was developed to guide you find your route (GradProject)

---

_OSTA — Your Alexandria Transport Assistant 🚌_
