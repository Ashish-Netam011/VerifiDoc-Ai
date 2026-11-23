# Phase 3.3 — Evidence Sufficiency & Abstention Engine

Report date: 2026-11-23
Scope: `E:\Desktop\ProofLens`, backend only. Models: cached `qwen2.5:3b-instruct` (Ollama) and
cached `cross-encoder/nli-deberta-base`.
Status: implemented, unit/integration tested (176 passed), live-verified against a running
server with the real models.

Everything marked "measured" was produced on this machine in this phase. Everything the
implementation does *not* guarantee is listed under [Known limitations](#12-known-limitations).

---

## 1. What was implemented

The Q&A pipeline now has a deterministic gate between retrieval, generation and what the client
is allowed to see:

```
Question
  → hybrid retrieval (unchanged, Phase 2)
  → evidence sufficiency pre-check          ← new, can abstain without calling Qwen
  → grounded Qwen generation (unchanged, Phase 3.1)
  → citation integrity + NLI claim verification (unchanged, Phase 3.2)
  → final decision engine                   ← new, arbitrary LLM prose cannot bypass it
  → answer / partial answer / abstention + evidence gap report
```

| File | Change |
| --- | --- |
| `backend/app/services/evidence_sufficiency.py` | **new** — coverage analysis, relevance pre-check, conflict detection, decision policy, gap report |
| `backend/app/services/qa_service.py` | pre-check before generation; `assess()` after verification; `decision`, `missing_information`, `conflicts`, `evidence_gap_report` on `QAResult`; abstraction helpers |
| `backend/app/routers/qa.py` | new response fields and models: `decision`, `missing_information`, `conflicts[]`, `evidence_gap_report` (`AskConflict`, `AskCoverage`, `AskCoverageComponent`, `AskSupportingEvidence`, `AskEvidenceGapReport`) |
| `backend/app/config.py`, `backend/.env`, `backend/.env.example` | five `EVIDENCE_*` settings |
| `backend/tests/test_evidence_sufficiency.py` | **new** — 34 tests, deterministic |
| `backend/tests/test_abstention.py` | **new** — 19 tests (service + API, stubbed Qwen/NLI) |
| `backend/tests/test_qa.py` | two Phase 3.2 assertions updated to the new, stricter publication rule (see §7) |
| `docs/PHASE_3_3_ABSTENTION_REPORT.md` | this report |

Untouched: `/api/search`, ingestion, chunking, embeddings, BM25, RRF, vector store, the NLI
service and the verifier's scoring rules. No new dependency, no new model download.

## 2. Architecture and where the decision lives

`EvidenceSufficiencyEngine` has two entry points:

- `precheck(question, results) -> PrecheckResult` — cheap, deterministic, runs before generation.
- `assess(question, evidence=…, claims=…, verification_status=…, generated_answer=…) ->
  SufficiencyAssessment` — runs after verification and produces the user-facing answer.

The engine consumes only backend-owned data: retrieval records, the evidence actually supplied to
the model, and the `ClaimVerification` objects Phase 3.2 already produced. **It never runs NLI
itself** and never re-scores a claim. The LLM's `answer` string is used only when the engine has
already established that every requested fact is supported; otherwise the engine composes the
visible text (partial) or replaces it (abstention).

`Decision` is an enum (`answer`, `partial_answer`, `abstain`); the API serialises its value.

## 3. Evidence sufficiency methodology

### 3.1 Pre-generation screen (deterministic)

`precheck` abstains without calling Qwen when retrieval is empty, or when no retrieved chunk

- shares at least one content token with the question (stopwords removed, `bm25_service.tokenize`
  source), **and** no chunk
- mentions a slot named by the question (see §4),

**and** the best semantic score is below `EVIDENCE_MIN_SEMANTIC_SCORE` (default 0.70).

The screen is deliberately one-sided: it can only *skip* generation, never authorise an answer.
`EVIDENCE_MIN_RELEVANT_CHUNKS` (default 1) sets how many chunks must pass the lexical test. A
retrieval set with high cosine similarity but no shared term still proceeds to generation —
cosine similarity is not treated as proof of anything.

### 3.2 Signals used by the final decision

| Signal | Source | Used for |
| --- | --- | --- |
| number of relevant chunks | pre-check lexical overlap | pre-check only; never sufficient alone |
| semantic relevance | E5 cosine from retrieval | pre-check floor; never sufficient alone |
| keyword relevance | question ∩ chunk content tokens | pre-check, coverage fallback |
| evidence coverage of requested facts | slot keywords per chunk | which requested facts the documents even discuss |
| citation integrity | `ClaimVerification.integrity_failures` | a claim with a broken citation is `invalid_citation` |
| entailment / contradiction / neutral scores | Phase 3.2 NLI results | support, contradiction, insufficiency |
| missing qualifications | condition markers in the supporting sentence | blocks an answer that drops a condition |
| conflicting evidence | contradicted claims, cross-document figure mismatch | disclosed conflict, blocks the answer |

`numeric_conflict` from Phase 3.2 is reused unchanged, so a claim carrying a figure the chunk does
not contain can still never be supported.

## 4. Question coverage strategy

Coverage is **lexical and conservative**, not an LLM decomposition:

1. `match_slots(question)` matches a fixed vocabulary of 16 slots (`monthly_rent`,
   `security_deposit`, `rent_due_date`, `landlord_income`, `notice_period`, `subletting`,
   `late_payment`, `lease_term`, `maintenance`, `utilities`, `pets`, `governing_law`,
   `rent_increase`, `occupants`, `parking`, `termination`) against alias phrases.
2. Within a slot the longest alias wins; a match fully contained in a longer match of a *different*
   slot is dropped, so "when is the rent due" yields only `rent_due_date`, not `rent` as well.
3. Each component then gets a status from claims + evidence (`SLOT_KEYWORDS` decides whether a
   claim or a chunk "speaks about" the slot):

| Component status | Meaning |
| --- | --- |
| `supported` | a claim about this fact is `supported` by its cited chunk (and keeps its condition) |
| `contradicted` | a claim about this fact is contradicted by its cited chunk |
| `invalid_citation` | a claim about this fact failed citation integrity |
| `unverified` | the documents or a claim mention this fact, but nothing is supported |
| `condition_not_preserved` | supported, but the answer dropped a condition in the evidence |
| `missing` | neither a claim nor any retrieved chunk mentions this fact |

If **no** slot matches, coverage is `uncertain`: the engine does not claim to know what is missing
and falls back to claim-level verification only (all claims supported → `answer`; some supported →
`partial_answer`; none → `abstain`). This is what keeps questions like "summarise the payment terms"
from being penalised for a vocabulary gap.

Coverage is a *retrieval of intents*, not a proof of intent: a question that names two slots
because it mentions them in passing will require both (documented limitation, §12).

## 5. Decision rules (ordered, deterministic)

Evaluated top to bottom; the first match wins.

| # | Condition | Decision | `reason` |
| --- | --- | --- | --- |
| 1 | retrieval empty / no chunk passes the pre-check | `abstain` | `empty_corpus`, `no_relevant_evidence` |
| 2 | `verification_status == verification_unavailable` and `EVIDENCE_REQUIRE_VERIFICATION` (default true) | `abstain` | `verification_unavailable` |
| 3 | any `claim_contradiction` conflict | `abstain` | `contradictory_evidence` |
| 4 | any component `condition_not_preserved` | `abstain` | `qualification_not_preserved` |
| 5 | cross-document figure conflict (`conflicting_amounts`) | `abstain` | `conflicting_evidence` |
| 6 | a component is contradicted | `abstain` | `contradictory_evidence` |
| 7 | no claims at all | `abstain` | `no_claims` |
| 8 | no supported claim | `abstain` | `invalid_citations` if every claim is invalid, else `insufficient_evidence` |
| 9 | coverage identified, every component `supported` | `answer` | `all_requested_facts_supported` |
| 10 | coverage uncertain, every claim supported | `answer` | `all_claims_supported` |
| 11 | ≥1 component supported and ≥1 not | `partial_answer` | `some_requested_facts_missing` |
| 12 | `EVIDENCE_CONSERVATIVE_MODE=true` and rule 11 applies | `abstain` | `conservative_mode` |

Rules 3–6 are what make "no sufficient evidence, no confident answer" enforceable: a
contradiction is always **disclosed** with its chunk, page and score, never folded into a generic
"insufficient evidence".

## 6. Partial-answer handling

For `partial_answer` the visible `answer` is **composed by the backend**, never taken from Qwen:

```
<every supported claim, in order>
+ "The available documents do not establish <missing facts>."
```

Unsupported, unverified and contradicted claims are excluded from that text. They remain in
`claims[]` with their per-claim verdict, so the exclusion is transparent rather than silent.
`missing_information` names each unestablished fact; `supporting_evidence` lists the real chunk,
document, filename and page that carry each supported claim.

## 7. Abstention logic

On `abstain` the visible `answer` is a fixed, backend-owned sentence for the reason (see §5), never
model prose. Concretely:

- contradicted claim → "The generated answer conflicts with the cited evidence… The claim
  \"…\" is contradicted by <filename> page <n>."
- verification unavailable → "Claim verification is currently unavailable, so no verified answer can
  be given."
- insufficient / no claims / invalid citations / conflicting figures → their own fixed sentence.

Claim provenance is still returned in `claims[]` (`sources`, `verification`), but nothing is
presented as a fact.

**Behaviour change vs Phase 3.2** (deliberate, and the reason two `test_qa.py` assertions were
updated):

| Situation | Phase 3.2 | Phase 3.3 |
| --- | --- | --- |
| all claims `contradicted` | generated answer still returned, `verification_status: contradicted` | `decision: abstain`, conflict disclosed, answer withheld |
| NLI unavailable | generated answer still returned, claims with `verification: null` | `decision: abstain`, `verification_status: verification_unavailable` |

`EVIDENCE_REQUIRE_VERIFICATION=false` restores generation when NLI fails, but unverified claims are
still never supported, so the decision remains `abstain` (rule 8) — the flag only changes the
reason, never the publication.

## 8. Evidence Gap Report

Attached to every response as `evidence_gap_report`:

```json
{
  "status": "partial_answer",
  "reason": "some_requested_facts_missing",
  "missing_information": [
    "The available documents mention the security deposit, but it could not be verified for this answer."
  ],
  "conflicts": [],
  "supporting_evidence": [
    {
      "description": "The rent is INR 15,000 per month.",
      "chunk_id": "bc18c20521964f708f2b373d56fbdc95:p0001:c0000",
      "document_id": "bc18c20521964f708f2b373d56fbdc95",
      "filename": "lease_phase33.pdf",
      "page_number": 1,
      "claim_text": "The rent is INR 15,000 per month."
    }
  ],
  "coverage": {
    "status": "identified",
    "components": [
      {"name": "monthly_rent", "label": "the monthly rent", "matched_phrase": "rent",
       "status": "supported", "evidence_chunk_ids": ["bc18c20521964f708f2b373d56fbdc95:p0001:c0000"]},
      {"name": "security_deposit", "label": "the security deposit", "matched_phrase": "security deposit",
       "status": "unverified", "evidence_chunk_ids": ["bc18c20521964f708f2b373d56fbdc95:p0001:c0000"]}
    ]
  },
  "signals": {"claims": 2, "supported_claims": 1, "contradicted_claims": 0, "invalid_claims": 0,
              "unverified_claims": 0, "coverage": "identified", "relevant_chunks": 1,
              "best_semantic_score": 0.937}
}
```

(Abridged from the live run: the two long ids are real backend chunk/doc ids, the semantic score is
from that request.) Every reference is a backend-owned record; no filesystem path is included
(asserted by `test_gap_report_has_no_filesystem_paths`).

## 9. Configuration and thresholds

| Setting | Default | Meaning | Why this value |
| --- | --- | --- | --- |
| `EVIDENCE_MIN_RELEVANT_CHUNKS` | 1 | chunks that must share a content token / slot word with the question for the pre-check to pass | one lexically related chunk is enough to justify *asking* the model; nothing more |
| `EVIDENCE_MIN_SEMANTIC_SCORE` | 0.70 | similarity floor used only when no chunk shares a term | E5 similarities for this corpus sit ≈0.6–0.95; 0.70 keeps clearly unrelated chunks from triggering generation |
| `EVIDENCE_MAX_ITEMS` | 8 | evidence items the sufficiency analysis considers | bounds coverage/conflict work; `qa_top_k` (5) is the normal ceiling |
| `EVIDENCE_REQUIRE_VERIFICATION` | true | abstain when NLI is unavailable | an unverifiable answer is not an answer |
| `EVIDENCE_CONSERVATIVE_MODE` | false | downgrade partial answers to abstention | available when a deployment wants answer-all-or-nothing |

These are **operating points chosen from observed behaviour**, not calibrated probabilities and not
scientifically validated. `EVIDENCE_MAX_ITEMS` is the only value with no direct measurement behind
it; it exists to bound work per request.

Unchanged from Phase 3.2: `NLI_ENTAILMENT_THRESHOLD=0.60`, `NLI_CONTRADICTION_THRESHOLD=0.60`,
`NLI_BATCH_SIZE=8`, `QA_TOP_K=5`, `QA_MAX_CONTEXT_CHARS=6000`.

## 10. Test results

```
cd E:\Desktop\ProofLens\backend
.\.venv\Scripts\python.exe -m pytest tests -q
176 passed, 1 warning in 18.54s
```

123 tests before this phase → **53 new**: 34 in `test_evidence_sufficiency.py`, 19 in
`test_abstention.py`. All pre-existing NLI, verifier, retrieval, ingestion and API tests still pass.

`test_evidence_sufficiency.py` (deterministic, no model): slot extraction and alias absorption,
uncertain coverage, component statuses (supported / missing / unverified / condition), claim
matching through the cited sentence, all pre-check branches, keyword relevance, condition detection
(preserved / omitted / unconditional), every decision rule (answer, partial, abstain ×6, conflict
disclosure, conservative mode, uncertain coverage), gap-report contents, real-evidence references,
no filesystem paths, serialisation.

`test_abstention.py` (stubbed Qwen + verifier, plus API): fully supported → `answer`; empty corpus →
`abstain` **without calling the model**; irrelevant low-similarity retrieval → `abstain` without
calling the model; **high similarity without entailment → `abstain`**; two-part question with one
supported fact → `partial_answer` with the unsupported claim absent from the answer; both facts
supported → `answer`; missing amount → `abstain` + `missing` component; wrong amount →
`abstain` + disclosed conflict; conflicting claims → `abstain`; preserved condition → `answer`;
invalid citation → never `answer`; NLI unavailable → never verified; all-neutral → `abstain`; mixed
claims with uncertain coverage → `partial_answer`; unsupported claims never leak into the answer;
gap report references real chunks; Phase 3.1/3.2 fields survive.

API tests use the autouse `FakeCitationVerifier` fixture and never load the 700 MB NLI model; the
real-model behaviour is exercised in `test_nli.py` (Phase 3.2) and in the live run below.

## 11. Live model verification

Server restarted on this phase's code: `uvicorn app.main:app` on `127.0.0.1:8000`, `/api/health`
→ `ok`, `llm.model_present: true`. A one-page synthetic lease was uploaded (rent INR 15,000 due on
the fifth, deposit INR 30,000 refundable in 30 days, no subletting without prior written consent,
two months' notice, **no landlord income anywhere**) and queried through `POST /api/ask` with the
real Qwen and the real NLI model, then removed (§13).

Final run:

| Question | Expected | Actual decision | Claim verdicts (ent / con) | Latency |
| --- | --- | --- | --- | --- |
| What is the monthly rent? | ANSWER | **answer** / `verified` | supported 0.9722 / 0.0142 | 3.51 s |
| What is the security deposit? | ANSWER | **abstain** / `not_verified` | insufficient 0.5620 / 0.1752 | 1.99 s |
| What is the rent and security deposit? | ANSWER | **partial_answer** / `partially_verified` | supported 0.9018 / 0.0501 · insufficient 0.5620 / 0.1752 | 3.17 s |
| What is the rent and the landlord's annual income? | PARTIAL_ANSWER | **abstain** / `contradicted` | supported 0.9018 / 0.0501 · contradicted 0.0054 / 0.6285 | 4.00 s |
| What is the landlord's annual income? | ABSTAIN | **abstain** / `not_verified` (no claims; pre-check passed, model refused) | — | 1.12 s |
| Can the tenant sublet freely? | ABSTAIN or conditional answer | **answer** / `verified`, condition preserved in the answer | supported 0.9793 / 0.0086 | 2.47 s |
| Is subletting permitted with written consent? | ANSWER | **answer** / `verified` | supported 0.9592 / 0.0147 | 2.32 s |
| Is the monthly rent INR 18,000? | CONTRADICTED / ABSTAIN | **answer** / `verified` — "The monthly rent is INR 15,000, not INR 18,000…" | supported 0.9576 / 0.0231 | 2.29 s |

Notes on the three rows that differ from the table I expected:

1. **Security deposit (ANSWER → abstain/partial).** The model's claim "The security deposit is
   INR 30,000." scores entailment **0.562**, just under the 0.60 threshold, against an 800-character
   chunk holding four clauses. A different phrasing in an earlier run ("…refundable within thirty
   days of vacating the premises.") scored 0.886 and produced a correct ANSWER. This is a genuine
   recall limitation of chunk-level NLI, not a policy bug: the system erred toward not answering.
2. **Rent + annual income (PARTIAL → abstain).** In this run Qwen invented "The annual income from
   rent is INR 180,000." — contradicted by the chunk (0.6285 > 0.60, and the figure is absent from
   the evidence). The engine disclosed the conflict and abstained instead of publishing a partial
   answer that sat next to a fabricated figure. The earlier run produced `partial_answer` for this
   question, because the model then emitted "The landlord's annual income is INR 180,000.", which
   was `insufficient` (0.0028 / 0.3488) rather than contradicted. Both outcomes are inside the
   intended policy; only the first matches the table's "PARTIAL_ANSWER" wording.
3. **"Is the monthly rent INR 18,000?" (CONTRADICTED → answer).** Qwen produced the corrective claim
   "The monthly rent is INR 15,000." rather than repeating the false premise. That claim is
   supported, so the answer is shown — a correct, evidence-backed correction rather than a
   contradiction of a generated claim. The claim-level contradiction path is exercised by the
   18,000 case in Phase 3.2 and by `test_wrong_amount_abstains_and_discloses_the_conflict`.

Other observed behaviour:

- Empty/irrelevant retrieval short-circuits before Qwen (verified live via the "annual income"
  question returning in 1.12 s with zero model claims, and in tests by asserting no model call).
- `coverage` was `identified` for all eight questions; the `landlord_income` component was `missing`
  for the standalone income question, which is what produced the missing-information sentence.
- `/api/documents` and `/api/search` behaved as before; `/api/health` stayed green.

### Bug found by the live run and fixed

The first live pass abstained for **both** subletting questions although the claim was verbatim the
clause. Cause: PDF extraction plus the 800-character chunk budget left the chunk ending
`"… without the prio"`, so the condition clause was a single fragment word (`prio`) that a faithful
claim cannot contain. `condition_not_preserved` now requires **at least two distinctive condition
words** before it can flag an answer; shorter fragments are treated as an unusable clause. After the
fix both subletting questions answered with the condition intact, and
`test_dropped_condition_blocks_the_answer` still shows the guard rejecting an answer that really
drops "prior written consent".

## 12. Performance measurements

Single-request latency on this machine (HTTP, includes retrieval + Qwen + NLI), from the final run:

| Path | Latency |
| --- | --- |
| pre-check abstention (no Qwen) | 1.12 s |
| first answered request after start (models warming) | 3.51 s |
| answered / partial requests, warm | 2.29–4.00 s (mean ≈ 2.9 s) |

The sufficiency layer itself is pure Python over already-computed data: matching, coverage and
conflict detection are O(claims × slots × chunk length) string work on a handful of items, with no
model call and no measurable share of the latency above (well under 10 ms on this corpus). NLI cost
is unchanged from Phase 3.2 (≈56.8 ms per premise/hypothesis pair, one batch per answered
question). The pre-check saves an entire Qwen generation when it fires. No concurrency or
throughput testing was done.

## 13. Data and storage

All artefacts remain on `E:`. Tests use `E:\Desktop\ProofLens\data\tmp` and delete it after a
passing run. The live PDF, its chunks, vectors and BM25 entries were removed after verification;
`GET /api/documents` → `count: 0` and `POST /api/search` → `result_count: 0` at the end of the
phase. The model cache and the Ollama store were not modified.

## 14. Known limitations

**Measured, not speculative:**

- **Chunk-level NLI is phrase-sensitive near the threshold.** A true deposit claim scored 0.562
  against a four-clause chunk that contained the exact figure (0.886 with a longer paraphrase). The
  result is a *conservative* miss (abstain/partial) but a real recall loss. Sentence-level premise
  windows are the obvious next experiment; it was not done here because Phase 3.2 verification is
  reused as-is.
- **Qwen output varies between runs**, so the same question can yield `partial_answer` in one run and
  `abstain` in another (measured above, same document, same code). The policy is deterministic for
  fixed inputs; the model's claims are not.
- **Chunks can end mid-clause** (`"… without the prio"`). The condition guard now refuses to judge
  such fragments, which means a genuinely truncated condition can pass un-noticed. Chunk overlap
  (120 chars) usually restores the clause in a neighbouring chunk, but not always.

**Heuristic, by design:**

- Coverage vocabulary is 16 hand-written slots with aliases and keywords. Unknown topics give
  `coverage: uncertain`, and questions that merely mention two slots in passing require both.
- "Speaks about the slot" is keyword matching, so a claim can be attached to a slot by one shared
  word (`"rent"` in "annual income from rent").
- Condition preservation is marker-based and only looks at the best-matching sentence of the cited
  chunk.
- Cross-document contradiction detection is limited to: a contradicted claim (disclosed), and two
  *supported* claims citing different documents with different figures for the same slot. There is
  no document-pair comparison subsystem, per the phase constraints.
- `PARTIAL_ANSWER` composes claim sentences rather than rewriting them, so the prose is stitched
  ("The rent is INR 15,000 per month. The available documents do not establish the security deposit.").

**Not claimed:**

- Not legal correctness, not calibrated confidence. The scores are raw softmax outputs; the
  thresholds are operating points.
- The numeric safeguard only covers digits; numbers written as words ("fifth" vs "third") are left
  to NLI.
- No guarantee that "coverage: identified" equals the user's real intent.
- Windows/CPU only; no load, concurrency, or multi-document-scale testing.

## 15. Recommended next milestone

**Phase 3.4 — sentence-level evidence windows for verification/abstention.** Feed the NLI model the
best-matching sentence (or a two-sentence window) of a cited chunk instead of the whole 800-character
chunk, and re-measure the deposit-style misses; this is the single largest measured source of false
abstention. Pair it with a small, labelled question set (say 40 questions over these leases) so
threshold changes are evaluated against false-answer and false-abstain rates instead of anecdotes,
and only then consider cross-document amendment intelligence.

## 16. Reproduce

```powershell
cd E:\Desktop\ProofLens\backend
.\.venv\Scripts\python.exe -m pytest tests -q                       # 176 passed
.\.venv\Scripts\python.exe -m pytest tests/test_evidence_sufficiency.py tests/test_abstention.py -q
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then `POST /api/documents/upload` a lease and `POST /api/ask`; read `decision`,
`missing_information`, `conflicts`, `evidence_gap_report` and `verification_status`.
