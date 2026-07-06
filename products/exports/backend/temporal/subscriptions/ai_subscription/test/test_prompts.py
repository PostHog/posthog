import re

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.exports.backend.temporal.subscriptions.ai_subscription.prompts import (
    HOGQL_FIX_PROMPT,
    PLAN_GENERATION_PROMPT,
    resolve_prompt,
)

_P = "products.exports.backend.temporal.subscriptions.ai_subscription.prompts"


class TestPlannerWindowInstruction:
    """The window-determinism fix lives in the prompt's example patterns — the planner copies them.
    These guard against re-introducing the `now()`-relative date math that caused timezone query
    errors and run-to-run drift."""

    @parameterized.expand(
        [
            ("planner", PLAN_GENERATION_PROMPT),
            ("hogql_fix", HOGQL_FIX_PROMPT),
        ]
    )
    def test_instructs_explicit_window_and_forbids_now_interval(self, _name: str, prompt: str) -> None:
        # The half-open `toDateTime(...)` filter is the template the model must copy/preserve.
        assert "toDateTime(" in prompt
        # `now()` may appear only in the prohibition prose (`now()` / `now() - INTERVAL …` / `today()`).
        # A *usable* example — `now()` wired into concrete date-math or time-bucketing that the model
        # would copy verbatim — must not appear anywhere, or the planner reintroduces the run-to-run
        # drift the fix removes. Guard both shapes rather than two exact literals, since the last such
        # example (`toStartOfDay(now())`) slipped through a literal-match guard.
        assert not re.search(r"toStartOf\w+\(\s*now\(\)", prompt)
        assert not re.search(r"now\(\)\s*[-+]\s*INTERVAL\s+\d", prompt)


@patch(f"{_P}.ph_scoped_capture")
@patch(f"{_P}.get_prompt_by_name_from_cache", return_value={"prompt": "managed body"})
def test_resolve_prompt_uses_managed_prompt_when_present(_mock_cache: MagicMock, _scoped: MagicMock) -> None:
    assert resolve_prompt(MagicMock(), "ai-subscription-planner", "code default") == "managed body"


class TestResolvePromptFallback:
    @parameterized.expand(
        [
            ("missing", None),
            ("empty_string", {"prompt": ""}),
            ("whitespace_only", {"prompt": "   "}),
            ("non_string", {"prompt": 123}),
        ]
    )
    @patch(f"{_P}.ph_scoped_capture")
    @patch(f"{_P}.get_prompt_by_name_from_cache")
    def test_falls_back_to_default(self, _name: str, cached: object, mock_cache: MagicMock, _scoped: MagicMock) -> None:
        mock_cache.return_value = cached
        assert resolve_prompt(MagicMock(), "ai-subscription-planner", "code default") == "code default"

    @patch(f"{_P}.ph_scoped_capture")
    @patch(f"{_P}.get_prompt_by_name_from_cache", side_effect=RuntimeError("cache down"))
    def test_falls_back_on_lookup_error(self, _mock_cache: MagicMock, _scoped: MagicMock) -> None:
        assert resolve_prompt(MagicMock(), "ai-subscription-planner", "code default") == "code default"


@parameterized.expand(
    [
        ("managed", {"prompt": "managed body"}, "managed"),
        ("fallback", None, "fallback"),
    ]
)
@patch(f"{_P}.ph_scoped_capture")
@patch(f"{_P}.get_prompt_by_name_from_cache")
def test_resolve_prompt_captures_source_event(
    _name: str,
    cached: object,
    expected_source: str,
    mock_cache: MagicMock,
    mock_scoped: MagicMock,
) -> None:
    mock_cache.return_value = cached
    capture = MagicMock()
    mock_scoped.return_value.__enter__.return_value = capture
    team = MagicMock()
    team.uuid = "team-uuid"
    team.id = 7

    resolve_prompt(team, "ai-subscription-synthesis", "code default")

    capture.assert_called_once()
    call = capture.call_args.kwargs
    assert call["event"] == "ai_subscription_prompt_resolved"
    assert call["distinct_id"] == "team-uuid"
    assert call["properties"] == {
        "feature": "ai_subscription",
        "prompt_name": "ai-subscription-synthesis",
        "source": expected_source,
        "team_id": 7,
        "$process_person_profile": False,
    }
