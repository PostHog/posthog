from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models import EventDefinition, EventProperty, PropertyDefinition, Team

from products.exports.backend.models.subscription import Subscription
from products.exports.backend.temporal.subscriptions.ai_subscription.schemas import (
    MAX_STEP_HOGQL_LENGTH,
    QueryPlan,
    QueryPlanStep,
    RelevantEvents,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.spec_generator import (
    AI_QUERY_PLAN_VERSION,
    MAX_PINNED_EVENTS,
    PROMPT_MAX_LENGTH,
    RELEVANT_EVENTS_LIMIT,
    PromptRejectedError,
    ReportWindow,
    StoredPlanInvalidError,
    _event_property_names,
    _extract_quoted_event_tokens,
    _group_type_labels,
    _no_data_event_names,
    _person_property_names,
    _pinned_event_names,
    _recent_event_names,
    _select_relevant_events,
    build_context_blob,
    build_frozen_prompt,
    compute_report_window,
    generate_query_plan,
    prettify_hogql,
    sanitize_prompt,
)

_SG = "products.exports.backend.temporal.subscriptions.ai_subscription.spec_generator"


def _window(days: int = 7) -> ReportWindow:
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
        # Dormancy is a fixed NO_DATA_LOOKBACK_DAYS (30) lookback: seen-recently is excluded, older-than
        # the cutoff or never-seen is included. Guards the filter direction and the fixed-lookback choice.
        now = datetime.now(tz=UTC)
        EventDefinition.objects.create(team=self.team, name="recent_event", last_seen_at=now - timedelta(days=1))
        EventDefinition.objects.create(team=self.team, name="dormant_event", last_seen_at=now - timedelta(days=45))
        EventDefinition.objects.create(team=self.team, name="never_seen_event", last_seen_at=None)

        names = _no_data_event_names(self.team, limit=25)

        assert "recent_event" not in names
        assert "dormant_event" in names
        assert "never_seen_event" in names

    def test_respects_limit(self) -> None:
        now = datetime.now(tz=UTC)
        for i in range(5):
            EventDefinition.objects.create(team=self.team, name=f"dormant_{i}", last_seen_at=now - timedelta(days=45))

        assert len(_no_data_event_names(self.team, limit=2)) == 2


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


class TestAIWindowConfigProperties:
    """The ai_prompt_config readers feed compute_report_window on every delivery run, and the column
    is a JSONField a row can carry in any shape — a non-defensive reader would crash the run."""

    @staticmethod
    def _sub(config: object) -> Subscription:
        # In-memory only — the properties are pure reads, but __init__ caches the rrule, so the
        # schedule fields must be valid.
        return Subscription(
            frequency="daily",
            interval=1,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            ai_prompt_config=config,
        )

    @parameterized.expand(
        [
            ("empty", {}, "since_last_sent"),
            ("window_not_a_dict", {"window": "hi"}, "since_last_sent"),
            (
                "garbage_values",
                {"window": {"mode": "bogus", "start_days_ago": "seven", "end_days_ago": True}},
                "since_last_sent",
            ),
            ("none_config", None, "since_last_sent"),
            # Out-of-bounds day values must not survive either: a negative start would push the
            # window's start past its end (a future/inverted range handed to the planner). The valid
            # mode reads through; the day bounds are dropped, so compute degrades to the default window.
            (
                "negative_days",
                {"window": {"mode": "last_n_days", "start_days_ago": -5, "end_days_ago": -1}},
                "last_n_days",
            ),
            (
                # An inverted range would hand the planner a window that ends before it starts.
                "inverted_range",
                {"window": {"mode": "days_ago_range", "start_days_ago": 3, "end_days_ago": 5}},
                "days_ago_range",
            ),
            (
                # Equality is inverted too (>= boundary): a zero-length half-open window is empty.
                "range_zero_length",
                {"window": {"mode": "days_ago_range", "start_days_ago": 3, "end_days_ago": 3}},
                "days_ago_range",
            ),
            (
                "over_max_days",
                {"window": {"mode": "last_n_days", "start_days_ago": 9000, "end_days_ago": 400}},
                "last_n_days",
            ),
        ]
    )
    def test_garbage_config_degrades_to_defaults(self, _name: str, config: object, expected_mode: str) -> None:
        sub = self._sub(config)

        assert sub.ai_window_mode == expected_mode
        assert sub.ai_window_start_days_ago is None
        assert sub.ai_window_end_days_ago is None

    def test_valid_config_is_read_through(self) -> None:
        sub = self._sub({"window": {"mode": "days_ago_range", "start_days_ago": 10, "end_days_ago": 3}})

        assert sub.ai_window_mode == Subscription.AIWindowMode.DAYS_AGO_RANGE
        assert sub.ai_window_start_days_ago == 10
        assert sub.ai_window_end_days_ago == 3

    def test_last_n_days_keeps_start_despite_garbage_end(self) -> None:
        # Normalisation is per-mode: a garbage value in a field the mode ignores must not
        # collateral-null the field it uses.
        sub = self._sub({"window": {"mode": "last_n_days", "start_days_ago": 7, "end_days_ago": 10}})

        assert sub.ai_window_mode == Subscription.AIWindowMode.LAST_N_DAYS
        assert sub.ai_window_start_days_ago == 7
        assert sub.ai_window_end_days_ago is None


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

        window = compute_report_window(
            self._team(),
            last_successful_delivery_at=last,
            now=now,
            window_days=1,
            mode=Subscription.AIWindowMode.SINCE_LAST_SENT,
        )

        # Gap-free: start is exactly the previous send, not now - window_days (which would be identical
        # here, but the next case proves they diverge when the prior send drifted).
        assert window.start == last.astimezone(ZoneInfo("UTC"))
        assert window.end == now.astimezone(ZoneInfo("UTC"))

    def test_since_last_delivery_can_exceed_window_days(self) -> None:
        # A weekly sub (window_days=7) whose prior delivery was 10 days ago must cover the whole gap,
        # not just the last 7 days — proving start follows the delivery, not the cadence default.
        now = datetime(2026, 6, 29, 16, 0, tzinfo=UTC)
        last = datetime(2026, 6, 19, 16, 0, tzinfo=UTC)

        window = compute_report_window(
            self._team(),
            last_successful_delivery_at=last,
            now=now,
            window_days=7,
            mode=Subscription.AIWindowMode.SINCE_LAST_SENT,
        )

        assert window.start == last
        assert (window.end - window.start) == timedelta(days=10)

    def test_compare_start_is_the_equal_length_prior_period(self) -> None:
        # Period-over-period reads back exactly the window's own length before start (not window_days),
        # so a weekly report compares to the prior week and a daily one to the prior day. A 10-day gap
        # against a 7-day cadence proves it tracks the real window, not the default; a sign/length
        # regression here silently compares growth against the wrong baseline.
        now = datetime(2026, 6, 29, 16, 0, tzinfo=UTC)
        last = datetime(2026, 6, 19, 16, 0, tzinfo=UTC)

        window = compute_report_window(
            self._team(),
            last_successful_delivery_at=last,
            now=now,
            window_days=7,
            mode=Subscription.AIWindowMode.SINCE_LAST_SENT,
        )

        assert (window.start - window.compare_start) == (window.end - window.start)
        assert window.compare_start == datetime(2026, 6, 9, 16, 0, tzinfo=UTC)
        assert window.compare_start_literal == "2026-06-09 16:00:00"

    def test_falls_back_to_window_days_without_prior_delivery(self) -> None:
        now = datetime(2026, 6, 29, 16, 0, tzinfo=UTC)

        window = compute_report_window(
            self._team(),
            last_successful_delivery_at=None,
            now=now,
            window_days=7,
            mode=Subscription.AIWindowMode.SINCE_LAST_SENT,
        )

        assert window.end == now
        assert window.start == now - timedelta(days=7)

    def test_last_n_days_is_a_fixed_trailing_window(self) -> None:
        # The day-based mode must ignore the delivery anchor entirely: a recent send must not shrink
        # the window (that send-timing dependence is what the mode exists to opt out of).
        now = datetime(2026, 6, 29, 16, 0, tzinfo=UTC)
        recent_send = datetime(2026, 6, 29, 15, 0, tzinfo=UTC)

        window = compute_report_window(
            self._team(),
            last_successful_delivery_at=recent_send,
            now=now,
            window_days=7,
            mode=Subscription.AIWindowMode.LAST_N_DAYS,
            start_days_ago=3,
        )

        assert window.start == now - timedelta(days=3)
        assert window.end == now

    def test_days_ago_range_is_an_explicit_historical_range(self) -> None:
        now = datetime(2026, 6, 29, 16, 0, tzinfo=UTC)

        window = compute_report_window(
            self._team(),
            last_successful_delivery_at=None,
            now=now,
            window_days=7,
            mode=Subscription.AIWindowMode.DAYS_AGO_RANGE,
            start_days_ago=10,
            end_days_ago=3,
        )

        assert window.start == now - timedelta(days=10)
        assert window.end == now - timedelta(days=3)
        # compare_start stays the equal-length prior period, so period-over-period works here too.
        assert window.compare_start == now - timedelta(days=17)

    def test_range_missing_end_is_treated_as_ending_now(self) -> None:
        # Documented degrade: a DAYS_AGO_RANGE row missing end_days_ago ends at "now" (0 = now per
        # the serializer help text) instead of falling back to a completely different window.
        now = datetime(2026, 6, 29, 16, 0, tzinfo=UTC)

        window = compute_report_window(
            self._team(),
            last_successful_delivery_at=None,
            now=now,
            window_days=7,
            mode=Subscription.AIWindowMode.DAYS_AGO_RANGE,
            start_days_ago=10,
            end_days_ago=None,
        )

        assert window.start == now - timedelta(days=10)
        assert window.end == now

    @parameterized.expand(
        [
            ("last_n_days_missing_start", Subscription.AIWindowMode.LAST_N_DAYS, None, None),
            ("range_missing_start", Subscription.AIWindowMode.DAYS_AGO_RANGE, None, 3),
        ]
    )
    def test_bad_day_mode_config_falls_back_to_trailing_window(
        self, _name: str, mode: str, start_days_ago: int | None, end_days_ago: int | None
    ) -> None:
        # normalize_ai_window nulls out bad day values, so what reaches compute is a day mode with
        # missing values; it must degrade to the cadence trailing window (anchor is None because
        # delivery.py skips the last-delivery lookup for day-based modes).
        now = datetime(2026, 6, 29, 16, 0, tzinfo=UTC)

        window = compute_report_window(
            self._team(),
            last_successful_delivery_at=None,
            now=now,
            window_days=7,
            mode=mode,
            start_days_ago=start_days_ago,
            end_days_ago=end_days_ago,
        )

        assert window.start == now - timedelta(days=7)
        assert window.end == now

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

        window = compute_report_window(
            self._team(),
            last_successful_delivery_at=last,
            now=now,
            window_days=1,
            mode=Subscription.AIWindowMode.SINCE_LAST_SENT,
        )

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
    def test_states_window_bounds_and_placeholder_in_project_timezone(
        self, _mock_top: object, _mock_groups: object
    ) -> None:
        # The blob hands the planner the concrete `[start, end)` bounds for context, but instructs it to
        # filter via the `{{date_range}}` placeholder (the executor substitutes the real window at run
        # time) — never literal dates or the old "last N day(s)" relative phrasing.
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
        # The filter instruction names the placeholder, not the literal bounds — so a frozen plan stays
        # window-agnostic and the dates never get baked into the planner's HogQL.
        assert "{{date_range}}" in blob
        assert f"toDateTime('{window.start_literal}')" not in blob
        assert (
            f"Previous-period start (for period-over-period comparisons only, project timezone): "
            f"{window.compare_start_literal}" in blob
        )
        # The relative "last N day(s)" phrasing the planner used to do tz math against is gone.
        assert "Suggested analysis window" not in blob
        assert "Current UTC time" not in blob

    @patch(f"{_SG}.get_group_types_for_project", return_value=[{"group_type": "organization", "group_type_index": 0}])
    @patch(f"{_SG}._top_event_names", return_value=[])
    def test_includes_no_data_person_and_group_lines(self, _mock_top: object, _mock_groups: object) -> None:
        now = datetime.now(tz=UTC)
        EventDefinition.objects.create(team=self.team, name="dormant_event", last_seen_at=now - timedelta(days=45))
        PropertyDefinition.objects.create(team=self.team, name="plan", type=PropertyDefinition.Type.PERSON)

        blob = build_context_blob(self.team, _window(7))

        assert "Events defined but with no data in the last 30 day(s):" in blob
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


class TestPrettifyHogql:
    """The prettifier reformats LLM SQL that gets frozen and replayed — a corruption here (splitting
    inside a string literal, mangling a window token, dropping a character) silently changes every
    future report's queries, so the dangerous shapes are pinned."""

    @parameterized.expand(
        [
            (
                "single_line_query_splits_clauses_and_columns",
                "SELECT event, count() AS c FROM events WHERE {{date_range}} AND event = 'purchase' "
                "GROUP BY event HAVING c > 0 ORDER BY c DESC LIMIT 50",
                "SELECT event,\n    count() AS c\nFROM events\nWHERE {{date_range}} AND event = 'purchase'\n"
                "GROUP BY event\nHAVING c > 0\nORDER BY c DESC\nLIMIT 50",
            ),
            (
                "keywords_inside_string_literals_untouched",
                "SELECT count() FROM events WHERE properties.msg = 'copy FROM here WHERE possible' AND {{date_range}}",
                "SELECT count()\nFROM events\nWHERE properties.msg = 'copy FROM here WHERE possible' AND {{date_range}}",
            ),
            (
                "subquery_clauses_stay_inline",
                "SELECT c FROM (SELECT count() AS c FROM events WHERE {{date_range}} GROUP BY event) ORDER BY c",
                "SELECT c\nFROM (SELECT count() AS c FROM events WHERE {{date_range}} GROUP BY event)\nORDER BY c",
            ),
            (
                "already_multiline_input_canonicalizes_identically",
                "SELECT event,\n       count() AS c\n  FROM events\n WHERE {{compare_date_range}}",
                "SELECT event,\n    count() AS c\nFROM events\nWHERE {{compare_date_range}}",
            ),
            (
                "commas_inside_function_calls_stay_inline",
                "SELECT concat(event, '-', distinct_id) FROM events WHERE {{window_start}} <= timestamp",
                "SELECT concat(event, '-', distinct_id)\nFROM events\nWHERE {{window_start}} <= timestamp",
            ),
        ]
    )
    def test_reformats_without_corruption(self, _name: str, raw: str, expected: str) -> None:
        assert prettify_hogql(raw) == expected

    def test_falls_back_to_input_when_pretty_form_would_exceed_length_cap(self) -> None:
        # Enough top-level commas that the inserted indentation pushes past the schema's max_length,
        # which would make the frozen plan fail revalidation on reuse. Self-checking: if the pretty
        # form fit the cap, prettify would return it (multi-line) and the equality would fail.
        columns = ", ".join(f"col_{i}" for i in range(490))
        raw = f"SELECT {columns} FROM events WHERE {{{{date_range}}}}"
        assert len(raw) <= MAX_STEP_HOGQL_LENGTH
        assert prettify_hogql(raw) == raw


class TestGenerateQueryPlanSubstitution(APIBaseTest):
    """Test the substitution *behaviour* — that the planner actually receives the prompt and context
    interpolated into the template — rather than asserting prose fragments exist in the prompt string.
    Prompt *quality* (do the guardrails work?) belongs in an LLM eval, not a unit test."""

    @patch(f"{_SG}.MaxChatOpenAI")
    def test_substitutes_prompt_and_context_into_system_message(self, mock_chat: MagicMock) -> None:
        structured = mock_chat.return_value.with_structured_output.return_value
        structured.invoke.return_value = QueryPlan(
            overall_intent="intent",
            steps=[QueryPlanStep(description="d", hogql="SELECT event FROM events WHERE {{date_range}}")],
        )

        plan = generate_query_plan(
            cleaned_prompt="CLEANED_PROMPT_MARKER",
            context_blob="CONTEXT_BLOB_MARKER",
            team=self.team,
            user=self.user,
        )

        # Steps leave the planner in canonical pretty form — this is what gets frozen and executed.
        assert plan.steps[0].hogql == "SELECT event\nFROM events\nWHERE {{date_range}}"

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


class TestBuildFrozenPrompt(APIBaseTest):
    """The deterministic reuse path: reconstruct the spec from a persisted plan with NO LLM calls."""

    def _stored_plan(self) -> dict:
        return {
            "version": AI_QUERY_PLAN_VERSION,
            "plan": QueryPlan(
                overall_intent="count events",
                steps=[QueryPlanStep(description="counts", hogql="SELECT count() FROM events WHERE {{date_range}}")],
            ).model_dump(),
        }

    @patch(f"{_SG}.MaxChatOpenAI")
    @patch(f"{_SG}._select_relevant_events")
    @patch(f"{_SG}.get_group_types_for_project", return_value=[])
    @patch(f"{_SG}._top_event_names", return_value=[])
    def test_reconstructs_plan_without_calling_any_llm(
        self, _mock_top: object, _mock_groups: object, mock_select: MagicMock, mock_chat: MagicMock
    ) -> None:
        stored = self._stored_plan()

        spec = build_frozen_prompt(
            team=self.team, prompt="how are exports doing?", window=_window(7), ai_query_plan=stored
        )

        # Neither the event-selection model nor the planner runs on the frozen path...
        mock_select.assert_not_called()
        mock_chat.assert_not_called()
        # ...and the plan round-trips byte-for-byte (persist shape == reuse shape), HogQL placeholder intact.
        assert spec.plan.model_dump() == stored["plan"]
        assert "{{date_range}}" in spec.plan.steps[0].hogql

    @parameterized.expand(
        [
            # A corrupted plan and a stale schema version both raise StoredPlanInvalidError, NOT
            # PromptRejectedError — the caller self-heals by re-planning live, so neither a QueryPlan
            # schema change nor an AI_QUERY_PLAN_VERSION bump can brick a frozen subscription.
            (
                "malformed_plan",
                {"version": AI_QUERY_PLAN_VERSION, "plan": {"overall_intent": "i", "steps": []}},
                "malformed",
            ),
            ("stale_version", {"version": AI_QUERY_PLAN_VERSION - 1, "plan": {}}, "stale"),
            ("pre_versioning_shape", {"overall_intent": "i", "steps": []}, "stale"),
        ]
    )
    @patch(f"{_SG}.get_group_types_for_project", return_value=[])
    @patch(f"{_SG}._top_event_names", return_value=[])
    def test_invalid_stored_plan_raises_recoverable_error(
        self, _name: str, stored: dict, match: str, _mock_top: object, _mock_groups: object
    ) -> None:
        with pytest.raises(StoredPlanInvalidError, match=match):
            build_frozen_prompt(team=self.team, prompt="p", window=_window(7), ai_query_plan=stored)
