"""Offline retrieval-quality evaluation for the VTU Assistant.

This package measures how well the dense retriever in :mod:`app.retrieval`
finds the chunks that actually answer a question. It is a read-only measurement
layer: it queries the existing FAISS index with the existing embedding model,
compares the returned chunk IDs against a set of grounded relevance judgements,
and writes a report.

What lives here:

* :mod:`app.evaluation.metrics` - the metric arithmetic (recall@k, precision@k,
  reciprocal rank@k, hit@k), stated as explicit formulas.
* :mod:`app.evaluation.dataset` - the evaluation-question schema, its loader and
  its validator. Relevance labels live here, never in the production index.
* :mod:`app.evaluation.build_dataset` - a deterministic builder that derives the
  relevance labels from the canonical chunk dataset, so a label is a chunk that
  really exists rather than a chunk ID typed by hand.
* :mod:`app.evaluation.evaluate` - the runner: it queries the retriever, computes
  the metrics, checks returned provenance, and writes the markdown report.

Scope boundaries: no answer generation, no Gemini, no refusal logic, no Flask,
no frontend. The evaluation never mutates the index or the canonical dataset; it
only reads them. Nothing here reaches the network.
"""
