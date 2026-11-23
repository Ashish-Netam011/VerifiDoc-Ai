# Phase 5.0 - Runtime Stabilization Diagnostic Report

**Scope:** read-only diagnosis of ProofLens runtime model loading, Ollama
availability, HTTP 502 behavior, and test/environment failures.

**Constraint:** this phase began with no source modifications. The
implementation remediation is documented separately in the runtime report.

---

## 1. Environment

| Component | Observed |
| --- | --- |
| Operating system | Windows |
| Python | 3.12.10 |
| Virtual environment | `backend\.venv` |
| PyTorch | 2.15.0+cpu |
| CUDA | unavailable |
| sentence-transformers | 6.3.0 |
| transformers | 5.24.0 |
| huggingface_hub | 2.4.0 |
| NumPy | 2.5.5 |
| HTTP client | httpx 0.28.1 |
| Physical RAM | 16,788,983,808 bytes (about 16 GB) |
| Backend | FastAPI/Uvicorn on `127.0.0.1:8000` |
| Ollama | running; Qwen 2.5 3B Q4_K_M installed |

---

## 2. Model cache

Both required model caches are complete and available offline.

### E5

- model: `intfloat/multilingual-e5-small`
- snapshot:
  `data/models_cache/models--intfloat--multilingual-e5-small/snapshots/614241f622f53c4eeff9890bdc4f31cfecc418b3`
- size: approximately 470.4 MB
- required files observed:
  - `config.json`
  - `model.safetensors` (470,641,600 bytes)
  - `1_Pooling/`

### NLI

- model: `cross-encoder/nli-deberta-base`
- snapshot:
  `data/models_cache/hub/models--cross-encoder--nli-deberta-base/snapshots/f375a3f8bdba5a9ea9489179fe2f7b7d69c00b76`
- size: approximately 533.5 MB
- required files observed:
  - `config.json`
  - `model.safetensors` (556,806,836 bytes)
- label mapping observed:
  `{"0":"contradiction","1":"entailment","2":"neutral"}`

No cache replacement or model download was performed during diagnosis.

---

## 3. Reproduced failures

### 3.1 PyTorch inter-op thread configuration

The direct and pytest reproductions showed the first concrete runtime regression:

```text
RuntimeError: cannot set number of interop threads after parallel work has started
or set_num_interop_threads called
```

Both `EmbeddingService.ensure_loaded()` and `NLIService.ensure_loaded()` called:

```python
torch.set_num_threads(1)
torch.set_num_interop_threads(1)
```

`set_num_interop_threads()` is only valid before PyTorch starts parallel work.
Calling it after model/work initialization can fail even though imports and cache
files are valid. The failure was raised from loader configuration, before either
model could be instantiated in the failing pytest paths.

This is a real, reproduced root-cause defect in the loader code.

### 3.2 Combined model-suite memory/order behavior

Running E5 and NLI tests while the live backend process remained loaded showed
resource pressure:

- the live backend process consumed approximately 1.9 GB private memory;
- a combined test run could not load the NLI checkpoint;
- the full suite later reached a pytest `MemoryError` while formatting failures;
- 3 full-suite failures were visible near the model tests before the formatter
  crashed.

When the backend was stopped and model tests were rerun independently, E5/NLI
tests passed. This is evidence of Windows process-memory pressure, not an
invalid model cache or absent package.

No paging-file size failure was reproduced in the isolated final tests.
Current paging usage was bounded; the earlier audit's paging diagnosis was not
disproven, but the reproducible loader defect is the primary code failure.

### 3.3 Package/import behavior

Direct imports succeeded in the virtual environment:

- `torch`
- `sentence_transformers`
- `transformers`
- `huggingface_hub`
- `numpy`
- `httpx`

Therefore, the audit statement that packages were missing was not reproduced.
The packages exist and load.

---

## 4. Ollama diagnosis

`GET http://127.0.0.1:11434/api/tags` returned:

- Ollama is reachable.
- configured model `qwen2.5:3b-instruct` is installed.
- model format: GGUF Q4_K_M.
- Ollama was not the source of the interop-thread test failures.

The Ollama service maps timeout, unavailable, missing-model, and malformed
responses to the existing API contracts.

---

## 5. HTTP 502 diagnosis

The live `/api/ask` 502 report was not reproduced in the final diagnosis:

- `/api/ask` returned 200 for the unsupported question probe.
- the response correctly abstained with `decision=abstain`,
  `verification_status=not_verified`, and no claims.
- backend logs showed supported live requests reaching Ollama and returning
  generated JSON, rather than an Ollama 502.

A 502 remains a valid contract result for unusable/malformed Ollama output,
according to `qa_service.py` and `qa.py`, but the reproduced runtime defect was
the PyTorch inter-op thread configuration that occurred in model test paths.
The 502 audit finding could not be attributed to Ollama from the reproduced
live state.

---

## 6. Test evidence before remediation

### Real model pair

Before the interop fix:

- E5 tests: 5 passed, one missing-model error assertion mismatch.
- NLI tests: 7 failed, 3 passed.
- actual failures: `set_num_interop_threads` invoked after PyTorch work started.

### Core backend

- core retrieval/Q&A/sufficiency/abstention/citation selection:
  120 passed.

### Model-adjacent

- ingestion/embedding integration/vector/BM25 selection: 39 passed.

### Full suite

- earlier audit: 164 passed, 12 failed.
- final pre-remediation run showed model suites could pass or fail depending on
  process ordering and memory pressure.
- combined full-suite execution reached `MemoryError` while reporting test
  failures, consistent with insufficient free memory in the active process mix.

---

## 7. Precise root-cause conclusion

There are two separate, evidenced issues:

1. **Code defect:** loader calls `torch.set_num_interop_threads(1)` at a point
   where PyTorch may already have started parallel work. This caused the
   reproducible model-test failures.

2. **Resource pressure:** running the live backend and large model suites in the
   same 16 GB Windows environment can increase private memory enough to prevent
   combined test/NLI loading and pytest result formatting.

No evidence justified replacing E5, replacing NLI, weakening verification,
changing thresholds, changing API schemas, or downloading alternate models.
