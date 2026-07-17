import re

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.exports.backend.temporal.subscriptions.ai_subscription.prompts import (
    HOGQL_FIX_PROMPT,
    PLAN_GENERATION_PROMPT,
    resolve_prompt,
)

from ee.hogai.chat_agent.sql.prompts import (
    HOGQL_DIALECT_RULES,
    HOGQL_FUNCTION_CASING_RULES,
    SQL_EXPRESSIONS_DOCS,
    SQL_SUPPORTED_AGGREGATIONS_DOCS,
    SQL_SUPPORTED_FUNCTIONS_DOCS,
)

_P = "products.exports.backend.temporal.subscriptions.ai_subscription.prompts"


@parameterized.expand([("planner", PLAN_GENERATION_PROMPT), ("hogql_fix", HOGQL_FIX_PROMPT)])
def test_prompt_embeds_shared_hogql_rules(_name: str, prompt: str) -> None:
    # Casing + dialect rules are shared verbatim from the SQL assistant skill; if the import breaks or a
    # placeholder stops resolving, the planner/fixer silently lose the shared HogQL guidance.
    assert HOGQL_FUNCTION_CASING_RULES in prompt
    assert HOGQL_DIALECT_RULES in prompt
    assert not re.search(r"\{\{\{hogql_\w+\}\}\}", prompt)  # every shared placeholder resolved


def test_planner_embeds_shared_reference_docs() -> None:
    # The expressions/functions/aggregations reference is shared from the SQL assistant so both stay in
    # sync; guards the wiring that injects the full reference into report planning.
    for doc in (SQL_EXPRESSIONS_DOCS, SQL_SUPPORTED_FUNCTIONS_DOCS, SQL_SUPPORTED_AGGREGATIONS_DOCS):
        assert doc in PLAN_GENERATION_PROMPT


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
