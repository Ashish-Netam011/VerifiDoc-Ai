# VerifiDoc AI

## Hack-A-Sol 5.0 — AIML Track, Problem Statement 02, Option B

**Zero-Guessing & Contradiction-Checking Document AI**

### Project Overview

VerifiDoc AI is a document intelligence system that answers questions across multiple PDFs using **verifiable evidence**. Every generated claim is supported by exact documentary evidence, and contradictions between documents are detected and reported. The system abstains when sufficient evidence is unavailable — never guesses.

### Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| Frontend | React 18 + Vite 7 + Tailwind CSS 3 | User interface |
| Backend | Python 3.12 + FastAPI | REST API & business logic |
| PDF Processing | PyMuPDF | Page-aware text and detectable table extraction |
| Embeddings | intfloat/multilingual-e5-small (384-dim) | Semantic representation |
| Vector Search | NumPy exact cosine similarity | Local similarity search; FAISS is not wired into the runtime |
| Keyword Search | BM25 | Exact keyword retrieval |
| Reranking | cross-encoder/ms-marco-MiniLM-L-6-v2 | Bounded query-document relevance reranking |
| LLM Runtime | Hybrid: OpenRouter primary, Ollama fallback | Hosted generation with a local fallback |
| LLM | Gemini 3.7 Flash (`google/gemini-3.7-flash`) / Qwen 3.5 2B | Primary / fallback answer generation |
| Verification | cross-encoder/nli-deberta-base | Claim entailment, neutrality, and contradiction |
| Persistence | Atomic JSON files + NumPy NPZ index | Document catalogue, chunks, tables, and vectors |

### Architecture Principle

**Evidence first. Generation second. Verification always.**

The LLM drafts answers; verification gates validate them. PDF storage, retrieval,
embeddings, reranking, and verification remain local. OpenRouter is the primary
provider; if it is unavailable and fallback is enabled, the same request is sent
to the configured local Ollama instance. When OpenRouter handles a request,
question text, retrieved evidence excerpts, and filename/page/chunk labels leave
the machine; only use documents you are authorized to share with that service.

### AIML-02 Option B Compliance

| Requirement | Status | Scope and limitations |
|---|---|---|
| Zero-guessing answers, citation verification, and abstention | Implemented; regression-tested | Existing verification thresholds and abstention behavior remain authoritative. |
| Cross-document contradiction detection | MVP; regression-tested | Compares explicit numeric/date facts with source provenance and preserves both quotations. Candidate extraction is heuristic; it does not establish that all rule or eligibility conflicts will be found. |
| Amendment chains and as-of-date resolution | MVP; regression-tested | Links only explicit document references and usable effective dates; missing, ambiguous, and circular links remain unresolved. Upload recency is not treated as legal applicability. |
| Structured PDF table extraction | MVP; regression-tested | Uses PyMuPDF table detection, stores page/table/row provenance, and flags incomplete structures for review. Arbitrary PDF layouts are not guaranteed to extract correctly; ordinary text extraction remains the fallback. |
| Sentence-level faithfulness score | Implemented conservatively; regression-tested | Counts only exact normalized sentence-to-verified-claim matches with source quotations. Abstentions have no percentage; paraphrases may be undercounted. This is not a guarantee of legal correctness. |

These features provide evidence-oriented assistance, not legal advice or a guarantee that every contradiction, amendment, or table has been found or interpreted correctly. Verify displayed source passages in the original documents.

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

### Phase 0 Status (Historical Baseline)

Environment validated. See `docs/PHASE_0_FINAL_REPORT.md` for benchmarks, model verification results and known blockers.

Verified working: Python 3.12.10, FastAPI stack, PyMuPDF, sentence-transformers, `multilingual-e5-small` (384-dim, CPU), `nli-deberta-base` (CPU), Vite build and dev server.

At Phase 0, the FAISS native DLL was blocked by Windows Smart App Control and Ollama was not installed. These are historical Phase 0 findings, not the current runtime status. The Phase 5.2 report describes the earlier local-Qwen configuration; the current LLM provider is hybrid, with OpenRouter primary and Ollama fallback. See `docs/PHASE_5_2_FINAL_REVIEW_REPORT.md` for historical verification.

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

#### 3. Cache Retrieval and Verification Models

The backend loads Hugging Face checkpoints in local-only mode; it does not
download or silently substitute models during a request. Run this once from
`backend/` to cache E5, NLI, and the separate relevance reranker:

```powershell
$env:HF_HOME = (Resolve-Path "..\data\models_cache").Path
python -c "import os; from sentence_transformers import SentenceTransformer, CrossEncoder; cache=os.environ['HF_HOME']; SentenceTransformer('intfloat/multilingual-e5-small', cache_folder=cache); CrossEncoder('cross-encoder/nli-deberta-base'); CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"
```

The reranker is a distinct relevance model. Do not substitute the NLI model for
reranking. If the configured reranker checkpoint is missing, search and Q&A
return an explicit unavailable-model error.

The Hugging Face checkpoints are cached under `data/models_cache` (outside Git).

#### 4. Configure LLM providers

Open `backend/.env` and configure `OPENROUTER_API_KEY`. Never commit the key.
OpenRouter is the default primary provider and uses
`google/gemini-3.7-flash`. To enable local fallback, install Ollama, start
the Ollama service, and pull the configured fallback model:

```powershell
ollama pull qwen3.5:2b
```

