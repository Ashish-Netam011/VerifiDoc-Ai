# PHASE 0 — FINAL ENVIRONMENT REPORT

**Project:** ProofLens AI — Zero-Guessing & Contradiction-Checking Document AI
**Event:** HACK-A-SOL 5.0 · AIML Track · Problem Statement AIML-02, Option B
**Project root:** `E:\Desktop\ProofLens`
**Branch:** `main` (feature branches `feat/backend`, `feat/ai-ml`, `feat/frontend` present)
**Base commit:** `dafd0f6`

Every result below was produced by a command run on the project machine. Anything not executed is listed under **Pending tasks**, not under results.

---

## 1. Completed tasks

| Task | Status | Evidence |
|---|---|---|
| 1. Inspect project and hardware | Done | Git, toolchain, RAM/VRAM/disk all recorded below |
| 2. Ollama installation | **Not done — needs admin installer** | `ollama` not found on PATH, no `%USERPROFILE%\.ollama` |
| 3. LLM models | Blocked by Task 2 | — |
| 4. Embedding model verification | **Done** | 384-dim, correct similarity ordering, 0.154 s / 4 sentences |
| 5. FAISS troubleshooting | Done (blocker diagnosed) | Smart App Control event 3118 |
| 6. Vite dev server | **Done — root cause found and fixed** | `npm run build` passes, dev server answers HTTP 200 |
| 7. NLI model selection | **Done** | entailment 0.993 vs contradiction 0.994 on the test pair |
| 8. Environment configuration | Done | `backend/.env.example` + local `backend/.env` |
| 9. Team setup guide | Done | Section 8 of this report + README |

---

## 2. Hardware and toolchain (measured)

| Item | Value |
|---|---|
| CPU | Intel Core 5 210H — 8 cores / 12 threads |
| RAM | 15.6 GB total (2.1 GB free while testing) |
| GPU | NVIDIA GeForce RTX 3050 Laptop GPU — **4 GB VRAM** |
| GPU (integrated) | Intel Graphics |
| Disk E: | 293 GB total, 73 GB free |
| Python | 3.12.10 |
| Node.js | 24.19.0 |
| npm | 12.2.3 |
| Git | repository intact, working tree clean apart from this phase's edits |

**Constraint to design around:** 4 GB VRAM and ~2 GB free RAM. The 3B LLM will not fit entirely in VRAM, so partial CPU offload is expected and normal. Nothing in the architecture needs to change; only latency expectations do.

---

## 3. Backend dependency verification

```text
python -c "import fastapi, uvicorn, pydantic, fitz; print('Backend dependencies OK')"
→ Backend dependencies OK
```

Installed in `E:\Desktop\ProofLens\backend\.venv` (Python 3.12.10):

| Package | Version |
|---|---|
| fastapi | 0.165.0 |
| uvicorn | via `uvicorn[standard]` |
| pydantic | 2.14.4 |
| sqlmodel | 0.0.50 |
| SQLAlchemy | 2.1.9 |
| torch (CPU) | 2.15.0 |
| sentence-transformers | 6.3.0 |
| transformers/tokenizers | 0.23.3 (tokenizers) |
| numpy | 2.5.5 |
| PyMuPDF (`fitz`) | 2.1 |
| pdfplumber | 0.11.11 |
| rank-bm25 | 0.2.2 |
| faiss-cpu | 1.16.0 (installed, **cannot import** — see §6) |
| pytest | 9.2.0 |
| scikit-learn | 1.9.1 |
| onnxruntime | 1.32.0 |

Note: `import fitz` emits a `FutureWarning` — upstream renamed the module to `pymupdf`. New code should use `import pymupdf`. Existing `import fitz` calls still work.

---

## 4. Embedding model verification — PASS

**Model:** `intfloat/multilingual-e5-small` · **Licence: MIT** · 94 languages
**Cache:** `E:\Desktop\ProofLens\data\models_cache` (gitignored, outside the repository)

```text
LOAD_S=317.05            # first run, includes the download
DIM= 384
ENCODE_S=0.154           # 4 sentences, CPU
sim q-vs-8pct=0.8223  q-vs-8pct-text=0.8619  8pct-vs-8pct-text=0.9439  q-vs-cat=0.6444
SHAPE (4, 384)
```

