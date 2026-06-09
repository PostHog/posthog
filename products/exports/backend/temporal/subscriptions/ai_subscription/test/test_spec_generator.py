from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.models import EventDefinition, EventProperty, PropertyDefinition

from products.exports.backend.temporal.subscriptions.ai_subscription.schemas import QueryPlan, QueryPlanStep
from products.exports.backend.temporal.subscriptions.ai_subscription.spec_generator import (
    PROMPT_MAX_LENGTH,
    PromptRejectedError,
    _event_property_names,
    _group_type_labels,
    _no_data_event_names,
    _person_property_names,
    _prompt_relevant_event_names,
    build_context_blob,
    generate_query_plan,
    sanitize_prompt,
)

_SG = "products.exports.backend.temporal.subscriptions.ai_subscription.spec_generator"


class TestSanitizePrompt:
    """`sanitize_prompt` is the public input-validation gate, so its three reject branches and the
    tag-stripping behaviour are pinned explicitly — a dropped branch would silently admit bad input."""

    @pytest.mark.parametrize("raw", [None, "", "   ", "\n\t "])
    def test_rejects_empty_or_whitespace(self, raw: str | None) -> None:
        with pytest.raises(PromptRejectedError, match="empty"):
            sanitize_prompt(raw)

    def test_rejects_over_max_length(self) -> None:
        with pytest.raises(PromptRejectedError, match="exceeds"):
            sanitize_prompt("x" * (PROMPT_MAX_LENGTH + 1))

    def test_rejects_prompt_that_is_only_framing_tags(self) -> None:
        # sanitize_user_text strips the framing markers, leaving nothing → empty rejection.
        with pytest.raises(PromptRejectedError, match="empty"):
            sanitize_prompt("<system></system>")

    def test_strips_html_tags_from_valid_prompt(self) -> None:
        assert sanitize_prompt("Show <script>alert(1)</script> pageviews") == "Show alert(1) pageviews"

    def test_returns_cleaned_prompt(self) -> None:
        assert sanitize_prompt("  Weekly pageviews summary  ") == "Weekly pageviews summary"


class TestNoDataEventNames(APIBaseTest):
    def test_returns_dormant_and_never_seen_events_excluding_recent(self) -> None:
        now = datetime.now(tz=UTC)
        EventDefinition.objects.create(team=self.team, name="recent_event", last_seen_at=now - timedelta(days=1))
        EventDefinition.objects.create(team=self.team, name="dormant_event", last_seen_at=now - timedelta(days=30))
        EventDefinition.objects.create(team=self.team, name="never_seen_event", last_seen_at=None)

        names = _no_data_event_names(self.team, window_days=7, limit=25)

        assert "recent_event" not in names
        assert "dormant_event" in names
        assert "never_seen_event" in names

    def test_respects_limit(self) -> None:
        now = datetime.now(tz=UTC)
        for i in range(5):
            EventDefinition.objects.create(team=self.team, name=f"dormant_{i}", last_seen_at=now - timedelta(days=30))

        assert len(_no_data_event_names(self.team, window_days=7, limit=2)) == 2


class TestPersonPropertyNames(APIBaseTest):
    def test_returns_person_properties_excluding_event_properties(self) -> None:
        PropertyDefinition.objects.create(team=self.team, name="plan", type=PropertyDefinition.Type.PERSON)
        PropertyDefinition.objects.create(team=self.team, name="country", type=PropertyDefinition.Type.PERSON)
        PropertyDefinition.objects.create(team=self.team, name="$browser", type=PropertyDefinition.Type.EVENT)

        names = _person_property_names(self.team, limit=30)

        assert "plan" in names
        assert "country" in names
        assert "$browser" not in names


class TestGroupTypeLabels(APIBaseTest):
    @patch(
        f"{_SG}.get_group_types_for_project",
        return_value=[
            {"group_type": "organization", "group_type_index": 0},
            {"group_type": "project", "group_type_index": 1},
        ],
    )
    def test_maps_group_types_to_indexed_paths(self, _mock_groups: object) -> None:
        labels = _group_type_labels(self.team)
        assert labels == ["group_0 = organization", "group_1 = project"]


class TestPromptRelevantEventNames(APIBaseTest):
    def test_matches_by_prompt_token_including_plural(self) -> None:
        EventDefinition.objects.create(team=self.team, name="export created")
        EventDefinition.objects.create(team=self.team, name="export failed")
        EventDefinition.objects.create(team=self.team, name="alert created")
        EventDefinition.objects.create(team=self.team, name="$pageview")

        # "exports" (plural) must still match the singular "export ..." event names
        names = _prompt_relevant_event_names(self.team, "how are exports doing?", limit=12)

        assert "export created" in names
        assert "export failed" in names
        assert "alert created" not in names
        assert "$pageview" not in names

    def test_returns_empty_when_prompt_is_only_generic_filler(self) -> None:
        EventDefinition.objects.create(team=self.team, name="export created")
        assert _prompt_relevant_event_names(self.team, "give me a weekly summary", limit=12) == []

    def test_respects_limit(self) -> None:
        for i in range(5):
            EventDefinition.objects.create(team=self.team, name=f"export variant {i}")
        assert len(_prompt_relevant_event_names(self.team, "exports", limit=2)) == 2


