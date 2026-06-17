from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models import EventDefinition, EventProperty, PropertyDefinition, Team

from products.exports.backend.temporal.subscriptions.ai_subscription.schemas import (
    QueryPlan,
    QueryPlanStep,
    RelevantEvents,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.spec_generator import (
    PROMPT_MAX_LENGTH,
    PromptRejectedError,
    _event_property_names,
    _group_type_labels,
    _no_data_event_names,
    _person_property_names,
    _select_relevant_events,
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


class TestSelectRelevantEvents(APIBaseTest):
    @parameterized.expand(
        [
            ("single_real_event", ["export created"], ["export created"]),
            ("drops_hallucinated_name", ["export created", "totally made up event"], ["export created"]),
            ("dedupes_repeats", ["export created", "export created"], ["export created"]),
            ("preserves_model_order", ["alert created", "export created"], ["alert created", "export created"]),
        ]
    )
    @patch(f"{_SG}.MaxChatOpenAI")
    def test_maps_model_picks_to_real_events(
        self, _name: str, model_events: list[str], expected: list[str], mock_chat: MagicMock
    ) -> None:
        # the model's picks map to real events: hallucinated names dropped, repeats deduped, order preserved
        EventDefinition.objects.create(team=self.team, name="export created")
        EventDefinition.objects.create(team=self.team, name="alert created")
        mock_chat.return_value.with_structured_output.return_value.invoke.return_value = RelevantEvents(
            events=model_events
        )

        assert _select_relevant_events(self.team, self.user, "how are exports doing?") == expected

    @patch(f"{_SG}.MaxChatOpenAI")
    def test_substitutes_prompt_and_event_names_into_system_message(self, mock_chat: MagicMock) -> None:
        # Guards the {{{...}}} render — a dropped/typo'd substitution key would send literal placeholders
        # to the model and the other tests (which only check the return value) would still pass.
        EventDefinition.objects.create(team=self.team, name="export created")
        structured = mock_chat.return_value.with_structured_output.return_value
        structured.invoke.return_value = RelevantEvents(events=[])

        _select_relevant_events(self.team, self.user, "SELECTION_PROMPT_MARKER")

        (messages,) = structured.invoke.call_args[0]
        (_role, system_content) = messages[0]
        assert "SELECTION_PROMPT_MARKER" in system_content
        assert "export created" in system_content
        assert "{{{" not in system_content

    @parameterized.expand(
        [
            ("llm_error", {"side_effect": RuntimeError("boom")}),
            ("malformed_output", {"return_value": "not a RelevantEvents"}),
        ]
    )
    @patch(f"{_SG}.MaxChatOpenAI")
    def test_falls_back_to_empty_when_selection_unusable(
        self, _name: str, invoke_config: dict, mock_chat: MagicMock
    ) -> None:
        # an LLM error or a non-RelevantEvents result degrades to no relevant events rather than raising
        EventDefinition.objects.create(team=self.team, name="export created")
        mock_chat.return_value.with_structured_output.return_value.invoke.configure_mock(**invoke_config)

        assert _select_relevant_events(self.team, self.user, "exports") == []

    @patch(f"{_SG}.MaxChatOpenAI")
    def test_no_candidate_events_skips_the_llm(self, mock_chat: MagicMock) -> None:
        # no EventDefinitions → nothing to select from → never calls the model
        assert _select_relevant_events(self.team, self.user, "exports") == []
        mock_chat.assert_not_called()


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

    def test_excludes_other_teams_properties(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        EventProperty.objects.create(team=other_team, event="export created", property="leaked")
        EventProperty.objects.create(team=self.team, event="export created", property="mine")

        assert _event_property_names(self.team, ["export created"], per_event_limit=15) == {"export created": ["mine"]}


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

    @parameterized.expand(
        [
            ("single_property", ["format"], "format"),
            ("multiple_properties_sorted", ["status", "format", "duration"], "duration, format, status"),
        ]
    )
    @patch(f"{_SG}.get_group_types_for_project", return_value=[])
    @patch(f"{_SG}._top_event_names", return_value=[])
    def test_surfaces_selected_events_and_their_property_schema(
        self, _name: str, props: list[str], expected_list: str, _mock_top: object, _mock_groups: object
    ) -> None:
        for prop in props:
            EventProperty.objects.create(team=self.team, event="export created", property=prop)

        blob = build_context_blob(self.team, window_days=7, relevant_events=["export created"])

        assert "Events matching your request: export created" in blob
        # properties are listed alphabetically (the _event_property_names ordering)
        assert f"`export created` properties (use properties.<name>): {expected_list}" in blob

    @patch(f"{_SG}.get_group_types_for_project", return_value=[])
    @patch(f"{_SG}._top_event_names", return_value=["$pageview"])
    def test_injects_property_schema_for_selected_top_event(self, _mock_top: object, _mock_groups: object) -> None:
        EventProperty.objects.create(team=self.team, event="$pageview", property="$browser")

        blob = build_context_blob(self.team, window_days=7, relevant_events=["$pageview"])

        # $pageview is already under "Top events", so it's not repeated in the matched-names line...
        assert "Events matching your request" not in blob
        # ...but its property schema must still be surfaced (otherwise the planner can't see $browser).
        assert "`$pageview` properties (use properties.<name>): $browser" in blob

    @patch(f"{_SG}.get_group_types_for_project", return_value=[])
    @patch(f"{_SG}._top_event_names", return_value=[])
    def test_omits_relevant_section_without_selected_events(self, _mock_top: object, _mock_groups: object) -> None:
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