Interpretation:

- Output dimension is **384** — this fixes the FAISS/fallback index dimension.
- Two phrasings of the same 8% clause score **0.9439**; the query matches them at 0.82–0.86; the unrelated sentence scores **0.6444**. Correct ordering, so the model separates related from unrelated text.
- CPU encoding is fast enough for interactive use.
- 317 s load time is a **one-time** download, not steady-state load. Warm loads read from the local cache.

**E5 detail that matters for Phase 1:** passages must be prefixed `passage: ` and queries `query: `. Skipping the prefix degrades retrieval quality silently.

---

## 5. NLI model verification — PASS

**Model:** `cross-encoder/nli-deberta-base` · **Licence: Apache-2.0** (~0.5 GB)
Trained on SNLI + MultiNLI; labels are `contradiction`, `entailment`, `neutral`. MNLI-mismatched accuracy 88.08 (SBERT reference).

Premise: *"The borrower must pay an annual interest rate of 8%."*

| Hypothesis | entailment | neutral | contradiction |
|---|---|---|---|
| "The borrower must pay 8% annual interest." | **0.9930** | 0.0060 | 0.0010 |
| "The borrower must pay 12% annual interest." | 0.0007 | 0.0053 | **0.9940** |

```text
LATENCY_PER_PAIR_S=0.112
RSS_MB=1018
```

The model cleanly separates restatement from contradiction, with ~112 ms per pair on CPU and ~1 GB RSS. At that speed, verifying 6 retrieved chunks per answer costs well under a second.

**Caveat carried into Phase 1:** this model is an NLI component, not proof. It is trained on general English inference and will be wrong on subtle legal wording ("shall" vs "may", effective-date ranges, defined terms). It must gate claims inside the verification pipeline — combined with evidence-span matching and numeric consistency checks — never be treated as a standalone truth oracle. Legal-domain NLI is also weaker than the 88% benchmark suggests.

**No model change required.** If RAM pressure appears alongside Ollama, the lightweight fallback is `cross-encoder/nli-distilroberta-base` (MNLI-m 83.98). Trade-off: ~5 accuracy points and weaker handling of numeric contradiction, in exchange for roughly half the memory. Keep `nli-deberta-base` as the choice.

---

## 6. FAISS verification — BLOCKED (confirmed, not fixable by reinstall)

```text
python -c "import faiss; print('FAISS working:', faiss.__version__)"

File "...\faiss\swigfaiss.py", line 10, in <module>
    from . import _swigfaiss
ImportError: DLL load failed while importing _swigfaiss:
An Application Control policy has blocked this file.
```

Diagnosis: this is **not** a package incompatibility.

- `faiss-cpu 1.16.0` is installed correctly and `_swigfaiss.pyd` exists on disk.
- Windows CodeIntegrity log, same timestamp as the failure:
  - Event **3118** — "Smart App Control Block Details"
  - Event **3077** — `python.exe attempted to load ...`
- Smart App Control blocks unsigned native binaries. `_swigfaiss.pyd` has no trusted signature.

Consequences:

- **Do not reinstall `faiss-cpu`.** It will fail identically.
- **Do not disable Smart App Control** or download third-party DLLs. Windows requires a reset to re-enable SAC, and unsigned DLLs from anywhere but Meta's official wheels are a supply-chain risk.
- FAISS remains the preferred vector-search implementation in the architecture. It will work unchanged on any machine without Smart App Control (most team laptops, and any Linux/WSL2 environment).

### Temporary retrieval fallback (no architecture change)

NumPy exact cosine search over the same 384-dim normalized vectors. Measured on this machine:

| Index size | Time per query |
|---|---|
| 1,000 vectors | 1.2 ms |
| 10,000 vectors | 2.0 ms |
| 50,000 vectors | 5.3 ms |

A hackathon demo has a few thousand chunks at most, so brute-force search is **faster than the rest of the RAG pipeline** and is exact rather than approximate. Implementation rule for Phase 1: keep one small `VectorStore` interface with `add(vectors, metadata)` and `search(query, k)`; back it with FAISS when importable and NumPy otherwise. The rest of the pipeline never learns which backend is active.