By default, transient OpenRouter failures and missing credentials fall back to
Ollama. HTTP 401/403 does not fall back unless `LLM_FALLBACK_ON_AUTH_ERROR=true`
is explicitly set. Set `LLM_PROVIDER=ollama` to use only the local provider, or
set `LLM_FALLBACK_ENABLED=false` to disable fallback. The health endpoint
reports whether the primary or configured fallback is ready.

### Environment Variables

Defined in `backend/.env` (template: `backend/.env.example`).

| Variable | Value |
|---|---|
| `LLM_PROVIDER` | `hybrid` (`hybrid`, `openrouter`, or `ollama`) |
| `OPENROUTER_API_KEY` | Optional if Ollama fallback is available; configure locally |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` |
| `OPENROUTER_MODEL` | `google/gemini-3.7-flash` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` |
| `OLLAMA_MODEL` | `qwen3.5:2b` |
| `LLM_FALLBACK_ENABLED` | `true` |
| `LLM_FALLBACK_ON_AUTH_ERROR` | `false`; explicitly opt in to fallback for HTTP 401/403 |
| `EMBED_MODEL` | `intfloat/multilingual-e5-small` |
| `NLI_MODEL` | `cross-encoder/nli-deberta-base` |
| `RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| `RETRIEVAL_CANDIDATE_K` | `32` |
| `RERANK_CANDIDATE_K` | `32` |
| `LLM_NUM_CTX` | `8192` (Ollama context window) |
| `LLM_NUM_PREDICT` | `1024` (maximum generated tokens for either provider) |
| `HF_HOME` | `../data/models_cache` |
| `DATA_DIR` | `../data` (backend-relative, resolves to `E:\Desktop\ProofLens\data`) |
| `MAX_UPLOAD_MB` | `25` |
| `TOP_K` | `6` |
| `QA_MAX_CHUNKS_PER_DOCUMENT` | `2`: at most this many chunks per document in one unscoped answer, so cross-document questions are not answered from a single file; `0` disables it |
| `LLM_TIMEOUT_SECONDS` | `45` per provider request |
| `CORS_ORIGINS` | `http://localhost:5173` |

`DATA_DIR` and `HF_HOME` are resolved relative to the backend working directory, so every generated file stays inside `E:\Desktop\ProofLens\data`.

### Storage locations (all on E:)

VerifiDoc never writes documents, indexes or models to `C:`.

| Path | Contents |
|---|---|
| `E:\Desktop\ProofLens\data\pdfs\<document_id>\` | uploaded PDFs and their extracted `chunks.json` |
| `E:\Desktop\ProofLens\data\indexes\` | `documents.json` catalogue and `vectors\vector_index.npz` |
| `E:\Desktop\ProofLens\data\models_cache\` | Hugging Face models (E5, NLI, relevance reranker) |
| `E:\Desktop\ProofLens\data\tmp\` | throw-away test data, deleted after a passing test run |
| `E:\Desktop\ProofLens\backend\.venv\` | Python environment, ~1.5 GB |

To keep a test run's temporary data for debugging, set
`VERIFICDOC_KEEP_TEST_DATA=1` before running pytest. The legacy
`PROOFLENS_KEEP_TEST_DATA=1` variable is still supported.

### Model Licences

| Model | Licence | Notes |
|---|---|---|
| Gemini 3.7 Flash via OpenRouter | N/A | Subject to Google and OpenRouter terms; inference is hosted |
| Qwen 2.5 3B via Ollama | Apache-2.0 | Local fallback model; verify Ollama/model terms before redistribution |
| `intfloat/multilingual-e5-small` | MIT | 94 languages, 384 dims |
| `cross-encoder/nli-deberta-base` | Apache-2.0 | Trained on SNLI + MultiNLI |
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | Check the model card before redistribution | Dedicated relevance reranker; not used for NLI |
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
2. **At least one LLM provider must be available.** Configure `OPENROUTER_API_KEY` for hosted generation and/or install Ollama with the configured model for local generation/fallback.
3. **Hugging Face Xet downloads stall on this network.** Set `HF_HUB_DISABLE_XET=1` before downloading models.

### Team Responsibilities

| Member | Focus Area |
|---|---|
| **Member 1** (Team Lead) | Backend architecture, API contracts, database integration, deployment, final demo |
| **Member 2** | AI/ML engineer — embeddings, FAISS/fallback retrieval, BM25, OpenRouter integration, NLI verification, evidence pipeline |
| **Member 3** | Frontend engineer — React app, document library, chat interface, proof receipts, conflict dashboard, self-test console |

Member 2 owns the only machine that needs the AI models. Members 1 and 3 do not download model weights.

### Key Commands Summary

| Action | Command |
|---|---|
| Activate venv | `.\backend\.venv\Scripts\Activate.ps1` |
| Start backend | `cd backend && uvicorn app.main:app --reload --port 8000` |
| Start frontend | `cd frontend && npm run dev` |
| Build frontend | `cd frontend && npm run build` |
| Run tests | `cd backend && pytest` |
| Retrieval benchmark (recall@k, MRR, nDCG, per strategy) | `cd backend && python -m app.benchmark` |
| Q&A evaluation, RAGAS-style metrics | `cd backend && python -m app.evaluation --ragas-style` |

### License

See individual model terms above. Pay particular attention to PyMuPDF's AGPL conditions and the provider terms for hosted Claude inference.

---

**VerifiDoc AI — Evidence First. Every Claim Verified.**