class TestEventPropertyNames(APIBaseTest):
    def test_groups_properties_by_event_in_one_query(self) -> None:
        EventProperty.objects.create(team=self.team, event="export created", property="status")
        EventProperty.objects.create(team=self.team, event="export created", property="format")
        EventProperty.objects.create(team=self.team, event="alert created", property="threshold")

        by_event = _event_property_names(self.team, ["export created"], per_event_limit=15)

        # ordered by property name; the un-queried event is absent
        assert by_event == {"export created": ["format", "status"]}

    def test_respects_per_event_limit(self) -> None:
        for i in range(5):
            EventProperty.objects.create(team=self.team, event="export created", property=f"prop_{i}")
        assert len(_event_property_names(self.team, ["export created"], per_event_limit=2)["export created"]) == 2

    def test_empty_for_no_events(self) -> None:
        assert _event_property_names(self.team, [], per_event_limit=15) == {}


class TestContextBlob(APIBaseTest):
    @patch(f"{_SG}.get_group_types_for_project", return_value=[{"group_type": "organization", "group_type_index": 0}])
    @patch(f"{_SG}._top_event_names", return_value=[])
    def test_includes_no_data_person_and_group_lines(self, _mock_top: object, _mock_groups: object) -> None:
        now = datetime.now(tz=UTC)
        EventDefinition.objects.create(team=self.team, name="dormant_event", last_seen_at=now - timedelta(days=30))
        PropertyDefinition.objects.create(team=self.team, name="plan", type=PropertyDefinition.Type.PERSON)

        blob = build_context_blob(self.team, window_days=7)

        assert "Events defined but with no data in the last 7 day(s):" in blob
        assert "dormant_event" in blob
        assert "Person properties (reference as person.properties.<name>" in blob
        assert "plan" in blob
        assert "Group/account types (reference as group_<index>.properties.<name>" in blob
        assert "group_0 = organization" in blob

    @patch(f"{_SG}.get_group_types_for_project", return_value=[])
    @patch(f"{_SG}._top_event_names", return_value=[])
    def test_surfaces_prompt_relevant_events_and_their_property_schema(
        self, _mock_top: object, _mock_groups: object
    ) -> None:
        EventDefinition.objects.create(team=self.team, name="export created", last_seen_at=datetime.now(tz=UTC))
        EventProperty.objects.create(team=self.team, event="export created", property="format")

        blob = build_context_blob(self.team, window_days=7, prompt="how are exports doing?")

        assert "Events matching your request: export created" in blob
        assert "`export created` properties (use properties.<name>): format" in blob

    @patch(f"{_SG}.get_group_types_for_project", return_value=[])
    @patch(f"{_SG}._top_event_names", return_value=[])
    def test_omits_relevant_section_without_a_prompt(self, _mock_top: object, _mock_groups: object) -> None:
        EventDefinition.objects.create(team=self.team, name="export created", last_seen_at=datetime.now(tz=UTC))

        blob = build_context_blob(self.team, window_days=7)

        assert "Events matching your request" not in blob


class TestGenerateQueryPlanSubstitution(APIBaseTest):
    """Test the substitution *behaviour* — that the planner actually receives the prompt and context
    interpolated into the template — rather than asserting prose fragments exist in the prompt string.
    Prompt *quality* (do the guardrails work?) belongs in an LLM eval, not a unit test."""

    @patch(f"{_SG}.MaxChatOpenAI")
    def test_substitutes_prompt_and_context_into_system_message(self, mock_chat: MagicMock) -> None:
        structured = mock_chat.return_value.with_structured_output.return_value
        structured.invoke.return_value = QueryPlan(
            overall_intent="intent",
            steps=[QueryPlanStep(description="d", hogql="SELECT 1")],
        )

        generate_query_plan(
            cleaned_prompt="CLEANED_PROMPT_MARKER",
            context_blob="CONTEXT_BLOB_MARKER",
            team=self.team,
            user=self.user,
        )

        (messages,) = structured.invoke.call_args[0]
        (_role, system_content) = messages[0]
        assert "CLEANED_PROMPT_MARKER" in system_content
        assert "CONTEXT_BLOB_MARKER" in system_content
        # The template's `{{{...}}}` placeholders must be gone — proving substitution ran.
        assert "{{{" not in system_content

    @patch(f"{_SG}.MaxChatOpenAI")
    def test_rejects_malformed_planner_output(self, mock_chat: MagicMock) -> None:
        structured = mock_chat.return_value.with_structured_output.return_value
        structured.invoke.return_value = "not a QueryPlan"

        with pytest.raises(PromptRejectedError, match="malformed"):
            generate_query_plan(cleaned_prompt="p", context_blob="c", team=self.team, user=self.user)
