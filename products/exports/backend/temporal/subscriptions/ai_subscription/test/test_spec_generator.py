from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

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
    MAX_PINNED_EVENTS,
    PROMPT_MAX_LENGTH,
    RELEVANT_EVENTS_LIMIT,
    PromptRejectedError,
    ReportWindow,
    _event_property_names,
    _extract_quoted_event_tokens,
    _group_type_labels,
    _no_data_event_names,
    _person_property_names,
    _pinned_event_names,
    _recent_event_names,
    _select_relevant_events,
    build_context_blob,
    compute_report_window,
    generate_query_plan,
    sanitize_prompt,
)

_SG = "products.exports.backend.temporal.subscriptions.ai_subscription.spec_generator"


def _window(days: int = 7) -> ReportWindow:
    # A fixed-ish window for context-blob tests: end = now, start = now - days. The dormant-event
    # cases below rely on start being recent enough that a 30-day-old event predates it.
    end = datetime.now(tz=UTC)
    return ReportWindow(start=end - timedelta(days=days), end=end)


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
        cutoff = now - timedelta(days=7)
        EventDefinition.objects.create(team=self.team, name="recent_event", last_seen_at=now - timedelta(days=1))
        EventDefinition.objects.create(team=self.team, name="dormant_event", last_seen_at=now - timedelta(days=30))
        EventDefinition.objects.create(team=self.team, name="never_seen_event", last_seen_at=None)

        names = _no_data_event_names(self.team, cutoff=cutoff, limit=25)

        assert "recent_event" not in names
        assert "dormant_event" in names
        assert "never_seen_event" in names

    def test_respects_limit(self) -> None:
        now = datetime.now(tz=UTC)
        for i in range(5):
            EventDefinition.objects.create(team=self.team, name=f"dormant_{i}", last_seen_at=now - timedelta(days=30))

        assert len(_no_data_event_names(self.team, cutoff=now - timedelta(days=7), limit=2)) == 2


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

    @patch(f"{_SG}.MaxChatOpenAI")
    def test_pins_named_event_the_llm_did_not_pick(self, mock_chat: MagicMock) -> None:
        # The deterministic guarantee: a backticked event the LLM ignores is still force-included.
        EventDefinition.objects.create(team=self.team, name="export created")
        mock_chat.return_value.with_structured_output.return_value.invoke.return_value = RelevantEvents(events=[])

        assert _select_relevant_events(self.team, self.user, "how is `export created` doing?") == ["export created"]

    @patch(f"{_SG}.MaxChatOpenAI")
    def test_unions_pinned_event_ahead_of_llm_picks(self, mock_chat: MagicMock) -> None:
        # Pinned event leads; the LLM's own (real) pick is kept and de-duped against it.
        EventDefinition.objects.create(team=self.team, name="export created")
        EventDefinition.objects.create(team=self.team, name="alert created")
        mock_chat.return_value.with_structured_output.return_value.invoke.return_value = RelevantEvents(
            events=["alert created", "export created"]
        )

        assert _select_relevant_events(self.team, self.user, "how is `export created` doing?") == [
            "export created",
            "alert created",
        ]

    @patch(f"{_SG}.MaxChatOpenAI")
    def test_pinned_event_survives_when_llm_fills_the_cap(self, mock_chat: MagicMock) -> None:
        # The named event is created last (oldest last_seen_at → outside the LLM's leading picks) and the
        # LLM returns a full cap's worth of other events. The pin must not be truncated by the cap.
        for i in range(RELEVANT_EVENTS_LIMIT):
            EventDefinition.objects.create(team=self.team, name=f"event_{i}", last_seen_at=datetime.now(tz=UTC))
        EventDefinition.objects.create(team=self.team, name="named_event", last_seen_at=None)
        mock_chat.return_value.with_structured_output.return_value.invoke.return_value = RelevantEvents(
            events=[f"event_{i}" for i in range(RELEVANT_EVENTS_LIMIT)]
        )

        selected = _select_relevant_events(self.team, self.user, "tell me about `named_event`")

        # The pin leads and survives; the cap drops the LLM's last pick instead of the named event.
        assert selected[0] == "named_event"
        assert len(selected) == RELEVANT_EVENTS_LIMIT

    @patch(f"{_SG}.CANDIDATE_EVENTS_LIMIT", 5)
    @patch(f"{_SG}.MaxChatOpenAI")
    def test_pins_event_outside_the_candidate_cap(self, mock_chat: MagicMock) -> None:
        # The whole reason the pin scan has its own (larger) bound: an event ranked below the candidate
        # cap is invisible to the selection LLM, but an explicit mention must still resolve. With the cap
        # patched to 5, the named event (oldest last_seen_at) falls outside the candidate slice.
        for i in range(5):
            EventDefinition.objects.create(team=self.team, name=f"common_{i}", last_seen_at=datetime.now(tz=UTC))
        EventDefinition.objects.create(team=self.team, name="rare_event", last_seen_at=None)
        mock_chat.return_value.with_structured_output.return_value.invoke.return_value = RelevantEvents(events=[])

        assert _select_relevant_events(self.team, self.user, "what about `rare_event`?") == ["rare_event"]


