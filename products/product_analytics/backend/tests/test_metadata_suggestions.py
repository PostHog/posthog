import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.llm.system_one import Answer, NoulAnswer, SystemOneResult
from posthog.llm.system_one_client import GATEWAY_MAX_QUESTIONS
from posthog.models import Team

from products.product_analytics.backend.presentation.metadata_suggestions import (
    JEV_MODEL,
    JEV_WINDOW_TOKENS,
    MAX_STATE_BYTES,
    MAX_TAG_NAME_CHARS,
    MAX_TAGS,
    SUGGESTION_TIMEOUT_SECONDS,
    InsightContext,
    InsightTooLargeForSuggestions,
    _tag_question,
    build_insight_context,
    suggest_tags,
)

BUILD = "products.product_analytics.backend.presentation.metadata_suggestions.build_system_one_client"

_CONTEXT = InsightContext(summary="Type: TrendsQuery\nSeries: $pageview", name="Signups by country")


def _result(answers: Mapping[str, Answer]) -> SystemOneResult:
    return SystemOneResult(model=JEV_MODEL, answers=answers, input_tokens=10)


def _answer_all(probability: float) -> MagicMock:
    return MagicMock(
        side_effect=lambda **request: _result(
            {key: NoulAnswer(probability=probability) for key in request["questions"]}
        )
    )


@contextmanager
def _jev(decide: MagicMock) -> Iterator[MagicMock]:
    with patch(BUILD) as build:
        build.return_value.decide = decide
        yield build


class TestMetadataSuggestions(SimpleTestCase):
    def test_tags_keep_only_confident_matches_and_never_invent_one(self) -> None:
        decide = MagicMock(
            return_value=_result(
                {
                    "t0": NoulAnswer(probability=0.9),
                    "t1": NoulAnswer(probability=0.2),
                    "t2": NoulAnswer(probability=0.6),
                }
            )
        )
        with _jev(decide) as build:
            suggestion = suggest_tags(1, _CONTEXT, ["growth", "billing", "marketing"])

        assert suggestion.tags == ("growth", "marketing")
        # No TypeSafe fallback: this metadata must never reach a third party.
        assert build.call_args.kwargs == {
            "model": JEV_MODEL,
            "ai_product": "product_analytics",
            "distinct_id": "team-1",
            "timeout": SUGGESTION_TIMEOUT_SECONDS,
        }
        sent = decide.call_args.kwargs
        assert sent["state"]["tags"] == {"t0": "growth", "t1": "billing", "t2": "marketing"}
        assert sent["state"]["subject"]["name"] == "Signups by country"
        # User text travels in state, never in the instructions.
        assert all("Signups" not in str(question.instructions) for question in sent["questions"].values())

    def test_tags_split_into_requests_the_gateway_accepts(self) -> None:
        tags = [f"tag {index}" for index in range(GATEWAY_MAX_QUESTIONS + 8)]
        decide = _answer_all(0.9)
        with _jev(decide) as build:
            suggestion = suggest_tags(1, _CONTEXT, tags)

        assert [len(call.kwargs["questions"]) for call in decide.call_args_list] == [GATEWAY_MAX_QUESTIONS, 8]
        assert set(suggestion.tags) == set(tags)
        # The batches run one after another, so together they wait no longer than one request may.
        assert [call.kwargs["timeout"] for call in build.call_args_list] == [SUGGESTION_TIMEOUT_SECONDS / 2] * 2

    def test_tags_without_any_existing_tag_skip_the_call(self) -> None:
        decide = MagicMock()
        with _jev(decide):
            assert suggest_tags(1, _CONTEXT, []).tags == ()
        decide.assert_not_called()

    def test_state_stays_inside_the_model_window(self) -> None:
        long_tags = [f"{i:03d}" + "z" * 252 for i in range(MAX_TAGS)]
        long_context = InsightContext(summary="s" * 5000, name="n" * 400, description="d" * 2000)
        decide = _answer_all(0.95)
        with _jev(decide):
            suggestion = suggest_tags(1, long_context, long_tags)
        assert all(
            len(json.dumps(call.kwargs["state"], ensure_ascii=False).encode("utf-8")) <= MAX_STATE_BYTES
            for call in decide.call_args_list
        )
        assert set(suggestion.tags) == set(long_tags)

    def test_largest_state_and_question_fit_the_model_window(self) -> None:
        # A token holds at least one UTF-8 byte, so bytes are an upper bound on tokens.
        prompt_format_headroom_tokens = 512
        question = _tag_question(f"t{MAX_TAGS - 1}")
        question_bytes = sum(
            len(text.encode("utf-8"))
            for text in (question.instructions, question.criteria_true, question.criteria_false)
        )
        assert MAX_STATE_BYTES + question_bytes <= JEV_WINDOW_TOKENS - prompt_format_headroom_tokens

    @parameterized.expand(
        [
            ("ascii_overflow", "y" * (MAX_STATE_BYTES + 1)),
            (
                "multibyte_overflow",
                "字" * (MAX_STATE_BYTES - 200),
            ),
        ]
    )
    def test_state_rejects_oversized_insights(self, _name: str, description: str) -> None:
        decide = MagicMock()
        with _jev(decide), self.assertRaises(InsightTooLargeForSuggestions):
            suggest_tags(1, InsightContext(summary="", description=description), ["growth"])
        decide.assert_not_called()

    @parameterized.expand(
        [
            ("differ_at_the_end", ["z" * MAX_TAG_NAME_CHARS + "-v1", "z" * MAX_TAG_NAME_CHARS + "-v2"], 2),
            ("differ_only_in_the_middle", ["z" * MAX_TAG_NAME_CHARS + m + "z" * MAX_TAG_NAME_CHARS for m in "ab"], 1),
        ]
    )
    def test_long_tag_names_are_sent_once_per_distinct_clipped_name(
        self, _name: str, tags: list[str], expected_count: int
    ) -> None:
        decide = _answer_all(0.9)
        with _jev(decide):
            suggestion = suggest_tags(1, _CONTEXT, tags)

        sent_names = [value for call in decide.call_args_list for value in call.kwargs["state"]["tags"].values()]
        assert len(sent_names) == len(set(sent_names)) == expected_count
        assert tags[0] in suggestion.tags

    def test_path_points_never_reach_the_model(self) -> None:
        query = {
            "kind": "InsightVizNode",
            "source": {"kind": "PathsQuery", "pathsFilter": {"startPoint": "/users/secret", "endPoint": "/secret"}},
        }
        context = build_insight_context(MagicMock(spec=Team), query, name="", description="")

        assert "secret" not in context.summary
        assert "PathsQuery" in context.summary
