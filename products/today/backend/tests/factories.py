from datetime import datetime
from typing import Any

from products.signals.backend.facade import api as signals
from products.today.backend.logic.figure_sources import (
    KIND_MEASURED,
    KIND_QUESTION,
    NAMED_LABELS,
    NAMED_QUESTION,
    RELATION_QUESTION,
    RELATION_SAME,
    SOURCE_QUESTION,
)
from products.today.backend.logic.jev import JevPick
from products.today.backend.logic.signal_text import SignalInput


def signal(
    *,
    content: str = "",
    source_product: str = "signals_scout",
    source_type: str = "cross_source_issue",
    source_id: str = "source-1",
    signal_id: str = "signal-1",
    timestamp: str = "2026-10-01T10:00:00+00:00",
    extra: dict[str, Any] | None = None,
) -> SignalInput:
    return SignalInput(
        signal_id=signal_id,
        content=content,
        source_product=source_product,
        source_type=source_type,
        source_id=source_id,
        timestamp=datetime.fromisoformat(timestamp),
        extra=extra or {},
    )


def page_source(
    *,
    summary: str = "",
    solution: str | None = None,
    impact: str | None = None,
    action_prompts: list[str] | None = None,
) -> signals.ReportPageSource:
    return signals.ReportPageSource(
        summary=summary,
        sections=signals.ReportSections(lead="Lead.", impact=impact, solution=solution),
        action_prompts=action_prompts or [],
        repo_slug="example/web",
        signals=[],
    )


SURE = 0.95
AGREEING = {
    KIND_QUESTION: JevPick(label=KIND_MEASURED, probability=SURE),
    SOURCE_QUESTION: JevPick(label="A", probability=SURE),
    RELATION_QUESTION: JevPick(label=RELATION_SAME, probability=SURE),
    NAMED_QUESTION: JevPick(label=NAMED_LABELS[0], probability=SURE),
}


class SameAnswerJev:
    def __init__(self, answers: dict[str, JevPick]) -> None:
        self._answers = answers
        self.asked: list[str] = []

    def choice(self, items: list[str], question: str, labels: list[str]) -> list[JevPick | None]:
        self.asked.append(question)
        return [self._answers[question] for _ in items]

    def yes_probability(self, items: list[str], question: str) -> list[float | None]:
        return [None for _ in items]


class FakeJev:
    def __init__(self, texts: list[str], roles: dict[str, JevPick], explanations: dict[str, str]) -> None:
        self.texts = texts
        self.roles = roles
        self.explanations = explanations

    def _marked_part(self, item: str) -> str:
        part = item
        for text in self.texts:
            part = part.replace(text, "")
        return next((clause for clause in self.roles if clause in part), "")

    def choice(self, items: list[str], question: str, labels: list[str]) -> list[JevPick | None]:
        return [self.roles.get(self._marked_part(item)) for item in items]

    def yes_probability(self, items: list[str], question: str) -> list[float | None]:
        return [
            0.9 if any(clause in item and sentence in item for clause, sentence in self.explanations.items()) else 0.1
            for item in items
        ]


class PickJev(FakeJev):
    def __init__(self, pick: JevPick | None) -> None:
        super().__init__([], {}, {})
        self.pick = pick

    def choice(self, items: list[str], question: str, labels: list[str]) -> list[JevPick | None]:
        return [self.pick for _ in items]
