from django.test import SimpleTestCase

from parameterized import parameterized

from products.today.backend.facade.enums import FigureText
from products.today.backend.logic.figure_sources import (
    KIND_LABELS,
    KIND_QUESTION,
    NAMED_QUESTION,
    RELATION_QUESTION,
    SOURCE_QUESTION,
    UNNAMED,
    match_figures,
)
from products.today.backend.logic.jev import JevPick
from products.today.backend.tests.factories import AGREEING, SURE, SameAnswerJev, signal

ALL_QUESTIONS = [KIND_QUESTION, SOURCE_QUESTION, RELATION_QUESTION, NAMED_QUESTION]


class TestFigureSources(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "marks a measured number that one source states",
                "The export failed for 212 users.",
                ["On Monday the export failed for 212 users."],
                {},
                [("212", "On Monday the export failed for 212 users.")],
                ALL_QUESTIONS,
            ),
            (
                "never marks a zero",
                "The scanner saw 0 sessions.",
                ["The scanner saw 0 sessions."],
                {},
                [],
                [],
            ),
            (
                "drops the mark when Jev does not read the number as a measured result",
                "The export failed for 212 users.",
                ["On Monday the export failed for 212 users."],
                {KIND_QUESTION: JevPick(label=KIND_LABELS[1], probability=SURE)},
                [],
                [KIND_QUESTION],
            ),
            (
                "drops the mark when the option order changes the source Jev picks",
                "The export failed for 212 users.",
                ["On Monday the export failed for 212 users.", "We count 212 users in the EU."],
                {},
                [],
                [KIND_QUESTION, SOURCE_QUESTION],
            ),
            (
                "drops the mark when the source does not say what the number counts",
                "The export failed for 212 users.",
                ["Result: 212."],
                {NAMED_QUESTION: JevPick(label=UNNAMED, probability=SURE)},
                [],
                ALL_QUESTIONS,
            ),
        ]
    )
    def test_marks_only_proven_numbers_and_asks_only_what_the_next_step_needs(
        self,
        _name: str,
        lead: str,
        sources: list[str],
        answers: dict[str, JevPick],
        expected: list[tuple[str, str]],
        asked: list[str],
    ) -> None:
        signals = [signal(content=text, signal_id=f"signal-{index}") for index, text in enumerate(sources)]
        jev = SameAnswerJev({**AGREEING, **answers})
        matches = match_figures({FigureText.LEAD: lead}, signals, [], jev)
        assert [(match.claim.figure.text, match.source.source.sentence) for match in matches] == expected
        assert jev.asked == asked
