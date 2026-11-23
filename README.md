# ProofLens AI

## Hack-A-Sol 5.0 — AIML Track, Problem Statement 02, Option B

**Zero-Guessing & Contradiction-Checking Document AI**

### Project Overview

ProofLens AI is a document intelligence system that answers questions across multiple PDFs using **verifiable evidence**. Every generated claim is supported by exact documentary evidence, and contradictions between documents are detected and reported. The system abstains when sufficient evidence is unavailable — never guesses.

### Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| Frontend | React 18 + Vite 7 + Tailwind CSS 3 | User interface |
| Backend | Python 3.12 + FastAPI | REST API & business logic |
| PDF Processing | PyMuPDF + pdfplumber | Text and table extraction |
| Embeddings | intfloat/multilingual-e5-small (384-dim) | Semantic representation |
| Vector Search | FAISS CPU (blocked — see limitations) | Similarity search |
| Keyword Search | BM25 | Exact keyword retrieval |
| LLM Runtime | Ollama | Local model inference |
| LLM | Qwen2.5-3B-Instruct (fallback 1.5B) | Answer generation |
| Verification | cross-encoder/nli-deberta-base | Semantic entailment |
| Database | SQLite | Metadata and structured records |

### Architecture Principle

**Evidence first. Generation second. Verification always.**

The LLM drafts answers; verification gates validate them. No paid external AI APIs are used.

### Repository Structure

```text
ProofLens/
│
├── frontend/              # React + Vite application
│   ├── index.html         # Vite entry point
│   └── src/
│       ├── components/    # UI primitives
│       └── pages/         # Library, Chat
├── backend/               # Python FastAPI application
│   ├── .venv/             # Virtual environment (not in Git)
│   ├── app/               # Source code modules
│   ├── requirements.txt
│   ├── .env.example       # Committed template
│   └── .env               # Local only (not in Git)
├── tests/                 # Unit and integration tests
├── demo_data/             # Demonstration PDFs and test questions
├── data/                  # Generated files + model cache (not in Git)
├── docs/                  # Documentation and reports
├── .gitignore
└── README.md
```

### Phase 0 Status

Environment validated. See `docs/PHASE_0_FINAL_REPORT.md` for benchmarks, model verification results and known blockers.

Verified working: Python 3.12.10, FastAPI stack, PyMuPDF, sentence-transformers, `multilingual-e5-small` (384-dim, CPU), `nli-deberta-base` (CPU), Vite build and dev server.

Verified blocked: FAISS native DLL (Windows Smart App Control), Ollama (not installed).

### Prerequisites

| Requirement | Verified value |
|---|---|
| Python | 3.12.10 |
| Node.js | 24.19.0 (LTS 18+ works) |
| npm | 12.2.3 |
| RAM | 16 GB |
| GPU | NVIDIA RTX 3050 Laptop, 4 GB VRAM |
| Free disk on E: | 73 GB |

### Installation

#### 1. Backend Setup

The virtual environment lives **inside `backend/`**, not at the repo root.

```powershell
Set-Location "E:\Desktop\ProofLens\backend"
python -m venv .venv                      # only if .venv does not exist
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create the local environment file:

```powershell
Copy-Item .env.example .env
```

Verify:

```powershell
python -c "import fastapi, uvicorn, pydantic, fitz; print('Backend dependencies OK')"
```

#### 2. Frontend Setup

```powershell
Set-Location "E:\Desktop\ProofLens\frontend"
npm install
npm run build     # production build check
npm run dev       # http://localhost:5173
```

#### 3. Ollama Installation (manual, required)

1. Download from the official page: https://ollama.com/download
2. Run the installer and launch Ollama.
3. Or, if winget is available: `winget install -e --id Ollama.Ollama`
4. Verify in a **new** terminal:

```powershell
ollama --version
ollama list
```

#### 4. Download AI Models

```powershell
# Primary LLM (~1.9 GB)
ollama pull qwen2.5:3b-instruct

