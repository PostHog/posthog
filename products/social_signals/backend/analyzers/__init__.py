"""Mention analyzers.

An analyzer takes a :class:`Mention` and produces a structured ``result`` dict
that is persisted as a :class:`MentionAnalysis` row, keyed by ``(mention, kind)``.

Adding a new analyzer:

1. Create ``my_analyzer.py`` with a class implementing :class:`MentionAnalyzer`.
2. Set ``kind`` to a value in :class:`AnalyzerKind` (extend the enum if needed).
3. Register the class in :data:`ANALYZER_REGISTRY` below.

The Celery task ``analyze_mention_task`` iterates the registry and runs each
analyzer whose ``enabled_by_default`` is True. Failures in one analyzer never
prevent others from running.
"""

from .base import MentionAnalyzer
from .classify_and_sentiment import ClassifyAndSentimentAnalyzer

ANALYZER_REGISTRY: dict[str, type[MentionAnalyzer]] = {
    ClassifyAndSentimentAnalyzer.kind: ClassifyAndSentimentAnalyzer,
}


def get_default_analyzers() -> list[type[MentionAnalyzer]]:
    """Analyzers that run automatically when a new mention is ingested."""
    return [cls for cls in ANALYZER_REGISTRY.values() if cls.enabled_by_default]


__all__ = [
    "MentionAnalyzer",
    "ClassifyAndSentimentAnalyzer",
    "ANALYZER_REGISTRY",
    "get_default_analyzers",
]
