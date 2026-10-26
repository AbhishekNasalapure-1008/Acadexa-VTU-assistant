# Retrieval Evaluation Report

Deterministic evaluation of the dense retriever over the five-document corpus. Every number below is computed from the artifacts named in this section; nothing is estimated, and no score threshold is applied anywhere.

## 1. Run context

| Input | Value |
| --- | --- |
| Index metric | `inner_product` |
| Indexed vectors | 655 |
| Canonical chunks | 655 |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2` |
| Evaluation questions | 58 (52 answerable, 6 unanswerable) |
| Cut-offs (k) | 1, 3, 5, 10 |
| Questions file | `questions.jsonl` sha256 `9555281418f20222` |
| Canonical chunks sha256 | `ce8fbf1dbc887245` |
| Index entries sha256 | `f6f443fbb7333f5d` |

Every question asks with `top_k = 10`; a question with a metadata
filter has the filter applied before ranking.

## 2. Methodology

With `retrieved` the ranked result list and `relevant` the judged-relevant set:

- Recall@k = |relevant ∩ retrieved[:k]| / |relevant|
- Precision@k = |relevant ∩ retrieved[:k]| / k
- Hit@k = 1 when any relevant chunk is in `retrieved[:k]`, else 0
- MRR@k = 1 / rank of the first relevant chunk in `retrieved[:k]`, else 0

Relevance comes only from the labels in the questions file. No similarity score is ever treated as evidence of relevance (`REQUIREMENTS.md` AC-04), and no threshold is applied. A question with no relevant chunk is reported through its scores, not through recall, so the metric definitions stay exact.

Per category: `syllabus_fact`, `module`, `scheme`, `semester`, `document_type`, `regulation`, `exact_term`, `semantic`, `insufficient_evidence`

## 3. Overall metrics (answerable questions)

| Metric | @1 | @3 | @5 | @10 |
| --- | --- | --- | --- | --- |
| recall | 0.429 | 0.631 | 0.667 | 0.721 |
| precision | 0.462 | 0.224 | 0.146 | 0.081 |
| hit | 0.462 | 0.673 | 0.712 | 0.750 |
| mrr | 0.462 | 0.551 | 0.561 | 0.566 |

## 4. Metrics by category

| Category | Questions | Answerable | Recall@1 | Recall@10 | Precision@1 | MRR@10 |
| --- | --- | --- | --- | --- | --- | --- |
| syllabus_fact | 8 | 8 | 0.250 | 0.500 | 0.250 | 0.344 |
| module | 10 | 10 | 0.400 | 0.600 | 0.400 | 0.450 |
| scheme | 5 | 5 | 0.600 | 1.000 | 0.600 | 0.687 |
| semester | 5 | 5 | 1.000 | 1.000 | 1.000 | 1.000 |
| document_type | 5 | 5 | 0.600 | 0.800 | 0.600 | 0.667 |
| regulation | 7 | 7 | 0.071 | 0.714 | 0.143 | 0.440 |
| exact_term | 6 | 6 | 0.750 | 0.917 | 0.833 | 0.917 |
| semantic | 6 | 6 | 0.056 | 0.500 | 0.167 | 0.306 |
| insufficient_evidence | 6 | 0 | n/a | n/a | n/a | n/a |

## 5. Filter correctness

39 question(s) apply a metadata filter (`document_type`, `scheme`, `semester`, and/or `document_ids`). Every returned chunk was checked against the filter that was applied.

Result: **0 violations** - every returned chunk satisfies the filter applied to its question.

## 6. Provenance correctness

Every returned chunk was checked for a complete citation chain: non-empty `chunk_id`/`document_id`/`version_id`/`filename`/`document_type`, at least one one-based page number, a `page_start`/`page_end` range that agrees with those pages, a `chunk_id` namespaced under its own `document_id`, and membership of the canonical dataset.

Result: **0 problems** - every returned chunk carried an accurate, traceable citation.

## 7. Representative successes

24 of 52 answerable question(s) put a relevant chunk at rank 1.

| Question | Category | Top-1 chunk | Score | Pages |
| --- | --- | --- | --- | --- |
| q-syl-02 | syllabus_fact | `abc23c2c1b9b3f06` | 0.5364 | 1 |
| q-syl-03 | syllabus_fact | `fe77f45ea1f03ddf` | 0.7124 | 13 |
| q-mod-01 | module | `94fc5f1ae2fab126` | 0.6640 | 2 |
| q-mod-04 | module | `bf1a7e22d550da42` | 0.6056 | 19 |
| q-mod-08 | module | `5251bed5289a837f` | 0.4948 | 23 |
| q-mod-09 | module | `253896ca6433252f` | 0.6502 | 6 |
| q-sch-02 | scheme | `9dc6f4cff021fdcc` | 0.5127 | 8 |
| q-sch-03 | scheme | `0a12a5ebf947927c` | 0.6507 | 18 |
| q-sch-05 | scheme | `4f237c9006466594` | 0.6987 | 23 |
| q-smt-01 | semester | `312426b86ed01080` | 0.6334 | 65 |
| q-smt-02 | semester | `681f9a6ca824f9e6` | 0.7581 | 41 |
| q-smt-03 | semester | `de9f842d8e1fdb13` | 0.6281 | 47 |

## 8. Failures and near-misses

- Relevant chunk absent from the top 10: **13** question(s).
- Relevant chunk present but not at rank 1: **15** question(s).

| Question | Category | Expected chunk | Best returned | Score |
| --- | --- | --- | --- | --- |
| q-syl-01 | syllabus_fact | `4d509f22570f7554` | `5adfc6d2aa5c5ef8` | 0.6156 |
| q-syl-05 | syllabus_fact | `c836a3a1ceee90fe` | `bd3bf7cdd6407486` | 0.4335 |
| q-syl-06 | syllabus_fact | `28238d5d36aa29fd` | `f6130784d3cfc4b2` | 0.5015 |
| q-syl-07 | syllabus_fact | `aae3c7454790e227` | `bd3bf7cdd6407486` | 0.5122 |
| q-mod-05 | module | `39d88776c3c8f8dc` | `9e027da88b3598ec` | 0.6359 |
| q-mod-06 | module | `94e18cf7bd364773` | `eda5a5c3a238a75d` | 0.5824 |
| q-mod-07 | module | `0f8049d2df5717d2` | `600e07975cff7f82` | 0.6422 |
| q-mod-10 | module | `f3d297e4ec653221` | `25d80f12ddb22f58` | 0.5825 |
| q-dty-03 | document_type | `c7b6a01cb5cb6120` | `0a12a5ebf947927c` | 0.5377 |
| q-reg-06 | regulation | `8323e40b8bf8400e` | `9213f8a6a6869f01` | 0.6649 |
| q-sem-01 | semantic | `fa394c7907e575d2` | `95bcf7021526d985` | 0.4813 |
| q-sem-03 | semantic | `489a81a4e6eca7b8` | `e46c29f71b4fde67` | 0.6788 |
| q-sem-05 | semantic | `8323e40b8bf8400e` | `ac920271f03957b6` | 0.6397 |

| Question | Category | First relevant rank | Expected chunk |
| --- | --- | --- | --- |
| q-syl-08 | syllabus_fact | 2 | `4f237c9006466594` |
| q-reg-04 | regulation | 2 | `fa394c7907e575d2` |
| q-reg-05 | regulation | 2 | `8323e40b8bf8400e` |
| q-reg-07 | regulation | 2 | `25a3c40d31f89f7a` |
| q-ext-04 | exact_term | 2 | `fa394c7907e575d2` |
| q-sem-02 | semantic | 2 | `5d5687d59526c62f` |
| q-mod-02 | module | 3 | `8668bb0fb294ee19` |
| q-sch-01 | scheme | 3 | `0a12a5ebf947927c` |
| q-dty-05 | document_type | 3 | `b42d473d057c4a26` |
| q-reg-03 | regulation | 3 | `489a81a4e6eca7b8` |
| q-sem-04 | semantic | 3 | `b42d473d057c4a26`, `1f9122c48a299e21` |
| q-syl-04 | syllabus_fact | 4 | `2dfeb58b3763e37e` |
| q-reg-01 | regulation | 4 | `6f1bb00d6e08d032`, `f3e9aaa6a3a58d3a` |
| q-mod-03 | module | 6 | `702a8419aa80eccc` |
| q-sch-04 | scheme | 10 | `5cf78627f79680da` |

## 9. Unanswerable-query findings

These questions have no relevant chunk in the corpus. No refusal logic exists yet, so the retriever still returns `top_k` chunks; what is reported here is how confident those returns are, which is the evidence any future threshold decision needs.

| Question | Top-1 score | Mean of top 10 scores |
| --- | --- | --- |
| q-uns-01 | 0.4404 | 0.4137 |
| q-uns-02 | 0.5132 | 0.4996 |
| q-uns-03 | 0.3731 | 0.3566 |
| q-uns-04 | 0.4953 | 0.4729 |
| q-uns-05 | 0.4241 | 0.3660 |
| q-uns-06 | 0.4217 | 0.3818 |

For comparison, the 24 answerable question(s) whose rank-1 result was relevant scored between 0.4353 and 0.7645 at rank 1.
The 6 unanswerable question(s) scored between 0.3731 and 0.5132 at rank 1.

## 10. Recommended quality thresholds

`REQUIREMENTS.md` Q7 leaves the retrieval range and any similarity threshold undecided, so nothing below is approved; it is a proposal derived from the measured numbers.

- The unanswerable rank-1 scores (up to 0.5132) overlap the correct answerable rank-1 scores (from 0.4353 down), so **no single score threshold separates them on this dataset**. A score cut-off alone cannot be recommended; any threshold would trade missing real answers against returning unsupported ones.
- Recommend a reported operating range of k = 5 to 10 citations per answer: retrieval is measured to be strongest at rank 1 and degrades with depth, and a person reads a short citation list.
- Recommend gating any answer on the retriever returning at least one chunk and on a future explicitly approved threshold; until then an unanswerable query must be handled by generation-time abstention, which is out of scope for this task.

## 11. Limitations

1. **Small, single-annotator dataset.** The 58 questions and their labels were derived
   from the corpus by the builder's selectors, not by independent human raters, so
   inter-annotator agreement has not been measured.
2. **Chunk-level relevance only.** A label names the chunk(s) that state the answer, not
   a span inside them; a chunk that merely repeats the answer counts as relevant.
3. **Corpus scope.** Only the five validated documents are covered. The 2022 and 2025
   regulations have no scheme or semester, so scheme/semester filters cannot be tested
   against them.
4. **Single embedding model.** Results describe `sentence-transformers/all-MiniLM-L6-v2` only.
5. **No reranking or query rewriting**, so the numbers are the plain dense-retrieval
   baseline.
6. **Unanswerable questions are a judgement**, not a guarantee: they were checked to have
   no lexical match, but a chunk could still be argued to be partially related.

---

Generated by `python -m app.evaluation.evaluate`. The report is reproducible: the same index, canonical dataset and questions file produce this file byte for byte.