class TestExtractQuotedEventTokens:
    @parameterized.expand(
        [
            ("backticks", "how is `export created`?", {"export created"}),
            ("double_quotes", 'how is "export created"?', {"export created"}),
            ("single_quotes", "how is 'export created'?", {"export created"}),
            ("mixed_quote_styles", "`a` and \"b\" and 'c'", {"a", "b", "c"}),
            ("casefolds_and_collapses_whitespace", "`Export   Created`", {"export created"}),
            ("none_present", "how are exports doing?", set()),
            ("ignores_unbalanced_quote", "how is `export created doing?", set()),
        ]
    )
    def test_extracts_normalized_quoted_tokens(self, _name: str, prompt: str, expected: set[str]) -> None:
        assert _extract_quoted_event_tokens(prompt) == expected


class TestPinnedEventNames:
    @parameterized.expand(
        [
            ("quoted_name_pinned", "how is `export created`?", ["export created"]),
            ("case_insensitive_match", "how is `EXPORT CREATED`?", ["export created"]),
            ("bare_exact_single_word_pinned", "trends for signup over time", ["signup"]),
            ("bare_exact_multi_word_pinned", "how is export created trending", ["export created"]),
            ("nonexistent_quoted_name_ignored", "how is `totally made up`?", []),
            ("substring_does_not_match", "tell me about signups please", []),
            ("no_reference_pins_nothing", "give me a weekly summary", []),
        ]
    )
    def test_pins_only_validated_named_events(self, _name: str, prompt: str, expected: list[str]) -> None:
        assert _pinned_event_names(prompt, ["export created", "signup"]) == expected

    @parameterized.expand(
        [
            # `$` and `.` are part of an event-name token, so `$pageview` and `app.opened` match as
            # whole names but never as a bare `pageview`/`opened` slice of a larger token.
            ("quoted_dollar_name", "how is `$pageview`?", ["$pageview"]),
            ("bare_dollar_name_excludes_plain", "spike in $pageview today", ["$pageview"]),
            ("bare_plain_name_excludes_dollar", "how many pageview events", ["pageview"]),
            ("dotted_name_pinned", "trend of app.opened", ["app.opened"]),
            ("embedded_in_identifier_not_matched", "check my_pageview_handler logs", []),
        ]
    )
    def test_special_char_token_boundaries(self, _name: str, prompt: str, expected: list[str]) -> None:
        assert _pinned_event_names(prompt, ["$pageview", "pageview", "app.opened"]) == expected

    def test_caps_pinned_count_at_max(self) -> None:
        # A degenerate prompt naming more events than the ceiling pins at most MAX_PINNED_EVENTS, so the
        # planner context and the downstream property lookup stay bounded.
        names = [f"evt_{i}" for i in range(MAX_PINNED_EVENTS + 5)]
        prompt = " ".join(f"`{n}`" for n in names)

        assert len(_pinned_event_names(prompt, names)) == MAX_PINNED_EVENTS