---

## 7. Vite verification — PASS after fixing three real defects

The "Rollup binary blocked" diagnosis was **incorrect on this machine**. Rollup 4.68.8 loads and runs normally. The build failed for three source-level reasons, all now fixed:

| # | Defect | Fix |
|---|---|---|
| 1 | `frontend/index.html` did not exist, so Vite had no entry module | Created `frontend/index.html` mounting `/src/main.jsx` into `#root` |
| 2 | `src/pages/*.jsx` imported `@/components/ui`, which did not exist and had no path alias | Added `frontend/src/components/ui.jsx` (Container, Card, CardHeader, CardTitle, CardContent) and the `@` to `src` alias in `vite.config.js` |
| 3 | `postcss.config.js` and `tailwind.config.js` used CommonJS while `package.json` sets `"type": "module"`; PostCSS also registered `tailwind` instead of `tailwindcss` | Converted both to ESM `export default`, corrected the plugin name |

Results:

```text
npm run build
✓ 34 modules transformed.
dist/index.html                   0.46 kB │ gzip:  0.30 kB
dist/assets/index-BEAHSaYQ.css    5.79 kB │ gzip:  1.69 kB
dist/assets/index-B22nQ5ZV.js   159.33 kB │ gzip: 52.17 kB
✓ built in 2.58s
```

```text
npm run dev
VITE v7.3.8  ready in 498 ms
GET http://localhost:5173/ → 200
```

Tailwind is compiling (5.79 kB stylesheet emitted from the `@tailwind` directives). Versions: vite 7.3.8, @vitejs/plugin-react 4.7.0, rollup 4.68.8, react 18.3, tailwindcss 3.4.17.

Housekeeping for Phase 1: `frontend/dist/` is not covered by `.gitignore` yet; add it so build output is never committed.

**If another machine reports a genuine Rollup block,** it is a separate issue: check `Get-WinEvent -LogName Microsoft-Windows-CodeIntegrity/Operational`, then use WSL2 or an approved machine. Do not swap Vite or Rollup versions.

---

## 8. Environment configuration (Task 8)

`backend/.env.example` was rewritten. The old template still carried the placeholder `NLI_MODEL=YOUR_SELECTED_NLI_CHECKPOINT`, a stray `[TEMPLATE]` first line, and `DATA_DIR=./data`, which resolves to `backend/data` and would have scattered generated files outside the mandated folder.

Final values, identical in `.env.example` and the local `.env`:

```env
OLLAMA_URL=http://localhost:11434
LLM_MODEL=qwen2.5:3b-instruct
EMBED_MODEL=intfloat/multilingual-e5-small
NLI_MODEL=cross-encoder/nli-deberta-base
HF_HOME=../data/models_cache
DATA_DIR=../data
MAX_UPLOAD_MB=25
TOP_K=6
LLM_TIMEOUT_S=45
CORS_ORIGINS=http://localhost:5173
```

`DATA_DIR` and `HF_HOME` are backend-relative, so everything lands inside `E:\Desktop\ProofLens\data`.

`git check-ignore -v backend/.env` returns `.gitignore:4:.env	backend/.env`, so **`.env` is ignored — confirmed.**

Model identifiers match what is actually installed: the embedding and NLI identifiers are verified against downloaded checkpoints. `LLM_MODEL` stays unverified until Ollama is installed (Task 3).

---

## 9. Pending tasks

| # | Task | Blocker | Next action |
|---|---|---|---|
| 1 | Install Ollama | Needs an administrator install | Run the installer from https://ollama.com/download, or `winget install -e --id Ollama.Ollama` |
| 2 | `ollama pull qwen2.5:3b-instruct` (~1.9 GB) | Needs Ollama running | Run after installation, then `ollama list` |
| 3 | LLM latency and VRAM measurement | Needs the model pulled | Measure once Ollama runs; compare 1.5B only if 3B is unusable |
| 4 | `backend/app/main.py` | Out of Phase 0 scope | Phase 1 — Backend Foundation |
| 5 | `.gitignore` missing `frontend/dist/` | Housekeeping | Add in Phase 1 |

