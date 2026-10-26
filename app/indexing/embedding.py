"""The local, offline Sentence-Transformers embedding backend.

One embedding configuration is shared by every document and every query, so a
document vector and a query vector are always produced the same way. The
configuration is recorded in the index manifest, which is how a later reader can
tell whether an index was built with the settings it is now being queried with.

Model choice
------------

``sentence-transformers/all-MiniLM-L6-v2``: a general-purpose sentence
embedding model, 384 dimensions, about 90 MB, CPU-only. It was chosen because it
is already present in this machine's local Hugging Face cache, so no download is
required, and because it fits the project's CPU and memory constraints.

Offline guarantee
-----------------

``allow_download`` defaults to ``False``, and in that mode the hub is switched
off through ``HF_HUB_OFFLINE`` and ``TRANSFORMERS_OFFLINE`` before the model is
loaded. Hugging Face libraries otherwise make a network request even when the
model is already cached. A model that is not cached therefore fails with a clear
:class:`EmbeddingModelError` instead of silently downloading.

Normalisation
-------------

Vectors are L2-normalised (``REQUIREMENTS.md`` FR-IDX-02), so an inner-product
index ranks by cosine similarity. The index manifest records both facts, and
:mod:`app.indexing.vector_index` checks that they agree with the index type.

Scope boundaries: no FAISS code, no retrieval, no generation, no Flask.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass

import numpy as np

#: The one embedding model this project uses.
MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"

#: The model's embedding dimension. Checked against the dimension of the model
#: that actually loads, so a substituted model is reported rather than accepted.
EMBEDDING_DIMENSION = 384

#: Vectors are L2-normalised, so inner product equals cosine similarity.
NORMALIZE_EMBEDDINGS = True

#: A conservative CPU batch size, small enough for a laptop and large enough
#: that the model is not called once per chunk.
DEFAULT_BATCH_SIZE = 32


class EmbeddingError(RuntimeError):
    """Base class for embedding failures that are reported rather than guessed at."""


class EmbeddingDependencyError(EmbeddingError):
    """The embedding runtime is not installed in the interpreter that is running."""


class EmbeddingModelError(EmbeddingError):
    """The model could not be loaded, or is not the configured model."""


@dataclass(frozen=True)
class EmbeddingConfig:
    """The embedding configuration shared by every document and every query."""

    model_id: str = MODEL_ID
    dimension: int = EMBEDDING_DIMENSION
    normalize: bool = NORMALIZE_EMBEDDINGS
    batch_size: int = DEFAULT_BATCH_SIZE

    def to_manifest(self) -> dict:
        """The JSON-serialisable form recorded in the index manifest."""
        return {
            "model_id": self.model_id,
            "dimension": self.dimension,
            "normalize": self.normalize,
            "batch_size": self.batch_size,
        }

    @property
    def fingerprint(self) -> str:
        """A stable hash of this configuration, for compatibility checks."""
        payload = json.dumps(self.to_manifest(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def require_sentence_transformers():
    """Import the embedding runtime, or report exactly what is missing.

    The import is deferred to here so that importing this module — and running
    the tests that do not need a real model — works in an interpreter where
    ``sentence-transformers`` is not installed.
    """
    try:
        import sentence_transformers
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise EmbeddingDependencyError(
            "sentence-transformers is not installed in this interpreter "
            f"({sys.executable}). Install it into the project environment, or "
            "run this stage with an interpreter that already has it."
        ) from exc
    return sentence_transformers


class SentenceTransformerEmbedder:
    """Encodes text with one shared, locally cached Sentence-Transformers model.

    The model is loaded on first use and then reused, so a pipeline that embeds
    the corpus and then answers many queries loads the model once.
    """

    def __init__(
        self,
        config: EmbeddingConfig | None = None,
        *,
        allow_download: bool = False,
    ) -> None:
        self._config = config or EmbeddingConfig()
        self._allow_download = allow_download
        self._model = None

    @property
    def config(self) -> EmbeddingConfig:
        return self._config

    @property
    def dimension(self) -> int:
        return self._config.dimension

    @property
    def is_loaded(self) -> bool:
        """Whether the underlying model has been loaded yet."""
        return self._model is not None

    def _load_model(self):
        if self._model is not None:
            return self._model

        sentence_transformers = require_sentence_transformers()
        if not self._allow_download:
            # Without this, the hub may still make a request for a model that is
            # already cached. Setting the variables makes the offline promise
            # real rather than merely intended.
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"

        try:
            model = sentence_transformers.SentenceTransformer(
                self._config.model_id, device="cpu"
            )
        except Exception as exc:  # the library raises several unrelated types
            raise EmbeddingModelError(
                f"could not load embedding model {self._config.model_id!r}: {exc}. "
                "The model must already be present in the local Hugging Face "
                "cache; this stage does not download models."
            ) from exc

        loaded_dimension = int(model.get_sentence_embedding_dimension())
        if loaded_dimension != self._config.dimension:
            raise EmbeddingModelError(
                f"model {self._config.model_id!r} produces {loaded_dimension}-dimensional "
                f"vectors, but the configuration expects {self._config.dimension}. "
                "Refusing to continue with an unrecorded model change."
            )

        self._model = model
        return model

    def encode(self, texts, *, batch_size: int | None = None) -> np.ndarray:
        """Embed ``texts`` into a ``(len(texts), dimension)`` float32 array.

        Texts are encoded in batches, and the result is returned as one array so
        the caller does not have to re-assemble a list of per-batch arrays.
        """
        items = [str(text) for text in texts]
        if not items:
            return np.zeros((0, self._config.dimension), dtype=np.float32)

        model = self._load_model()
        vectors = model.encode(
            items,
            batch_size=batch_size or self._config.batch_size,
            normalize_embeddings=self._config.normalize,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        vectors = np.asarray(vectors, dtype=np.float32)
        expected_shape = (len(items), self._config.dimension)
        if vectors.shape != expected_shape:
            raise EmbeddingError(
                f"embedding model returned shape {vectors.shape}; expected {expected_shape}"
            )
        return vectors

    def encode_query(self, query: str) -> np.ndarray:
        """Embed a single query string, using the same configuration as documents."""
        return self.encode([query])[0]
