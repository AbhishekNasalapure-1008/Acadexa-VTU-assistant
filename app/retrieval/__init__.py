"""Dense retrieval over the FAISS index.

This package is the read side of the vector index: it embeds a query with the
same configuration the index was built with and returns the top-k chunks with
their metadata and scores. It is a validation interface, not a chat endpoint.

Scope boundaries: no answer generation, no Gemini, no refusal logic, no Flask
routes, and no frontend code live here.
"""