class TestRecentEventNames(APIBaseTest):
    def test_scopes_to_team_and_respects_limit(self) -> None:
        other = Team.objects.create(organization=self.organization, name="other")
        EventDefinition.objects.create(team=other, name="other_team_event")
        for i in range(3):
            EventDefinition.objects.create(team=self.team, name=f"evt_{i}", last_seen_at=datetime.now(tz=UTC))

        names = _recent_event_names(self.team, limit=2)

        assert len(names) == 2
        assert "other_team_event" not in names


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


class TestComputeReportWindow:
    """`compute_report_window` is the pure core of the timezone-aware window. It's the fix for the
    UTC-anchored, send-time→midnight gap, so its three behaviours are pinned: since-last-delivery
    anchoring, the no-prior-delivery fallback, and timezone correctness (a regression here is the
    exact customer bug)."""

    @staticmethod
    def _team(timezone: str = "UTC") -> Team:
        # In-memory only — compute_report_window is pure and timezone_info just wraps ZoneInfo(tz),
        # so no DB row is needed and the test stays at the cheapest rung.
        return Team(timezone=timezone)

    def test_anchors_start_to_last_successful_delivery(self) -> None:
        now = datetime(2026, 6, 29, 16, 0, tzinfo=UTC)
        last = datetime(2026, 6, 28, 16, 0, tzinfo=UTC)

        window = compute_report_window(self._team(), last_successful_delivery_at=last, now=now, window_days=1)

        # Gap-free: start is exactly the previous send, not now - window_days (which would be identical
        # here, but the next case proves they diverge when the prior send drifted).
        assert window.start == last.astimezone(ZoneInfo("UTC"))
        assert window.end == now.astimezone(ZoneInfo("UTC"))

    def test_since_last_delivery_can_exceed_window_days(self) -> None:
        # A weekly sub (window_days=7) whose prior delivery was 10 days ago must cover the whole gap,
        # not just the last 7 days — proving start follows the delivery, not the cadence default.
        now = datetime(2026, 6, 29, 16, 0, tzinfo=UTC)
        last = datetime(2026, 6, 19, 16, 0, tzinfo=UTC)

        window = compute_report_window(self._team(), last_successful_delivery_at=last, now=now, window_days=7)

        assert window.start == last
        assert (window.end - window.start) == timedelta(days=10)

    def test_falls_back_to_window_days_without_prior_delivery(self) -> None:
        now = datetime(2026, 6, 29, 16, 0, tzinfo=UTC)

        window = compute_report_window(self._team(), last_successful_delivery_at=None, now=now, window_days=7)

        assert window.end == now
        assert window.start == now - timedelta(days=7)

    @parameterized.expand(
        [
            ("sydney", "Australia/Sydney"),
            ("la", "America/Los_Angeles"),
        ]
    )
    def test_bounds_are_in_team_timezone(self, _name: str, timezone: str) -> None:
        now = datetime(2026, 6, 29, 16, 0, tzinfo=UTC)

        window = compute_report_window(self._team(timezone), last_successful_delivery_at=None, now=now, window_days=1)

        # Same instant, rendered in the team's tz — utcoffset proves the bound carries the team's
        # offset (the UTC-anchored bug had a zero offset regardless of team timezone).
        assert window.end.tzinfo == ZoneInfo(timezone)
        assert window.end.utcoffset() == now.astimezone(ZoneInfo(timezone)).utcoffset()
        # The literal the planner sees is the project-tz wall clock (no offset), so the LLM never does
        # tz math — HogQL resolves a bare datetime against the project timezone.
        assert window.end_literal == now.astimezone(ZoneInfo(timezone)).strftime("%Y-%m-%d %H:%M:%S")

    def test_clamps_inverted_range_to_fallback(self) -> None:
        # A stale finished_at in the future would invert the range; clamp to the fallback window.
        now = datetime(2026, 6, 29, 16, 0, tzinfo=UTC)
        last = datetime(2026, 6, 30, 16, 0, tzinfo=UTC)

        window = compute_report_window(self._team(), last_successful_delivery_at=last, now=now, window_days=1)

        assert window.start == now - timedelta(days=1)
        assert window.end == now

    def test_naive_inputs_assumed_utc(self) -> None:
        now = datetime(2026, 6, 29, 16, 0)
        last = datetime(2026, 6, 28, 16, 0)

        window = compute_report_window(self._team("UTC"), last_successful_delivery_at=last, now=now, window_days=1)

        assert window.start == datetime(2026, 6, 28, 16, 0, tzinfo=UTC)
        assert window.end == datetime(2026, 6, 29, 16, 0, tzinfo=UTC)


