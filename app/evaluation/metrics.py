"""Information-retrieval metrics for the retrieval evaluation.

Only the arithmetic lives here: given the ordered list of chunk IDs a retriever
returned and the set of chunk IDs judged relevant, each function returns one
number. The formulas are stated explicitly, because a metric whose definition is
implied cannot be checked against its own results.

With ``relevant`` the judged-relevant set and ``retrieved`` the ranked result
list (best first):

* ``recall_at_k``          = |relevant ∩ retrieved[:k]| / |relevant|
* ``precision_at_k``       = |relevant ∩ retrieved[:k]| / k
* ``reciprocal_rank_at_k`` = 1 / rank of the first relevant chunk in
  ``retrieved[:k]``, or 0 when none is present
* ``hit_at_k``             = 1.0 when any relevant chunk is in ``retrieved[:k]``,
  else 0.0

A query with an empty relevance set has no recall to speak of. The recall and
precision functions reject an empty ``relevant`` set instead of returning a
misleading 0 or 1; the caller reports the scores of an unanswerable query
instead of a recall for it. ``precision_at_k`` uses ``k`` as its denominator,
so a retriever that returns fewer than ``k`` chunks is not rewarded for it.

No metric here uses a similarity threshold. A score is a ranking fact, not a
statement that a passage answers the question (``REQUIREMENTS.md`` AC-04), so
relevance comes only from the labels, never from the score.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

#: The cut-offs the evaluation reports. Small on purpose: a citation list a
#: person reads is short, and the agreed retrieval range is still an open
#: decision (``REQUIREMENTS.md`` Q7).
DEFAULT_K_VALUES: tuple[int, ...] = (1, 3, 5, 10)


class MetricError(ValueError):
    """A metric was asked for something it cannot define."""


def _check_k(k: int) -> None:
    if not isinstance(k, int) or isinstance(k, bool) or k <= 0:
        raise MetricError(f"k must be a positive integer, got {k!r}")


def _relevant_set(relevant: Iterable[str]) -> set[str]:
    items = {str(item) for item in relevant}
    if not items:
        raise MetricError(
            "an empty relevance set has no recall or precision; a query with no "
            "answer is reported through its scores, not through recall"
        )
    return items


def recall_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """The fraction of judged-relevant chunks found in the top ``k``."""
    _check_k(k)
    relevant_set = _relevant_set(relevant)
    found = len(set(retrieved[:k]) & relevant_set)
    return found / len(relevant_set)


def precision_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """The fraction of the top ``k`` results that are judged relevant."""
    _check_k(k)
    relevant_set = _relevant_set(relevant)
    found = len(set(retrieved[:k]) & relevant_set)
    return found / k


def reciprocal_rank_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """``1 / rank`` of the first relevant chunk in the top ``k``, else 0."""
    _check_k(k)
    relevant_set = _relevant_set(relevant)
    for position, chunk_id in enumerate(retrieved[:k], start=1):
        if chunk_id in relevant_set:
            return 1.0 / position
    return 0.0


def hit_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """1.0 when at least one relevant chunk is in the top ``k``, else 0.0."""
    _check_k(k)
    relevant_set = _relevant_set(relevant)
    return 1.0 if set(retrieved[:k]) & relevant_set else 0.0


def rank_of_first_relevant(retrieved: Sequence[str], relevant: Iterable[str]) -> int | None:
    """The one-based rank of the first relevant chunk, or ``None`` if absent.

    Reported alongside the aggregated numbers so a single failure can be read
    directly rather than inferred from a zero.
    """
    relevant_set = {str(item) for item in relevant}
    for position, chunk_id in enumerate(retrieved, start=1):
        if chunk_id in relevant_set:
            return position
    return None


def mean(values: Iterable[float]) -> float | None:
    """The arithmetic mean, or ``None`` for an empty sequence.

    ``None`` rather than 0.0 on purpose: a metric over no queries is undefined,
    and a 0.0 would read as a measured failure.
    """
    items = [float(value) for value in values]
    if not items:
        return None
    return sum(items) / len(items)
