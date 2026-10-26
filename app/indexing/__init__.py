"""Embedding and vector-index stage of the ingestion pipeline.

This package turns the canonical chunk dataset built by
:mod:`app.ingestion.canonical` into a FAISS index whose vectors stay tied to
chunk metadata by an explicit, stable ID. It sits between ingestion (extraction
and chunking) and the retrieval interface in :mod:`app.retrieval`.

Scope boundaries:

* No Gemini, no answer generation, no Flask routes, and no OCR live here.
* Nothing here reaches the network. The embedding model is loaded from the
  local Hugging Face cache with hub access switched off, so a missing model is
  reported rather than downloaded.
* The SQLite metadata store is not touched. The index carries its own metadata
  sidecar, which is what this stage actually needs.
"""
