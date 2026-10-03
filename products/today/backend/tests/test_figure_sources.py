from django.test import SimpleTestCase

from parameterized import parameterized

from products.today.backend.logic.figure_sources import (
    KIND_LABELS,
    KIND_MEASURED,
    KIND_QUESTION,
    NAMED_LABELS,
    NAMED_QUESTION,
    RELATION_QUESTION,
    RELATION_SAME,
    SOURCE_QUESTION,
    UNNAMED,
    match_figures,
)
from products.today.backend.logic.jev import JevPick
from products.today.backend.tests.test_signal_views import signal

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

    def choice(self, items: list[str], question: str, labels: list[str]) -> list[JevPick | None]:
        return [self._answers[question] for _ in items]

    def yes(self, items: list[str], question: str) -> list[float | None]:
        return [None for _ in items]


class TestFigureSources(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "marks a measured number that one source states",
                "The export failed for 212 users.",
                ["On Monday the export failed for 212 users."],
                {},
                [("212", "On Monday the export failed for 212 users.")],
            ),
            (
                "never marks a zero",
                "The scanner saw 0 sessions.",
                ["The scanner saw 0 sessions."],
                {},
                [],
            ),
            (
                "drops the mark when Jev does not read the number as a measured result",
                "The export failed for 212 users.",
                ["On Monday the export failed for 212 users."],
                {KIND_QUESTION: JevPick(label=KIND_LABELS[1], probability=SURE)},
                [],
            ),
            (
                "drops the mark when the option order changes the source Jev picks",
                "The export failed for 212 users.",
                ["On Monday the export failed for 212 users.", "We count 212 users in the EU."],
                {},
                [],
            ),
            (
                "drops the mark when the source does not say what the number counts",
                "The export failed for 212 users.",
                ["Result: 212."],
                {NAMED_QUESTION: JevPick(label=UNNAMED, probability=SURE)},
                [],
            ),
        ]
    )
    def test_marks_only_proven_numbers(
        self,
        _name: str,
        lead: str,
        sources: list[str],
        answers: dict[str, JevPick],
        expected: list[tuple[str, str]],
    ) -> None:
        signals = [signal(content=text, signal_id=f"signal-{index}") for index, text in enumerate(sources)]
        matches = match_figures({"lead": lead}, signals, [], SameAnswerJev({**AGREEING, **answers}))
        assert [
            (match.claim.figure.text, match.source.source.sentence) for match in matches if match.source
        ] == expected
