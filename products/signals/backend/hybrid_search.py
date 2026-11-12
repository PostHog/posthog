"""Pieces shared by the signals searches that merge a keyword ranking with a semantic one."""

from collections.abc import Hashable, Sequence
from typing import TypeVar

from django.db import models

# The standard constant from the reciprocal rank fusion paper. It keeps one top rank from outweighing
# agreement between the two rankings.
RRF_K = 60

K = TypeVar("K", bound=Hashable)


class SearchMode(models.TextChoices):
    HYBRID = "hybrid"
    SEMANTIC = "semantic"
    KEYWORD = "keyword"


class SemanticSearchUnavailable(Exception):
    """The query embedding or the vector read failed, so a semantic-only search has no ranking."""


def reciprocal_rank_fusion(rankings: Sequence[Sequence[K]]) -> dict[K, float]:
    """Each key's summed `1 / (RRF_K + rank)` over the rankings it appears in, so agreement outranks one high rank."""
    scores: dict[K, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
    return scores
