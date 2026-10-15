from parameterized import parameterized
from pydantic import BaseModel

from products.replay_vision.backend.temporal.citation_review import citations_in, replace_citations


class _Answer(BaseModel):
    summary: str
    reasoning: str = ""


class TestCitationMarkers:
    @parameterized.expand(
        [
            (
                "moves one and removes another",
                "Opened billing (t 344). They downgraded. (t 351) Then left.",
                {1: 252, 2: None},
                [("Opened billing", 344), ("They downgraded.", 351)],
                "Opened billing (t 252). They downgraded. Then left.",
            ),
            (
                "a comma-joined marker numbers each second",
                "Clicked twice (t 10, 12) and gave up (t 20).",
                {2: None, 3: 25},
                [("Clicked twice", 10), ("Clicked twice", 12), ("Clicked twice and gave up", 20)],
                "Clicked twice (t 10) and gave up (t 25).",
            ),
        ]
    )
    def test_numbers_citations_in_reading_order_and_rewrites_only_the_moved_ones(
        self,
        _name: str,
        summary: str,
        moves: dict[int, int | None],
        expected_citations: list[tuple[str, int]],
        expected_summary: str,
    ) -> None:
        answer = _Answer(summary=summary)

        citations = citations_in(answer, ["summary"])

        assert [(c.claim, c.video_s) for c in citations] == expected_citations
        assert replace_citations(answer, ["summary"], moves).summary == expected_summary

    def test_numbering_runs_across_fields_and_leaves_other_fields_alone(self) -> None:
        answer = _Answer(summary="A (t 1).", reasoning="B (t 2).")

        rewritten = replace_citations(answer, ["summary", "reasoning"], {2: 9})

        assert [c.n for c in citations_in(answer, ["summary", "reasoning"])] == [1, 2]
        assert (rewritten.summary, rewritten.reasoning) == ("A (t 1).", "B (t 9).")
