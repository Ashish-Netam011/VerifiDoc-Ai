# Phase 5.0 - ProofLens Runtime Stabilization Report

**Scope:** minimal remediation and verification of ProofLens real model loading
and live `/api/ask` behavior.

**Constraint:** no API schema changes, no model replacement, no threshold
changes, no verification weakening, no data deletion, and no unnecessary
package installation.

---

## 1. Root cause

The reproducible code defect was PyTorch thread configuration in the lazy E5
and NLI loaders:

- `torch.set_num_interop_threads(1)` could be called after PyTorch had already
  started parallel work;
- this raised `RuntimeError` before model loading and was misreported as a
  model/runtime failure;
- the 502 probe was not attributable to Ollama from the live state; unsupported
  live `/api/ask` correctly returned 200 with abstention.
- combined live/backend plus model-suite process memory can create a separate
  resource-pressure failure on this 16 GB Windows machine.

The local E5 and NLI caches are complete and offline loading is preserved.

---

## 2. Files modified

| File | Change |
| --- | --- |
| `backend/app/config.py` | Set BLAS/OpenMP worker environment variables at import time to one thread. This prevents native worker multiplication on CPU-only Windows loads. |
| `backend/app/services/embedding_service.py` | Make PyTorch thread configuration tolerant of already-started runtimes; preserve typed E5 load errors and offline loading. |
| `backend/app/services/nli_service.py` | Apply the same tolerant PyTorch setup; preserve cached/offline NLI loading, label mapping, and typed NLI errors. |
| `docs/PHASE_5_0_DIAGNOSTIC_REPORT.md` | Read-only diagnosis, root-cause evidence, and test baseline. |
| `docs/PHASE_5_0_RUNTIME_REPORT.md` | This final runtime remediation report. |

No API module or response schema was modified.

---

## 3. Environment and dependency changes

### Environment

- no OS setting or paging-file configuration was changed;
- no model, document, index, or `.env` file was replaced;
- no virtual environment was recreated;
- no package was installed.

### Dependencies

- existing sentence-transformers 6.3.0 remains in use;
- existing torch 2.15.0+cpu remains in use;
- existing transformers 5.24.0 remains in use;
- existing cached E5 and NLI snapshots remain in use;
- no alternate model or fallback model was introduced.

---

## 4. Test results before and after

### Before remediation

| Group | Result |
| --- | --- |
| Core retrieval/Q&A/sufficiency/abstention/citation selection | 120 passed |
| Combined audit-era full suite | 164 passed, 12 failed |
| Reproduced real-model pair | E5/NLI loader interop-thread failures, and resource-sensitive NLI loading |

The combined suite had 12 audit-era failures, primarily model runtime failures.
A later combined run also hit pytest `MemoryError` while formatting failures while
the live backend held about 1.9 GB private memory.

### After remediation

| Group | Result |
| --- | --- |
| Real E5 and NLI tests | 17 passed |
| Core backend selection | 120 passed |
| Ingestion/embedding integration/vector/BM25 selection | 39 passed |
| NLI/citation selection | 35 passed |
| Live health/documents/search/ask | passed |

The model suites pass in a clean process after the live backend is stopped.
The 17 real-model tests include E5 dimension, normalization, prefix, ranking,
NLI offline loading, label mapping, entailment, contradiction, neutral, and
batch-score checks.

---

## 5. Live API results

### Health

`GET /api/health` returned:

- status: `ok`
- backend version: `0.2.0`
- Ollama available: `true`
- model: `qwen2.5:3b-instruct`
- model present: `true`

### Documents

`GET /api/documents` returned 5 processed documents and did not modify or delete
any existing document/index data.

### Search

`POST /api/search` for `architecture`, `top_k=3`, returned 3 real hits.
Cold live search timing: 10.190 seconds.

### Supported ask

Cold ask question:

> What does the ProofLens AI architecture document say about hybrid dense plus
> BM25 retrieval?

Result:

- HTTP 200
- decision: `answer`
- verification: `verified`
- claims: 1
- conflicts: 0
- cold latency: 4.645 seconds

Three warm repeats:

| Run | Seconds | Decision | Verification |
| --- | --- | --- | --- |
| 1 | 2.995 | answer | verified |
| 2 | 2.579 | answer | verified |
| 3 | 2.904 | answer | verified |

### Unsupported ask

Cold unsupported question:

> What is the landlord annual income in the ProofLens AI architecture document?

Result:

- HTTP 200
- decision: `abstain`
- verification: `not_verified`
- claims: 0
- conflicts: 0
- cold latency: 2.112 seconds

### Contradiction probe

Cold contradiction question:

> According to the documents, is the rent 15000 or 18000?

Result:

- HTTP 200
- decision: `abstain`
- verification: `not_verified`
- claims: 0
- conflicts: 0
- cold latency: 1.043 seconds

No live ask returned 502 in the final cold/warm verification run.

---

## 6. Model loading and inference timings

Direct real-model measurements:

| Operation | Timing |
| --- | --- |
| E5 cold load + 384-d query embedding | 12.187 seconds |
| NLI cold load + two-pair scoring | 9.766 seconds |
| Cold live search | 10.190 seconds |
| Cold supported live ask | 4.645 seconds |
| Cold unsupported live ask | 2.112 seconds |
| Cold contradiction probe | 1.043 seconds |
| Warm supported live ask | 2.579–2.995 seconds |

These timings are from CPU-only Windows inference and are not throughput claims.

---

## 7. Remaining limitations

1. Combined full-suite execution and live inference should not run concurrently
   in this 16 GB environment. The live backend held about 1.9 GB private memory
   during one reproduction.
2. The current suite may need to be run in separate process groups in this
   environment rather than as one monolithic 176-test process.
3. No Windows paging change was made. Paging usage was not the reproduced
   definitive cause of the loader fix.
4. The contradiction probe returned abstention with no generated claim for the
   selected corpus; this verifies abstention behavior but not a live
   two-source contradiction UI scenario.
5. `fitz` deprecation emitted a FutureWarning; this is not a runtime blocker and
   was not changed in this phase.
6. A dedicated GPU/CUDA backend is not installed or required for current CPU
   operation.

---

## 8. Readiness

ProofLens is ready to proceed to new feature development at the runtime
foundation level:

- real E5 loading and embedding: verified;
- real NLI loading and relation scoring: verified;
- citation verification and abstention: preserved;
- `/api/health`: verified;
- `/api/documents`: verified;
- `/api/search`: verified;
- `/api/ask` supported: verified;
- `/api/ask` unsupported: verified;
- `/api/ask` contradiction-shaped probe: abstained cleanly.

The remaining risk is process-memory pressure when model-heavy tests and the
live server run concurrently, not missing model files or a broken verification
architecture.
