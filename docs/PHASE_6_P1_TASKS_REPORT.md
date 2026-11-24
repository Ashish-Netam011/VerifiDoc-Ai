# Phase 6 — P1 Evaluation and Cross-Document Gaps Closed

## Scope

Three P1 items from the review were open: RAGAS evaluation, cross-document
synthesized Q&A, and retrieval benchmarking. All three are now implemented
**without adding a runtime dependency**: `backend/requirements.txt` is unchanged
and no package was installed. Every number below was produced by running the
code on this machine against the corpus in `data/`.

## What changed

| Area | File | Change |
|---|---|---|
| Retrieval ablations | `backend/app/services/retrieval_service.py` | `search()` gained `strategy` (`semantic`, `keyword`, `hybrid`, `hybrid_rerank`) and `max_per_document`. `hybrid_rerank` remains the default, so API behaviour is unchanged. |
| Cross-document coverage | `backend/app/services/retrieval_service.py`, `backend/app/services/qa_service.py`, `backend/app/config.py` | `_apply_document_cap` spreads results over documents; `QA_MAX_CHUNKS_PER_DOCUMENT` (default 2) applies it to unscoped questions. The cap is a no-op for a single-document pool, tops up rather than returning fewer results, and restores rank order. |
| Multi-document answer rule | `backend/app/services/qa_service.py` | System prompt rule 9: attribute each fact to its own document and never merge facts across documents. |
| Retrieval benchmark | `backend/app/benchmark.py` (new) | `recall@k`, `precision@k`, `MRR`, `nDCG@k` over JSONL qrels, per strategy. CLI: `python -m app.benchmark`. |
| Qrels | `backend/evaluation/retrieval_qrels.jsonl` (new) | 12 questions labeled by reading the actual chunk text in `data/pdfs/*/chunks.json`. |
| RAGAS-style metrics | `backend/app/ragas_style.py` (new), `backend/app/evaluation.py` | Faithfulness, answer relevancy (LLM question regeneration + E5 cosine), rank-aware context precision, context recall. CLI flag `--ragas-style`. |

## Retrieval benchmark — measured

12 labeled questions, 140-chunk corpus, `k ∈ {1,3,5,10}`:

| Strategy | MRR | Recall@1 | Recall@3 | Recall@5 | nDCG@10 |
|---|---|---|---|---|---|
| semantic (E5 only) | 0.850 | 0.583 | 0.833 | 0.875 | 0.826 |
| keyword (BM25 only) | 0.625 | 0.417 | 0.625 | 0.708 | 0.639 |
| hybrid (RRF, no rerank) | 0.819 | 0.542 | **0.917** | **0.917** | 0.845 |
| hybrid + rerank (production) | **0.854** | **0.583** | 0.792 | 0.875 | **0.846** |

Findings, stated plainly:

1. The cross-encoder reranker **helps precision at the top** (MRR 0.819 → 0.854,
   recall@1 0.542 → 0.583) and is the best nDCG@10.
2. The reranker **hurts recall at 3 and 5** (0.917 → 0.792 and 0.917 → 0.875).
   On this corpus it promotes a single strongly-matching chunk and pushes out
   additional labeled chunks — including both cross-document questions, where
   `ms-marco-MiniLM-L-6-v2` is biased toward the query's surface form. This is a
   real trade-off in the production path, not a benchmark artefact: it was
   measured through `RetrievalService.search` itself.
3. BM25 alone is the weakest strategy on every metric; RRF fusion over both
   retrievers beats either on recall@k, which is what the pipeline depends on
   before abstention.

Unlabelled caveat: the qrels are 12 questions labeled by one annotator for this
specific corpus. They are a regression baseline, not a general benchmark.

## RAGAS-style evaluation — measured

`python -m app.evaluation --ragas-style` on `backend/evaluation/cases.jsonl`
(7 cases, real E5/NLI models, local Qwen fallback):

| Metric | Value |
|---|---|
| Decision accuracy | 0.857 (6/7) |
| Faithfulness (runtime citation verdicts) | 0.733 |
| Answer relevancy (regenerated-question cosine) | 0.824 |
| Context precision (rank-aware) | 0.417 |
| Context recall (labeled facts entailed) | 0.000 |

Interpretation, including the bad result:

- All seven cases returned a relevancy score (0.745–0.878); none failed or was
  filled in with a placeholder.
- **Context recall 0.000 is a dataset/corpus mismatch, not a retrieval failure.**
  `cases.jsonl` was written for a lease demo corpus ("monthly rent INR 18,000",
  "First Amendment") that is no longer in `data/`. The current corpus is the
  architecture document, a Secure Case PRD, a Hindi story, a room-rent timeline
  and a roadmap. Under that mismatch, decision accuracy and recall cannot be
  read as quality claims; the retrieval benchmark above is the meaningful
  measurement for the current corpus.
- Per-case rows record `answer_relevancy_reason`, so nulls stay distinguishable
  from zeros.

These values are **RAGAS-style**, not RAGAS-produced. The definitions follow the
RAGAS suite and every report carries `RAGAS_STYLE_NOTE`; the numbers are not
comparable to published RAGAS results. Installing the `ragas` package (0.4.4,
which pulls `datasets`, `langchain*`, `openai`, `instructor`) remains possible
but was deliberately not added.

## Cross-document Q&A

- Retrieval now spreads coverage when the question is unscoped and the pool
  holds more than one document: at most `QA_MAX_CHUNKS_PER_DOCUMENT` chunks per
  document, with the remainder topped up in rank order.
- Single-document pools and document-scoped questions are unchanged.
- Answer-level attribution is enforced by prompt rule 9; claims are still mapped
  to backend-owned sources, so a cross-document claim cannot cite a document
  that was not supplied.
- Verified by tests, not by a live model run: `test_multi_doc.py` drives
  `QAService` with a stub model and asserts the prompt contains evidence from
  both documents and that claims resolve to two distinct `document_id`s.

## Verification

| Check | Command | Result |
|---|---|---|
| Full backend suite | `python -m pytest tests/ -q` | **313 passed**, 0 failed, 0 skipped (66 s) |
| Retrieval benchmark | `python -m app.benchmark` | exit 0; table above |
| RAGAS-style evaluation | `python -m app.evaluation --ragas-style` | exit 0; table above |

The first evaluation attempt exited 1 with `LLMUnavailableError: Ollama service
returned HTTP 500`; an immediate retry completed. The local Qwen model is
intermittently unstable on longer prompts — a pre-existing runtime condition,
not a code path added here.

## Remaining limitations

1. Qrels are small and single-annotator; extend them before quoting the table in
   any external context.
2. `cases.jsonl` still targets the old lease corpus. Until it is rebuilt for the
   current corpus, `context_recall_nli` reads 0.000 and decision accuracy is
   uninformative.
3. The reranker's recall loss at k=3/5 is unresolved. A per-document quota on the
   production path would partly offset it, but that changes ranking behaviour and
   needs its own measurement before being enabled.
4. RAGAS-style values are not comparable to published RAGAS scores.
5. No live `/api/ask` run was performed for cross-document answers; the model
   returned HTTP 500 once, and the behaviour is covered by tests instead.
