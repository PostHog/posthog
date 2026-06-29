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
        # The relative window date-math the fix removes must not appear as a usable example. The
        # prohibition text says "Never now() - INTERVAL …" with an ellipsis, so a concrete
        # `now() - INTERVAL <n> DAY` example (the thing models copy) is what we're guarding against.
        assert "now() - INTERVAL 7 DAY" not in prompt
        assert "now() - INTERVAL 14 DAY" not in prompt


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
