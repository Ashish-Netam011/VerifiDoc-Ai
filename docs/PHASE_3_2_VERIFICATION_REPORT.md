# Phase 3.2 — Citation Integrity & Claim Verification Engine

Report date: 2026-11-23
Scope: `E:\Desktop\ProofLens`, backend only. Model: cached `cross-encoder/nli-deberta-base`.
Status: implemented, unit/integration tested, live-verified against a running server and the real NLI model.

Everything below marked "measured" was produced on this machine in this phase. Anything not
measured is listed under [What this report does not claim](#what-this-report-does-not-claim).

---

## 1. What was added

| File | Role |
| --- | --- |
| `backend/app/services/nli_service.py` | Offline NLI loader/scorer: `NLIService`, `NLIScores`, `NLIError`, `resolve_local_snapshot`, `get_nli_service`, `reset_nli_service` |
| `backend/app/services/citation_verifier.py` | Citation integrity checks, numeric safeguards, verdict aggregation: `CitationRecord`, `EvidenceRecord`, `CitationVerifier`, `ClaimVerification`, `VerificationStatus`, `check_citation`, `extract_numbers`, `numeric_conflict`, `get_citation_verifier` |
| `backend/tests/test_nli.py` | 10 tests, real model (load, label map, three relations, negation, batch, failure modes) |
| `backend/tests/test_citation_verifier.py` | 25 tests with a scripted NLI stub + one whitespace-normalisation regression test |
| `backend/app/services/qa_service.py` | Wires the verifier into `QAService.answer`, attaches per-claim verdicts, computes `verification_status` |
| `backend/app/routers/qa.py` | `AskVerification`, `AskEvidenceAssessment`, `AskClaim.verification`, widened `verification_status` |
| `backend/tests/conftest.py` | Autouse deterministic verifier fixture (API tests never load the 700 MB model) |
| `backend/tests/test_qa.py` | 2 new tests (contradicted answer, verification unavailable); Phase 3.1 status assertion updated |
| `backend/.env`, `backend/.env.example` | `NLI_BATCH_SIZE`, `NLI_ENTAILMENT_THRESHOLD`, `NLI_CONTRADICTION_THRESHOLD` (alongside existing `NLI_MODEL`) |

`/api/search`, ingestion, retrieval, BM25 and the vector store are unchanged.

## 2. NLI label mapping — read from the checkpoint, not assumed

The checkpoint's `config.json` maps `0 → contradiction`, `1 → entailment`, `2 → neutral`.
The service reads `id2label` from the loaded model config and fails with `NLIError` if the
mapping is missing, incomplete, non-contiguous, or contains an unknown label. The common
wrong assumption that entailment is class 2 would silently invert every verdict; this is
asserted in `test_label_mapping_comes_from_model_config`, which recomputes the expected map
from `config.json` and compares it with the service's map.

Premise = evidence chunk, hypothesis = generated claim. Neutral is never treated as support.

## 3. Loading model files offline

`SentenceTransformer` resolves the cached snapshot itself only when the repository layout is
`models--…/snapshots/<rev>` directly under the cache root (as E5 is). The NLI repo lives under
`data/models_cache/hub/models--cross-encoder--nli-deberta-base/snapshots/f375a3f8…`, so
`resolve_local_snapshot()` resolves that path and the model is constructed from it with
`local_files_only=True`. No network access, no new downloads; a docs/id mismatch raises
`NLIError("… not present in the local cache")` instead of silently fetching.

## 4. Thresholds and precedence

Configured by environment (defaults in parentheses):

- `NLI_ENTAILMENT_THRESHOLD` (0.60)
- `NLI_CONTRADICTION_THRESHOLD` (0.60)
- `NLI_BATCH_SIZE` (8)

Per claim, in this order:

1. **No citations** → `INVALID_CITATION` (`no_citations`).
2. **Any citation integrity failure** → `INVALID_CITATION` (`citation_integrity_failed`), with the
   failure list. Failed citations are never scored.
3. **Numeric conflict on any cited chunk** → support is blocked (`numeric_mismatch`); the claim
   cannot be `SUPPORTED` even if the model returns high entailment.
4. **max contradiction ≥ threshold** → `CONTRADICTED` (`evidence_contradicts_claim`).
5. **One chunk with entailment ≥ threshold, contradiction below threshold, no numeric conflict**
   → `SUPPORTED` (`single_chunk_entails_claim`).
6. Otherwise → `INSUFFICIENT` (`neutral_or_weak_evidence`).

Chunks are never concatenated into a synthetic premise: a claim whose facts are spread over
two chunks is `INSUFFICIENT`, which is the honest result for a system that does not combine
evidence. `test_claim_spanning_two_chunks_is_not_supported` pins this.

Integrity checks (no model needed): chunk id exists, document id matches, filename matches,
page number matches, quotation present and a substring of that chunk's stored text.

### Numeric safeguard

`extract_numbers` pulls figures (handling thousands separators and decimals) from both claim
and premise; `numeric_conflict(claim, premise)` is true when the claim states a number the
premise does not contain. This is what stops "18,000" being supported by a chunk saying
"15,000" and it is independent of the model's opinion.

## 5. API surface

`POST /api/ask` keeps every Phase 3.1 field and adds:

- `claims[].verification`: `{status, reason, entailment_score, neutral_score,
  contradiction_score, integrity_failures[], evidence[]}` or `null` when verification was
  unavailable.
- `verification_status`: `verified` | `partially_verified` | `not_verified` | `contradicted` |
  `verification_unavailable`.

Aggregation: all claims supported → `verified`; any contradicted → `contradicted`; some
supported and some not → `partially_verified`; none supported → `not_verified`; `NLIError` →
`verification_unavailable` with claims left unverified (never promoted to support).

## 6. Test evidence

Full suite: **123 passed, 0 failed** (`pytest tests -q`, ~18 s), of which 35 are new
(10 NLI against the real checkpoint, 25 verifier). The 86 pre-existing tests still pass
unchanged; API tests use a deterministic verifier stub, so the model is loaded only by
`test_nli.py` and by the live checks.

Covered by unit tests: valid/invalid citations, every integrity failure mode, empty quotation,
empty citations, fabricated quotations, correct/wrong amounts, numeric conflict blocking
support despite high NLI entailment, negation, neutral evidence, contradiction, threshold
boundaries, configurable thresholds, multiple evidence items scored independently, agreement
in a single batch, whitespace normalisation, all label-map failure modes, missing-model failure.

## 7. Live verification (real server, real model, real Qwen answers)

Server: `uvicorn app.main:app` on `127.0.0.1:8000`, restarted after the phase (running as PID 27336 at
the end of verification), `/api/health` → `status: ok`. A 3-page synthetic lease (`lease_live2.pdf`, rent INR 15,000 on
the fifth, deposit INR 45,000, two months' notice, no-sublet clause) was uploaded, queried via
`POST /api/ask`, then deleted (see §9).

| Question | Answer returned | Claim verdict | ent / neu / con | Response status |
| --- | --- | --- | --- | --- |
| Monthly rent and due date | "The monthly rent is INR 15,000 and it is due on the fifth day of each calendar month." | `supported` | 0.9819 / 0.0108 / 0.0073 | `verified` |
| Security deposit and refund | "The security deposit is INR 45,000 and it is refundable within 30 days of vacating…" | `supported` | 0.9872 / 0.0087 / 0.0041 | `verified` |
| May the tenant sublet? | "…shall not sublet the premises without the Landlord's written consent…" | `supported` | 0.9838 / 0.0133 / 0.0029 | `verified` |
| Penalty for late payment (not in the lease) | "…does not contain any specific information regarding the penalty…" | no claims | — | `not_verified` |

Adversarial checks run through the real `CitationVerifier` against the real retrieved chunk:

| Case | Verdict | ent / neu / con |
| --- | --- | --- |
| "The monthly rent is INR 15,000." | `supported` | 0.9682 / 0.0140 / 0.0177 |
| "The monthly rent is INR 18,000." | `contradicted` | 0.0027 / 0.0264 / 0.9709 |
| "The rent must be paid by credit card." (lease says bank transfer) | `contradicted` | 0.0064 / 0.0259 / 0.9677 |
| Fabricated quotation / wrong page / no citations | `invalid_citation` | not scored |
| "The lease is governed by German law." | `insufficient` | 0.0011 / 0.9943 / 0.0046 |

`/api/search` returned the same schema as Phase 3.1 (`query`, `results[]`, `result_count`) and
`/api/health` stayed green throughout.

### Finding: whitespace must be normalised before scoring

PDF extraction breaks lines inside words. On the first live lease the chunk contained
`calendar m\nonth`; the claim was nearly verbatim, yet the raw premise scored
**entailment 0.0026 / neutral 0.9748**, while the same text with whitespace collapsed scored
**0.9794 / 0.0122 / 0.0083**. `_normalise()` therefore collapses whitespace on both premise and
hypothesis before NLI scoring; quotations and citations are still checked against the raw
stored text. This is covered by `test_nli_pairs_are_whitespace_normalised`. Spaces inside a
word (`m onth`) remain a genuine blind spot — see limitations.

## 8. Measured cost

On this CPU-only machine (torch 2.15.0+cpu), from this phase's measurements:

- first load of the cached checkpoint: ~1.06–1.31 s
- warm scoring: ~56.8 ms per (premise, hypothesis) pair
- batch of 8 pairs: ~0.469 s

Verification adds roughly one such batch per answered question: each claim is scored against
each of its (usually 1–2) cited chunks in a single call. No GPU is used; CUDA is unavailable here.

## 9. Data and storage

All artefacts stay on `E:`. Tests use `E:\Desktop\ProofLens\data\tmp` and delete it after a
passing run (`PROOFLENS_KEEP_TEST_DATA=1` keeps it). Live-test documents, their PDFs and the
vector/document indexes were removed after verification; `POST /api/search` now returns
`result_count: 0` and `GET /api/documents` → `count: 0`. The model cache and Ollama store were
not touched.

## 10. What this report does not claim

- **Not legal correctness.** Verdicts say whether a chunk entails a sentence; they are not
  legal conclusions, and `verified` does not mean the lease is enforceable or correctly drafted.
- **Not calibrated confidence.** The scores are raw softmax outputs from a small NLI model.
  0.98 is not "98 % likely to be true in court", and thresholds were chosen from observed
  behaviour (clear cases score 0.96–0.99), not from a calibration set. No reliability diagram,
  no per-domain calibration.
- **Not immunity to NLI errors.** A model error inside a chunk (e.g. treating "may" as "may
  not" in a badly extracted sentence) will be reported as the model sees it. The numeric guard
  only covers numbers.
- **Word fragments are not repaired.** Text where a word is split with a space (`m onth`) is not
  joined back; such chunks may score as neutral. Real documents normally break at word
  boundaries, which the whitespace normalisation handles.
- **Compound claims are weak by design.** A sentence combining facts from two chunks is
  `INSUFFICIENT` because evidence is never concatenated; the system deliberately prefers a
  false "insufficient" over a synthesised premise.
- **Not load-tested.** No concurrency or throughput testing; latency numbers above are
  single-request measurements. Only one document at a time was exercised live.
- **Overall-status aggregation is unit-tested with stubs**, not with a live multi-claim answer
  that mixes supported and contradicted claims; the live runs produced single supported claims
  and one claim-less answer.
- **Windows/CPU only.** Nothing here was exercised on Linux or with GPU acceleration.

## 11. Reproduce

```bash
cd E:\Desktop\ProofLens\backend
.\.venv\Scripts\python.exe -m pytest tests -q                 # 123 passed
.\.venv\Scripts\python.exe -m pytest tests/test_nli.py -q     # real model, 10 tests
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then `POST /api/documents/upload` a PDF and `POST /api/ask` with a question; read
`verification_status` and `claims[].verification`.