# Fallback LLM (~1.0 GB) — only if 3B is too slow for the hardware
ollama pull qwen2.5:1.5b-instruct
```

Embedding and NLI models download automatically on first use from Hugging Face and cache into `data/models_cache` (outside Git).

### Environment Variables

Defined in `backend/.env` (template: `backend/.env.example`).

| Variable | Value |
|---|---|
| `OLLAMA_URL` | `http://localhost:11434` |
| `LLM_MODEL` | `qwen2.5:3b-instruct` |
| `EMBED_MODEL` | `intfloat/multilingual-e5-small` |
| `NLI_MODEL` | `cross-encoder/nli-deberta-base` |
| `HF_HOME` | `../data/models_cache` |
| `DATA_DIR` | `../data` (backend-relative, resolves to `E:\Desktop\ProofLens\data`) |
| `MAX_UPLOAD_MB` | `25` |
| `TOP_K` | `6` |
| `LLM_TIMEOUT_S` | `45` |
| `CORS_ORIGINS` | `http://localhost:5173` |

`DATA_DIR` and `HF_HOME` are resolved relative to the backend working directory, so every generated file stays inside `E:\Desktop\ProofLens\data`.

### Storage locations (all on E:)

ProofLens never writes documents, indexes or models to `C:`.

| Path | Contents |
|---|---|
| `E:\Desktop\ProofLens\data\pdfs\<document_id>\` | uploaded PDFs and their extracted `chunks.json` |
| `E:\Desktop\ProofLens\data\indexes\` | `documents.json` catalogue and `vectors\vector_index.npz` |
| `E:\Desktop\ProofLens\data\models_cache\` | Hugging Face models (E5, NLI), ~1.0 GB |
| `E:\Desktop\ProofLens\data\tmp\` | throw-away test data, deleted after a passing test run |
| `E:\Desktop\ProofLens\backend\.venv\` | Python environment, ~1.5 GB |
| `E:\Ollama_store\` | Ollama model blobs (via the `OLLAMA_MODELS` user variable), ~1.8 GB |

To keep a test run's temporary data for debugging, set `PROOFLENS_KEEP_TEST_DATA=1`
before running pytest.

### Model Licences

| Model | Licence | Notes |
|---|---|---|
| `qwen2.5:3b-instruct` | Apache-2.0 | Permissive local use |
| `intfloat/multilingual-e5-small` | MIT | 94 languages, 384 dims |
| `cross-encoder/nli-deberta-base` | Apache-2.0 | Trained on SNLI + MultiNLI |
| PyMuPDF | AGPL-3.0 | Review before any closed-source distribution |

### Local Execution

#### Start Backend

```powershell
Set-Location "E:\Desktop\ProofLens\backend"
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```

#### Start Frontend

```powershell
Set-Location "E:\Desktop\ProofLens\frontend"
npm run dev
```

Open http://localhost:5173.

### Known Environment Limitations

1. **FAISS is unavailable on this machine.** Windows Smart App Control blocks `_swigfaiss.pyd` (CodeIntegrity event 3118). Reinstalling will not fix this. Use WSL2 or the NumPy exact-search fallback documented in the Phase 0 report.
2. **Ollama is not installed.** Requires a manual installer run with administrator approval.
3. **Only 4 GB VRAM and ~2 GB free RAM during testing.** The 3B model will spill to CPU; expect slower inference.
4. **Hugging Face Xet downloads stall on this network.** Set `HF_HUB_DISABLE_XET=1` before downloading models.

### Team Responsibilities

| Member | Focus Area |
|---|---|
| **Member 1** (Team Lead) | Backend architecture, API contracts, database integration, deployment, final demo |
| **Member 2** | AI/ML engineer — embeddings, FAISS/fallback retrieval, BM25, Ollama integration, NLI verification, evidence pipeline |
| **Member 3** | Frontend engineer — React app, document library, chat interface, proof receipts, conflict dashboard, self-test console |

Member 2 owns the only machine that needs the AI models. Members 1 and 3 do not download model weights.

### Key Commands Summary

| Action | Command |
|---|---|
| Activate venv | `.\backend\.venv\Scripts\Activate.ps1` |
| Start backend | `cd backend && uvicorn app.main:app --reload --port 8000` |
| Start frontend | `cd frontend && npm run dev` |
| Build frontend | `cd frontend && npm run build` |
| List Ollama models | `ollama list` |
| Pull a model | `ollama pull qwen2.5:3b-instruct` |
| Run tests | `cd backend && pytest` |

### License

See individual model licences above. Pay particular attention to PyMuPDF's AGPL conditions and the selected Qwen model's licence.

---

**ProofLens AI — Evidence First. Every Claim Verified.**
