# ProofLens AI

## Hack-A-Sol 5.0 — AIML Track, Problem Statement 02, Option B

**Zero-Guessing & Contradiction-Checking Document AI**

### Project Overview

ProofLens AI is a document intelligence system that answers questions across multiple PDFs using **verifiable evidence**. Every generated claim is supported by exact documentary evidence, and contradictions between documents are detected and reported. The system abstains when sufficient evidence is unavailable — never guesses.

### Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| Frontend | React 18 + Vite + Tailwind CSS | User interface |
| Backend | Python 3.11 + FastAPI | REST API & business logic |
| PDF Processing | PyMuPDF + pdfplumber | Text and table extraction |
| Embeddings | multilingual-e5-small | Semantic representation |
| Vector Search | FAISS CPU | Similarity search |
| Keyword Search | BM25 | Exact keyword retrieval |
| LLM Runtime | Ollama | Local model inference |
| LLM | Qwen2.5-3B-Instruct | Answer generation |
| Verification | DeBERTa-based NLI | Semantic entailment |
| Database | SQLite | Metadata and structured records |

### Architecture Principle

**Evidence first. Generation second. Verification always.**

The LLM drafts answers; verification gates validate them. No paid external AI APIs are used.

### Repository Structure

```text
prooflens/
│
├── frontend/           # React + Vite application
├── backend/            # Python FastAPI application
│   ├── app/            # Source code modules
│   ├── requirements.txt
│   └── .env.example
├── tests/              # Unit and integration tests
├── demo_data/          # Demonstration PDFs and test questions
├── docs/               # Documentation and PRD
├── .gitignore
└── README.md
```

### Prerequisites

#### System Requirements
- Python 3.11 (3.12 compatible)
- Node.js LTS (v18+ recommended)
- Git
- 16 GB RAM minimum
- NVIDIA GPU with 4GB+ VRAM (for Ollama LLM inference)
- Windows 10/11 or macOS or Linux

#### Python Dependencies
- `python -m venv .venv` and activate
- `pip install -r backend/requirements.txt`

#### Node.js Dependencies
- `cd frontend && npm install`

### Installation

#### 1. Backend Setup

```powershell
# Clone or navigate to project
cd e:\Desktop\ProofLens

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r backend/requirements.txt

# Verify installation
python -c "import fastapi; print('FastAPI OK')"
python -c "import uvicorn; print('Uvicorn OK')"
```

#### 2. Frontend Setup

```powershell
cd e:\Desktop\ProofLens\frontend

# Install dependencies
npm install

# Start development server
npm run dev
# Available at: http://localhost:5173
```

#### 3. Ollama Installation

1. Download Ollama from: https://ollama.com/download
2. Install and launch the application
3. Verify it's running: `ollama list`

#### 4. Download AI Models

```powershell
# Pull primary LLM (Qwen2.5 3B Instruct)
ollama pull qwen2.5:3b-instruct

# Pull fallback LLM (Qwen2.5 1.5B Instruct)
ollama pull qwen2.5:1.5b-instruct

# Verify models available
ollama list

# The embedding model (multilingual-e5-small) is loaded on-demand
# The NLI model will be selected and cached during setup
```

### Local Execution

#### Start Backend Only

```powershell
cd e:\Desktop\ProofLens
.venv\Scripts\activate
cd backend
uvicorn app.main:app --reload --port 8000
# API available at: http://localhost:8000
# Health: http://localhost:8000/health
```

#### Start Frontend Only

```powershell
cd e:\Desktop\ProofLens\frontend
npm run dev
# Available at: http://localhost:5173
```

#### Start Both (recommended)

1. Start backend in one terminal: `uvicorn app.main:app --reload --port 8000`
2. Start frontend in another terminal: `npm run dev`
3. Open browser to: http://localhost:5173

### Team Responsibilities

| Member | Focus Area |
|---|---|
| **Member 1** (Team Lead) | Backend architecture, API contracts, database integration, deployment, final demo |
| **Member 2** | AI/ML engineer — embeddings, FAISS, BM25, Ollama integration, NLI verification, evidence pipeline |
| **Member 3** | Frontend engineer — React app, document library, chat interface, proof receipts, conflict dashboard, self-test console |

### Key Commands Summary

| Action | Command |
|---|---|
| Activate venv | `.\backend\.venv\Scripts\activate` |
| Start backend | `cd backend && uvicorn app.main:app --reload --port 8000` |
| Start frontend | `cd frontend && npm run dev` |
| List Ollama models | `ollama list` |
| Pull a model | `ollama pull qwen2.5:3b-instruct` |
| Run tests | `cd backend && pytest` |
| Build frontend | `cd frontend && npm run build` |

### License

See individual model licences in the README and `.env.example`. Pay particular attention to PyMuPDF's AGPL conditions and the selected Qwen model's licence.

---

**ProofLens AI — Evidence First. Every Claim Verified.**