Nothing here blocks Phase 1 planning, but item 3 must close before any LLM-dependent code is tested.

---

## 10. Known blockers and limitations

1. **FAISS blocked by Smart App Control** (CodeIntegrity event 3118). Use the NumPy fallback here and FAISS elsewhere. Do not disable the security policy.
2. **Ollama not installed.** Requires a manual, administrator-approved install.
3. **4 GB VRAM and about 2 GB free RAM during testing.** The 3B model offloads to CPU. Budget 5–20 s per answer; `LLM_TIMEOUT_S=45` is already set accordingly, so do not shorten it.
4. **Hugging Face Xet transfers stall on this network.** The e5 pull stalled at 0 % and the NLI pull sat at 0 bytes until retried with `HF_HUB_DISABLE_XET=1`. Always set that variable before pulling models here.
5. **No symlink support in the HF cache** (Developer Mode off), so cached blobs are duplicated on disk. Harmless.
6. **Download throughput is roughly 0.7 MB/s.** Plan model downloads well before demo time.

---

## 11. Team setup instructions

Clone once; each member works on their own feature branch. Only **Member 2** needs model weights.

### All members — first 5 minutes

```powershell
git clone <repo-url> E:\Desktop\ProofLens
Set-Location "E:\Desktop\ProofLens"
```

### Member 1 — Backend environment

```powershell
Set-Location "E:\Desktop\ProofLens\backend"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -c "import fastapi, uvicorn, pydantic, fitz; print('Backend dependencies OK')"
```

Expect `Backend dependencies OK`; the `fitz` deprecation warning is normal. If `faiss-cpu` fails to import on your machine, that is your machine's Application Control policy — which is why Phase 1 code must not hard-import FAISS at module load.

### Member 2 — AI/ML environment (primary AI machine)

```powershell
Set-Location "E:\Desktop\ProofLens\backend"
.\.venv\Scripts\Activate.ps1

# Required on this network to avoid stalled downloads
$env:HF_HOME="E:\Desktop\ProofLens\data\models_cache"
$env:HF_HUB_DISABLE_XET="1"

python -c "from sentence_transformers import SentenceTransformer; m=SentenceTransformer('intfloat/multilingual-e5-small'); print(m.get_sentence_embedding_dimension())"
# expect: 384   (first run downloads about 470 MB)

python -c "from sentence_transformers import CrossEncoder; m=CrossEncoder('cross-encoder/nli-deberta-base'); print(m.predict([('The rate is 8%.','The rate is 12%.')]))"
# expect: a score row where 'contradiction' wins
```

Then install Ollama from https://ollama.com/download and pull the model:

```powershell
ollama --version
ollama pull qwen2.5:3b-instruct
ollama list
```

Do not pull both LLMs unless the 3B proves unusable.

### Member 3 — Frontend environment

```powershell
Set-Location "E:\Desktop\ProofLens\frontend"
npm install
npm run build
npm run dev
```

Open http://localhost:5173. React, Vite and Tailwind only — no Python and no models.

### Shared rules

- Never commit `.env`, `.venv/`, `node_modules/` or `data/`.
- `backend/.venv` lives inside `backend/`, not at the repository root.
- Generated files stay in `E:\Desktop\ProofLens\data`.
- On a machine without Smart App Control, FAISS simply works; keep code portable both ways.

---

## 12. Phase 0 exit criteria

| Criterion | Result |
|---|---|
| Repository intact, no second project created | Pass — one repo at `E:\Desktop\ProofLens`, history preserved |
| Backend dependencies import | Pass |
| Frontend builds and serves | Pass |
| Embedding model loads and embeds on CPU | Pass (384-dim) |
| NLI model separates entailment from contradiction | Pass |
| Configuration matches installed models | Pass (LLM pending Ollama) |
| Local LLM answering | **Pending — Ollama install required** |
| FAISS vector search | **Blocked — fallback documented** |

**Verdict:** the environment is ready for **Phase 1 — Backend Foundation**, with the LLM runtime pending a manual install and FAISS replaced on this machine by a documented, portable fallback.