class TestContextBlob(APIBaseTest):
    @patch(f"{_SG}.get_group_types_for_project", return_value=[])
    @patch(f"{_SG}._top_event_names", return_value=[])
    def test_states_explicit_window_bounds_in_project_timezone(self, _mock_top: object, _mock_groups: object) -> None:
        # The window-text regression: the blob must hand the planner concrete `[start, end)` literals
        # (so it never writes `now() - INTERVAL`), not the old "last N day(s)" relative phrasing.
        self.team.timezone = "Australia/Sydney"
        self.team.save()
        window = compute_report_window(
            self.team,
            last_successful_delivery_at=None,
            now=datetime(2026, 6, 29, 16, 0, tzinfo=UTC),
            window_days=1,
        )

        blob = build_context_blob(self.team, window)

        assert f"Analysis window start (inclusive, project timezone): {window.start_literal}" in blob
        assert f"Analysis window end (exclusive, project timezone): {window.end_literal}" in blob
        assert (
            f"timestamp >= toDateTime('{window.start_literal}') AND timestamp < toDateTime('{window.end_literal}')"
            in blob
        )
        # The relative "last N day(s)" phrasing the planner used to do tz math against is gone.
        assert "Suggested analysis window" not in blob
        assert "Current UTC time" not in blob

    @patch(f"{_SG}.get_group_types_for_project", return_value=[{"group_type": "organization", "group_type_index": 0}])
    @patch(f"{_SG}._top_event_names", return_value=[])
    def test_includes_no_data_person_and_group_lines(self, _mock_top: object, _mock_groups: object) -> None:
        now = datetime.now(tz=UTC)
        EventDefinition.objects.create(team=self.team, name="dormant_event", last_seen_at=now - timedelta(days=30))
        PropertyDefinition.objects.create(team=self.team, name="plan", type=PropertyDefinition.Type.PERSON)

        blob = build_context_blob(self.team, _window(7))

        assert "Events defined but with no data since the window start:" in blob
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

        blob = build_context_blob(self.team, _window(7), relevant_events=["export created"])

        assert "Events matching your request: export created" in blob
        # properties are listed alphabetically (the _event_property_names ordering)
        assert f"`export created` properties (use properties.<name>): {expected_list}" in blob

    @patch(f"{_SG}.get_group_types_for_project", return_value=[])
    @patch(f"{_SG}._top_event_names", return_value=["$pageview"])
    def test_injects_property_schema_for_selected_top_event(self, _mock_top: object, _mock_groups: object) -> None:
        EventProperty.objects.create(team=self.team, event="$pageview", property="$browser")

        blob = build_context_blob(self.team, _window(7), relevant_events=["$pageview"])

        # $pageview is already under "Top events", so it's not repeated in the matched-names line...
        assert "Events matching your request" not in blob
        # ...but its property schema must still be surfaced (otherwise the planner can't see $browser).
        assert "`$pageview` properties (use properties.<name>): $browser" in blob

    @patch(f"{_SG}.get_group_types_for_project", return_value=[])
    @patch(f"{_SG}._top_event_names", return_value=[])
    def test_omits_relevant_section_without_selected_events(self, _mock_top: object, _mock_groups: object) -> None:
        blob = build_context_blob(self.team, _window(7))

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
