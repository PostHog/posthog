import os
from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from posthog.schema import DateRange

from products.marketing_analytics.backend.max_tools import (
    MAX_LOOKBACK_DAYS,
    MarketingAuditUtmTool,
    MarketingDiagnoseSetupTool,
    MarketingExplainConversionGoalTool,
    MarketingListConversionGoalsTool,
    MarketingListDataSourcesTool,
    MarketingSuggestConversionGoalsTool,
    MarketingSuggestUtmMappingsTool,
    _format_audit_utm_for_llm,
    _format_conversion_goals_for_llm,
    _format_data_sources_for_llm,
    _format_diagnostic_for_llm,
    _format_event_suggestions_for_llm,
    _format_explain_goal_for_llm,
    _format_goal_line,
    _format_timestamp_for_llm,
    _format_utm_mapping_suggestions_for_llm,
    _lookback_days_from_date_range,
    _resolve_lookback_days,
    _sanitize_for_prompt,
)
from products.marketing_analytics.backend.services.conversion_goals_inspector import (
    ConversionGoalsListResponse,
    ConversionGoalSummary,
    GoalEventSample,
    GoalExplanation,
)
from products.marketing_analytics.backend.services.data_source_health import (
    DataSourceHealthEntry,
    DataSourceHealthResponse,
    RequiredTableStatus,
)
from products.marketing_analytics.backend.services.event_suggestions import CandidateEvent, EventSuggestionsResponse
from products.marketing_analytics.backend.services.mapping_suggester import (
    CatalogueEntry,
    CurrentMapping,
    RawUnmatchedSample,
    SourceMappingSuggestion,
    UtmMappingSuggestionsResponse,
)
from products.marketing_analytics.backend.services.marketing_diagnostic import (
    IntegrationDiagnostic,
    MarketingDiagnosticResponse,
    RecommendedAction,
)
from products.marketing_analytics.backend.services.types import (
    CampaignAuditResult,
    UtmAuditResponse,
    UtmEvent,
    UtmIssue,
    UtmIssueKind,
    UtmIssueSeverity,
)


def _make_config(team, user, contextual_tools=None):
    configurable = {"team": team, "user": user}
    if contextual_tools is not None:
        configurable["contextual_tools"] = contextual_tools
    return RunnableConfig(configurable=configurable)


def _make_tool(cls, team, user, contextual_tools=None):
    return cls(team=team, user=user, config=_make_config(team, user, contextual_tools))


def _make_data_source_entry(
    *,
    source_type="GoogleAds",
    display_name="Google Ads",
    connected=True,
    last_sync_at=None,
    last_sync_status="ok",
    last_error=None,
    rows_last_24h=100,
    rows_last_7d=700,
    schema_columns_required_missing=None,
    required_tables=None,
    settings_url="/settings/environment-marketing-analytics#marketing-settings",
    schemas_url=None,
    diagnosis="All good",
    fix_suggestion=None,
):
    return DataSourceHealthEntry(
        source_type=source_type,
        is_native=True,
        display_name=display_name,
        connected=connected,
        last_sync_at=last_sync_at,
        last_sync_status=last_sync_status,
        last_error=last_error,
        rows_last_24h=rows_last_24h,
        rows_last_7d=rows_last_7d,
        sources_map_present=True,
        schema_columns_mapped=[],
        schema_columns_required_missing=schema_columns_required_missing or [],
        required_tables=required_tables or [],
        settings_url=settings_url,
        schemas_url=schemas_url,
        diagnosis=diagnosis,
        fix_suggestion=fix_suggestion,
    )


def _make_goal_summary(
    *,
    id="goal-1",
    name="Purchase",
    kind="EventsNode",
    target_label="purchase",
    last_30d_count=150,
    integrated_count=100,
    events_without_utm_source=30,
    events_with_unmatched_utm_source=20,
    non_integrated_count=50,
    integrated_pct=66.7,
    is_misconfigured=False,
    misconfig_reason=None,
):
    return ConversionGoalSummary(
        id=id,
        name=name,
        kind=kind,
        target_label=target_label,
        last_30d_count=last_30d_count,
        integrated_count=integrated_count,
        events_without_utm_source=events_without_utm_source,
        events_with_unmatched_utm_source=events_with_unmatched_utm_source,
        non_integrated_count=non_integrated_count,
        integrated_pct=integrated_pct,
        is_misconfigured=is_misconfigured,
        misconfig_reason=misconfig_reason,
    )


class TestSanitizeForPrompt(BaseTest):
    @parameterized.expand(
        [
            ("newline_to_space", "google\nads", "google ads"),
            ("carriage_return_to_space", "google\rads", "google ads"),
            ("tab_to_space", "google\tads", "google ads"),
            ("null_byte_removed", "google\x00ads", "googleads"),
            ("del_char_removed", "google\x7fads", "googleads"),
            ("mixed_whitespace_collapsed", "a\nb\tc\rd", "a b c d"),
            ("clean_value_passthrough", "GoogleAds", "GoogleAds"),
            ("system_marker_stripped", "<system>foo</system>", "foo"),
            ("nested_marker_stripped", "<<system>system>foo", "foo"),
            ("html_tag_stripped", "<script>alert(1)</script>", "alert(1)"),
            ("whitespace_run_collapsed", "spaces    here", "spaces here"),
        ]
    )
    def test_sanitizes(self, _name, value, expected):
        assert _sanitize_for_prompt(value) == expected

    def test_truncates_long_value_with_ellipsis_marker(self):
        result = _sanitize_for_prompt("a" * 1000)
        assert result == "a" * 200 + "…"

    def test_short_value_not_truncated(self):
        result = _sanitize_for_prompt("short", max_len=100)
        assert result == "short"
        assert "…" not in result

    def test_custom_max_len_honoured(self):
        result = _sanitize_for_prompt("a" * 20, max_len=10)
        assert result == "a" * 10 + "…"

    def test_none_returns_placeholder(self):
        assert _sanitize_for_prompt(None) == "<none>"

    def test_empty_string_returns_placeholder(self):
        assert _sanitize_for_prompt("") == "<none>"
        assert _sanitize_for_prompt("   ") == "<none>"

    def test_value_that_becomes_empty_after_stripping_returns_placeholder(self):
        assert _sanitize_for_prompt("<system></system>") == "<none>"

    def test_non_string_value_coerced(self):
        assert _sanitize_for_prompt(42) == "42"
        assert _sanitize_for_prompt(3.14) == "3.14"

    def test_unicode_visible_chars_preserved(self):
        assert _sanitize_for_prompt("café 🚀") == "café 🚀"

    def test_invisible_unicode_stripped(self):
        # Zero-width joiner + variation selector — common smuggling vectors.
        result = _sanitize_for_prompt("a​b️c")
        assert result == "abc"


@freeze_time("2025-06-15")
class TestFormatTimestampForLlm(BaseTest):
    @parameterized.expand(
        [
            ("none_returns_never", None, "never"),
            ("future_date_mentions_future", datetime(2099, 1, 1, tzinfo=UTC), "future"),
        ]
    )
    def test_timestamp_variants(self, _name, dt, expected_substring):
        result = _format_timestamp_for_llm(dt)
        assert expected_substring in result

    def test_past_date_contains_days_ago(self):
        past = datetime.now(tz=UTC) - timedelta(days=5)
        result = _format_timestamp_for_llm(past)
        assert "days ago" in result
        assert past.strftime("%Y-%m-%d") in result

    def test_today_contains_today(self):
        from django.utils import timezone

        today = timezone.now()
        result = _format_timestamp_for_llm(today)
        assert "today" in result


class TestLookbackDaysFromDateRange(BaseTest):
    def test_none_date_range_returns_none(self):
        result = _lookback_days_from_date_range(self.team, None)
        assert result is None

    def test_non_dict_date_range_returns_none(self):
        result = _lookback_days_from_date_range(self.team, "not_a_dict")  # type: ignore[arg-type]
        assert result is None

    def test_empty_dict_returns_none(self):
        result = _lookback_days_from_date_range(self.team, {})
        assert result is None

    def test_invalid_date_string_returns_none(self):
        result = _lookback_days_from_date_range(self.team, {"date_from": "not-a-date"})
        assert result is None

    def test_relative_range_returns_positive_integer(self):
        result = _lookback_days_from_date_range(self.team, {"date_from": "-30d"})
        assert result is not None
        assert result > 0

    @parameterized.expand(
        [
            ("30d_relative", {"date_from": "-30d"}, 29, 31),
            ("7d_relative", {"date_from": "-7d"}, 6, 8),
        ]
    )
    def test_relative_range_approximate_days(self, _name, date_range, min_days, max_days):
        result = _lookback_days_from_date_range(self.team, date_range)
        assert result is not None
        assert min_days <= result <= max_days


class TestResolveLookbackDays(BaseTest):
    def test_explicit_value_takes_precedence(self):
        result = _resolve_lookback_days(self.team, {"current_date_range": {"date_from": "-30d"}}, 15, 7)
        assert result == 15

    def test_inferred_from_context_used_when_no_explicit(self):
        result = _resolve_lookback_days(self.team, {"current_date_range": {"date_from": "-30d"}}, None, 7)
        assert result > 7

    def test_fallback_used_when_no_explicit_or_context(self):
        result = _resolve_lookback_days(self.team, {}, None, 90)
        assert result == 90

    @parameterized.expand(
        [
            ("explicit_over_limit", 500, {}, 7),
            ("fallback_over_limit", None, {}, 500),
            ("inferred_over_limit_via_very_long_range", None, {"current_date_range": {"date_from": "-2000d"}}, 7),
        ]
    )
    def test_result_always_clamped_to_max_lookback(self, _name, requested, context, fallback):
        result = _resolve_lookback_days(self.team, context, requested, fallback)
        assert result <= MAX_LOOKBACK_DAYS

    def test_zero_requested_falls_through_to_context(self):
        result = _resolve_lookback_days(self.team, {}, 0, 90)
        assert result == 90

    def test_negative_requested_falls_through_to_context(self):
        result = _resolve_lookback_days(self.team, {}, -5, 90)
        assert result == 90


@freeze_time("2025-06-15")
class TestFormatDiagnosticForLlm(BaseTest):
    def _make_minimal_response(self, *, overall_status="healthy", summary="All good"):
        return MarketingDiagnosticResponse(
            integrations=[],
            overall_status=overall_status,
            summary=summary,
            conversion_goals=None,
            recommended_actions=[],
        )

    def test_contains_overall_status_and_summary(self):
        response = self._make_minimal_response(overall_status="degraded", summary="One integration has problems.")
        result = _format_diagnostic_for_llm(response)
        assert "degraded" in result
        assert "One integration has problems." in result

    def test_does_not_emit_bare_matched_pct_percentage(self):
        from products.marketing_analytics.backend.services.attribution_health import AttributionHealthEntry

        attr = AttributionHealthEntry(
            integration_key="google_ads",
            display_name="Google Ads",
            events_with_utm_last_7d=1000,
            events_matched_last_7d=750,
            events_unmatched_likely_yours_last_7d=0,
            last_event_with_matching_utm_at=None,
            matched_pct=75.0,
            sample_unmatched_utm_sources=[],
        )
        integration = IntegrationDiagnostic(
            integration_key="google_ads",
            source_type="GoogleAds",
            display_name="Google Ads",
            overall_status="healthy",
            diagnosis="All good",
            data_source=None,
            attribution=attr,
            recommended_actions=[],
        )
        response = MarketingDiagnosticResponse(
            integrations=[integration],
            overall_status="healthy",
            summary="Healthy",
            conversion_goals=None,
            recommended_actions=[],
        )
        result = _format_diagnostic_for_llm(response)
        # Must contain denominator phrasing — "matched N of M team events-with-utm_source"
        assert "matched 750 of 1000 team events-with-utm_source" in result
        # Must NOT emit a bare "matched_pct=75%"-only string without the denominator context
        assert "matched_pct=75.0%" not in result or "of" in result

    def test_timestamp_displayed_as_formatted_string_not_raw_datetime(self):
        from django.utils import timezone

        sync_time = timezone.now() - timedelta(days=2)
        ds = _make_data_source_entry(last_sync_at=sync_time)
        integration = IntegrationDiagnostic(
            integration_key="google_ads",
            source_type="GoogleAds",
            display_name="Google Ads",
            overall_status="healthy",
            diagnosis="All good",
            data_source=ds,
            attribution=None,
            recommended_actions=[],
        )
        response = MarketingDiagnosticResponse(
            integrations=[integration],
            overall_status="healthy",
            summary="Healthy",
            conversion_goals=None,
            recommended_actions=[],
        )
        result = _format_diagnostic_for_llm(response)
        assert "days ago" in result

    def test_recommended_actions_included(self):
        response = self._make_minimal_response()
        response.recommended_actions = [
            RecommendedAction(title="Fix sync", detail="Reconnect.", severity="error", target_tool=None)
        ]
        result = _format_diagnostic_for_llm(response)
        assert "Fix sync" in result

    def test_conversion_goals_section_present_when_provided(self):
        goals_resp = ConversionGoalsListResponse(
            goals=[_make_goal_summary()],
            attribution_window_days=30,
            attribution_mode="last_touch",
            has_misconfigured=False,
        )
        response = self._make_minimal_response()
        response.conversion_goals = goals_resp
        result = _format_diagnostic_for_llm(response)
        assert "Conversion goals" in result
        assert "Purchase" in result


class TestFormatConversionGoalsForLlm(BaseTest):
    def test_empty_goals_returns_no_goals_message(self):
        response = ConversionGoalsListResponse(
            goals=[],
            attribution_window_days=30,
            attribution_mode="last_touch",
            has_misconfigured=False,
        )
        result = _format_conversion_goals_for_llm(response)
        assert result == "No conversion goals are configured for this project."

    def test_populated_goals_includes_goal_names(self):
        response = ConversionGoalsListResponse(
            goals=[_make_goal_summary(name="Signup"), _make_goal_summary(id="goal-2", name="Purchase")],
            attribution_window_days=30,
            attribution_mode="last_touch",
            has_misconfigured=False,
        )
        result = _format_conversion_goals_for_llm(response)
        assert "Signup" in result
        assert "Purchase" in result

    def test_populated_goals_includes_non_integrated_split_instructions(self):
        response = ConversionGoalsListResponse(
            goals=[_make_goal_summary()],
            attribution_window_days=30,
            attribution_mode="last_touch",
            has_misconfigured=False,
        )
        result = _format_conversion_goals_for_llm(response)
        assert "non_integrated_count" in result
        assert "events_without_utm_source" in result
        assert "events_with_unmatched_utm_source" in result

    def test_includes_attribution_mode_and_window(self):
        response = ConversionGoalsListResponse(
            goals=[_make_goal_summary()],
            attribution_window_days=14,
            attribution_mode="first_touch",
            has_misconfigured=False,
        )
        result = _format_conversion_goals_for_llm(response)
        assert "first_touch" in result
        assert "14" in result


class TestFormatGoalLine(BaseTest):
    def test_includes_goal_name_and_kind(self):
        goal = _make_goal_summary(name="Signup", kind="EventsNode")
        result = _format_goal_line(goal)
        assert "Signup" in result
        assert "EventsNode" in result

    def test_include_id_prepends_id(self):
        goal = _make_goal_summary(id="abc-123")
        result = _format_goal_line(goal, include_id=True)
        assert "abc-123" in result

    def test_misconfigured_flag_shown(self):
        goal = _make_goal_summary(is_misconfigured=True, misconfig_reason="Action not found")
        result = _format_goal_line(goal)
        assert "MISCONFIGURED" in result
        assert "Action not found" in result

    def test_integrated_split_shown(self):
        goal = _make_goal_summary(integrated_count=100, non_integrated_count=50)
        result = _format_goal_line(goal)
        assert "integrated=100" in result
        assert "non_integrated=50" in result


@freeze_time("2025-06-15")
class TestFormatDataSourcesForLlm(BaseTest):
    def test_not_connected_shows_in_output(self):
        entry = _make_data_source_entry(
            display_name="Meta Ads",
            connected=False,
            last_sync_status="not_connected",
        )
        response = DataSourceHealthResponse(
            integrations=[entry],
            has_any_data=False,
            overall_status="no_sources",
            issues_summary=[],
        )
        result = _format_data_sources_for_llm(response)
        assert "Meta Ads" in result
        assert "not connected" in result

    def test_connected_entry_shows_sync_status_and_timestamp(self):
        from django.utils import timezone

        sync_at = timezone.now() - timedelta(days=1)
        entry = _make_data_source_entry(
            display_name="Google Ads",
            connected=True,
            last_sync_at=sync_at,
            last_sync_status="ok",
        )
        response = DataSourceHealthResponse(
            integrations=[entry],
            has_any_data=True,
            overall_status="healthy",
            issues_summary=[],
        )
        result = _format_data_sources_for_llm(response)
        assert "Google Ads" in result
        assert "ok" in result
        assert "1 day ago" in result

    def test_required_tables_shown(self):
        table = RequiredTableStatus(
            table_name="ads_report",
            present=True,
            should_sync=True,
            status="Completed",
            last_synced_at=None,
        )
        entry = _make_data_source_entry(required_tables=[table])
        response = DataSourceHealthResponse(
            integrations=[entry],
            has_any_data=True,
            overall_status="healthy",
            issues_summary=[],
        )
        result = _format_data_sources_for_llm(response)
        assert "ads_report" in result

    def test_issues_summary_appended(self):
        entry = _make_data_source_entry()
        response = DataSourceHealthResponse(
            integrations=[entry],
            has_any_data=True,
            overall_status="degraded",
            issues_summary=["Google Ads schema is missing cost_micros column."],
        )
        result = _format_data_sources_for_llm(response)
        assert "cost_micros" in result


class TestFormatExplainGoalForLlm(BaseTest):
    def _make_explanation(self, *, kind="EventsNode", total_count=200):
        return GoalExplanation(
            goal_id="goal-1",
            goal_name="Signup",
            kind=kind,
            period=DateRange(date_from="2025-04-01", date_to="2025-05-01"),
            total_count=total_count,
            integrated_count=150,
            events_without_utm_source=30,
            events_with_unmatched_utm_source=20,
            non_integrated_count=50,
            by_event=[("user signed up", 200)],
            by_utm_source=[("google", 150)],
            by_matched_integration=[("GoogleAds", 150)],
            samples=[
                GoalEventSample(
                    event_uuid="uuid-1",
                    timestamp=datetime(2025, 4, 15, tzinfo=UTC),
                    distinct_id="user-1",
                    utm_source="google",
                    utm_campaign="brand",
                    matched_integration="GoogleAds",
                )
            ],
            notes=["This is a flat breakdown."],
        )

    def test_contains_goal_name_and_total(self):
        result = _format_explain_goal_for_llm(self._make_explanation())
        assert "Signup" in result
        assert "200" in result

    def test_utm_source_breakdown_present(self):
        result = _format_explain_goal_for_llm(self._make_explanation())
        assert "google" in result

    def test_integration_split_present(self):
        result = _format_explain_goal_for_llm(self._make_explanation())
        assert "GoogleAds" in result

    def test_non_integrated_split_instructions_included_when_split_available(self):
        result = _format_explain_goal_for_llm(self._make_explanation())
        assert "non_integrated_count" in result

    def test_notes_included(self):
        result = _format_explain_goal_for_llm(self._make_explanation())
        assert "flat breakdown" in result


class TestFormatAuditUtmForLlm(BaseTest):
    def _make_response(self, *, campaigns_with_issues=0, results=None, all_utm_events=None):
        return UtmAuditResponse(
            total_campaigns=5,
            campaigns_with_issues=campaigns_with_issues,
            campaigns_without_issues=5 - campaigns_with_issues,
            total_spend_at_risk=0.0,
            results=results or [],
            all_utm_events=all_utm_events or [],
        )

    def test_summary_line_present(self):
        response = self._make_response(campaigns_with_issues=2)
        result = _format_audit_utm_for_llm(response)
        assert "2 of 5 campaigns have issues" in result

    def test_campaigns_with_issues_shown(self):
        issue = UtmIssue(
            field="utm_source",
            severity=UtmIssueSeverity.ERROR,
            kind=UtmIssueKind.NOT_LINKED,
            message="Campaign not linked",
        )
        campaign = CampaignAuditResult(
            campaign_name="brand_campaign",
            campaign_id="camp-1",
            source_name="google",
            spend=100.0,
            clicks=50,
            impressions=500,
            has_utm_events=False,
            event_count=0,
            issues=[issue],
        )
        response = self._make_response(campaigns_with_issues=1, results=[campaign])
        result = _format_audit_utm_for_llm(response)
        assert "brand_campaign" in result
        assert "Campaign not linked" in result

    def test_unmatched_utm_events_shown(self):
        event = UtmEvent(
            utm_campaign="summer_sale",
            utm_source="unknown_source",
            event_count=10,
            campaign_match="none",
            source_match="none",
            matched_campaign=None,
        )
        response = self._make_response(all_utm_events=[event])
        result = _format_audit_utm_for_llm(response)
        assert "unknown_source" in result


class TestFormatEventSuggestionsForLlm(BaseTest):
    def test_empty_candidates_returns_no_candidates_message(self):
        response = EventSuggestionsResponse(candidates=[], lookback_days=30)
        result = _format_event_suggestions_for_llm(response)
        assert "No suitable candidate events found" in result

    def test_populated_candidates_shows_event_names(self):
        candidate = CandidateEvent(
            event_name="user_signed_up",
            last_30d_count=500,
            distinct_users_30d=480,
            pct_with_utm_source=60.0,
            pct_with_utm_campaign=55.0,
            top_utm_sources=[("google", 300), ("facebook", 100)],
            is_already_a_goal=False,
            suggestion_score=0.88,
            suggestion_reason="High volume with good UTM coverage.",
        )
        response = EventSuggestionsResponse(candidates=[candidate], lookback_days=30)
        result = _format_event_suggestions_for_llm(response)
        assert "user_signed_up" in result
        assert "500" in result
        assert "High volume with good UTM coverage." in result

    def test_already_a_goal_flag_shown(self):
        candidate = CandidateEvent(
            event_name="purchase",
            last_30d_count=100,
            distinct_users_30d=90,
            pct_with_utm_source=50.0,
            pct_with_utm_campaign=40.0,
            top_utm_sources=[],
            is_already_a_goal=True,
            suggestion_score=0.5,
            suggestion_reason="Already configured.",
        )
        response = EventSuggestionsResponse(candidates=[candidate], lookback_days=30)
        result = _format_event_suggestions_for_llm(response)
        assert "already a goal" in result


class TestFormatUtmMappingSuggestionsForLlm(BaseTest):
    def _make_empty_response(self):
        return UtmMappingSuggestionsResponse(
            lookback_days_used=90,
            total_events_with_utm_in_window=0,
            total_unmatched_events_in_window=0,
        )

    def test_lookback_window_in_output(self):
        result = _format_utm_mapping_suggestions_for_llm(self._make_empty_response())
        assert "90" in result

    def test_full_catalogue_shown(self):
        entry = CatalogueEntry(
            raw_utm_source="google",
            event_count=500,
            matched_integration="google_ads",
            matched_integration_display_name="Google Ads",
            suggested_integration=None,
        )
        response = self._make_empty_response()
        response.full_utm_source_catalogue = [entry]
        result = _format_utm_mapping_suggestions_for_llm(response)
        assert "google" in result
        assert "Google Ads" in result

    def test_suggestions_shown(self):
        suggestion = SourceMappingSuggestion(
            raw_utm_source="facebook_paid",
            suggested_target="meta_ads",
            suggested_target_display_name="Meta Ads",
            reason="'facebook_paid' contains a known alias of Meta Ads.",
            event_count_30d=200,
        )
        response = self._make_empty_response()
        response.source_suggestions = [suggestion]
        result = _format_utm_mapping_suggestions_for_llm(response)
        assert "facebook_paid" in result
        assert "Meta Ads" in result

    def test_no_suggestions_shows_none(self):
        result = _format_utm_mapping_suggestions_for_llm(self._make_empty_response())
        assert "none" in result.lower()

    def test_raw_unmatched_samples_shown(self):
        sample = RawUnmatchedSample(
            raw_utm_source="organic",
            event_count=50,
            suggested_integration=None,
        )
        response = self._make_empty_response()
        response.raw_unmatched_samples = [sample]
        result = _format_utm_mapping_suggestions_for_llm(response)
        assert "organic" in result

    def test_current_mappings_shown_grouped_by_target(self):
        mapping = CurrentMapping(
            raw_utm_source="cpc",
            target="google_ads",
            target_display_name="Google Ads",
            source="canonical",
        )
        response = self._make_empty_response()
        response.current_mappings = [mapping]
        result = _format_utm_mapping_suggestions_for_llm(response)
        assert "cpc" in result
        assert "Google Ads" in result

    def test_team_custom_mappings_section_present(self):
        mapping = CurrentMapping(
            raw_utm_source="partner_blog",
            target="google_ads",
            target_display_name="Google Ads",
            source="team_custom",
        )
        response = self._make_empty_response()
        response.current_mappings = [mapping]
        result = _format_utm_mapping_suggestions_for_llm(response)
        assert "Team-custom mappings" in result
        assert "partner_blog" in result


class TestMarketingDiagnoseSetupTool(BaseTest):
    def setUp(self):
        super().setUp()
        os.environ["OPENAI_API_KEY"] = "test-api-key"

    def tearDown(self):
        super().tearDown()
        os.environ.pop("OPENAI_API_KEY", None)

    def _setup_tool(self):
        return _make_tool(MarketingDiagnoseSetupTool, self.team, self.user)

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_returns_string_and_dict(self):
        tool = self._setup_tool()
        mock_response = MarketingDiagnosticResponse(
            integrations=[],
            overall_status="no_sources",
            summary="No sources configured.",
            conversion_goals=None,
            recommended_actions=[],
        )
        with patch(
            "products.marketing_analytics.backend.max_tools.get_marketing_diagnostic",
            new=AsyncMock(return_value=mock_response),
        ):
            content, artifact = await tool._arun_impl()

        assert isinstance(content, str)
        assert isinstance(artifact, dict)
        assert "No sources" in content or "no_sources" in content

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_passes_resolved_lookback_to_service(self):
        tool = self._setup_tool()
        mock_response = MarketingDiagnosticResponse(
            integrations=[],
            overall_status="no_sources",
            summary="",
            conversion_goals=None,
            recommended_actions=[],
        )
        with patch(
            "products.marketing_analytics.backend.max_tools.get_marketing_diagnostic",
            new=AsyncMock(return_value=mock_response),
        ) as mock_svc:
            await tool._arun_impl(attribution_lookback_days=30)

        mock_svc.assert_called_once()
        _args, kwargs = mock_svc.call_args
        assert kwargs["attribution_lookback_days"] == 30

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_explicit_lookback_clamped_to_max(self):
        tool = self._setup_tool()
        mock_response = MarketingDiagnosticResponse(
            integrations=[],
            overall_status="no_sources",
            summary="",
            conversion_goals=None,
            recommended_actions=[],
        )
        with patch(
            "products.marketing_analytics.backend.max_tools.get_marketing_diagnostic",
            new=AsyncMock(return_value=mock_response),
        ) as mock_svc:
            await tool._arun_impl(attribution_lookback_days=1000)

        _args, kwargs = mock_svc.call_args
        assert kwargs["attribution_lookback_days"] <= MAX_LOOKBACK_DAYS


class TestMarketingExplainConversionGoalTool(BaseTest):
    def setUp(self):
        super().setUp()
        os.environ["OPENAI_API_KEY"] = "test-api-key"

    def tearDown(self):
        super().tearDown()
        os.environ.pop("OPENAI_API_KEY", None)

    def _setup_tool(self):
        return _make_tool(MarketingExplainConversionGoalTool, self.team, self.user)

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_success(self):
        tool = self._setup_tool()
        explanation = GoalExplanation(
            goal_id="goal-1",
            goal_name="Signup",
            kind="EventsNode",
            period=DateRange(date_from="2025-04-01", date_to="2025-05-01"),
            total_count=100,
            integrated_count=80,
            events_without_utm_source=10,
            events_with_unmatched_utm_source=10,
            non_integrated_count=20,
            by_event=[("user signed up", 100)],
            by_utm_source=[("google", 80)],
            by_matched_integration=[("GoogleAds", 80)],
            samples=[],
            notes=[],
        )
        with patch(
            "products.marketing_analytics.backend.max_tools.explain_conversion_goal",
            new=AsyncMock(return_value=explanation),
        ):
            content, artifact = await tool._arun_impl(goal_id="goal-1")

        assert isinstance(content, str)
        assert isinstance(artifact, dict)
        assert "Signup" in content

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_value_error_returns_goal_not_found(self):
        tool = self._setup_tool()
        with patch(
            "products.marketing_analytics.backend.max_tools.explain_conversion_goal",
            new=AsyncMock(side_effect=ValueError("Goal 'missing-id' not found")),
        ):
            content, artifact = await tool._arun_impl(goal_id="missing-id")

        assert "Could not explain" in content
        assert artifact["error"] == "goal_not_found"
        assert artifact["goal_id"] == "missing-id"


class TestMarketingListConversionGoalsTool(BaseTest):
    def setUp(self):
        super().setUp()
        os.environ["OPENAI_API_KEY"] = "test-api-key"

    def tearDown(self):
        super().tearDown()
        os.environ.pop("OPENAI_API_KEY", None)

    def _setup_tool(self):
        return _make_tool(MarketingListConversionGoalsTool, self.team, self.user)

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_returns_string_and_dict(self):
        tool = self._setup_tool()
        mock_response = ConversionGoalsListResponse(
            goals=[_make_goal_summary()],
            attribution_window_days=30,
            attribution_mode="last_touch",
            has_misconfigured=False,
        )
        with patch(
            "products.marketing_analytics.backend.max_tools.list_conversion_goals",
            new=AsyncMock(return_value=mock_response),
        ):
            content, artifact = await tool._arun_impl()

        assert isinstance(content, str)
        assert isinstance(artifact, dict)
        assert "Purchase" in content

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_empty_goals_message(self):
        tool = self._setup_tool()
        mock_response = ConversionGoalsListResponse(
            goals=[],
            attribution_window_days=30,
            attribution_mode="last_touch",
            has_misconfigured=False,
        )
        with patch(
            "products.marketing_analytics.backend.max_tools.list_conversion_goals",
            new=AsyncMock(return_value=mock_response),
        ):
            content, artifact = await tool._arun_impl()

        assert "No conversion goals" in content
        assert isinstance(artifact, dict)


class TestMarketingListDataSourcesTool(BaseTest):
    def setUp(self):
        super().setUp()
        os.environ["OPENAI_API_KEY"] = "test-api-key"

    def tearDown(self):
        super().tearDown()
        os.environ.pop("OPENAI_API_KEY", None)

    def _setup_tool(self):
        return _make_tool(MarketingListDataSourcesTool, self.team, self.user)

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_returns_string_and_dict(self):
        tool = self._setup_tool()
        mock_response = DataSourceHealthResponse(
            integrations=[_make_data_source_entry()],
            has_any_data=True,
            overall_status="healthy",
            issues_summary=[],
        )
        with patch(
            "products.marketing_analytics.backend.max_tools.get_data_source_health",
            new=AsyncMock(return_value=mock_response),
        ):
            content, artifact = await tool._arun_impl()

        assert isinstance(content, str)
        assert isinstance(artifact, dict)

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_passes_source_type_filter(self):
        tool = self._setup_tool()
        mock_response = DataSourceHealthResponse(
            integrations=[],
            has_any_data=False,
            overall_status="no_sources",
            issues_summary=[],
        )
        with patch(
            "products.marketing_analytics.backend.max_tools.get_data_source_health",
            new=AsyncMock(return_value=mock_response),
        ) as mock_svc:
            await tool._arun_impl(source_type="GoogleAds")

        mock_svc.assert_called_once()
        _args, kwargs = mock_svc.call_args
        assert kwargs["source_type"] == "GoogleAds"


class TestMarketingAuditUtmTool(BaseTest):
    def setUp(self):
        super().setUp()
        os.environ["OPENAI_API_KEY"] = "test-api-key"

    def tearDown(self):
        super().tearDown()
        os.environ.pop("OPENAI_API_KEY", None)

    def _setup_tool(self):
        return _make_tool(MarketingAuditUtmTool, self.team, self.user)

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_returns_string_and_dict(self):
        tool = self._setup_tool()
        mock_response = UtmAuditResponse(
            total_campaigns=3,
            campaigns_with_issues=1,
            campaigns_without_issues=2,
            total_spend_at_risk=50.0,
            results=[],
            all_utm_events=[],
        )
        with patch(
            "products.marketing_analytics.backend.max_tools.run_utm_audit",
            return_value=mock_response,
        ):
            content, artifact = await tool._arun_impl()

        assert isinstance(content, str)
        assert isinstance(artifact, dict)
        assert "1 of 3" in content


class TestMarketingSuggestConversionGoalsTool(BaseTest):
    def setUp(self):
        super().setUp()
        os.environ["OPENAI_API_KEY"] = "test-api-key"

    def tearDown(self):
        super().tearDown()
        os.environ.pop("OPENAI_API_KEY", None)

    def _setup_tool(self):
        return _make_tool(MarketingSuggestConversionGoalsTool, self.team, self.user)

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_returns_string_and_dict(self):
        tool = self._setup_tool()
        candidate = CandidateEvent(
            event_name="checkout_completed",
            last_30d_count=300,
            distinct_users_30d=280,
            pct_with_utm_source=70.0,
            pct_with_utm_campaign=65.0,
            top_utm_sources=[("google", 200)],
            is_already_a_goal=False,
            suggestion_score=0.92,
            suggestion_reason="High volume and UTM coverage.",
        )
        mock_response = EventSuggestionsResponse(candidates=[candidate], lookback_days=30)
        with patch(
            "products.marketing_analytics.backend.max_tools.suggest_conversion_goals",
            new=AsyncMock(return_value=mock_response),
        ):
            content, artifact = await tool._arun_impl(top_n=5, min_count=30)

        assert isinstance(content, str)
        assert isinstance(artifact, dict)
        assert "checkout_completed" in content

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_passes_top_n_and_min_count(self):
        tool = self._setup_tool()
        mock_response = EventSuggestionsResponse(candidates=[], lookback_days=30)
        with patch(
            "products.marketing_analytics.backend.max_tools.suggest_conversion_goals",
            new=AsyncMock(return_value=mock_response),
        ) as mock_svc:
            await tool._arun_impl(top_n=5, min_count=20)

        mock_svc.assert_called_once()
        _args, kwargs = mock_svc.call_args
        assert kwargs["top_n"] == 5
        assert kwargs["min_count"] == 20


class TestMarketingSuggestUtmMappingsTool(BaseTest):
    def setUp(self):
        super().setUp()
        os.environ["OPENAI_API_KEY"] = "test-api-key"

    def tearDown(self):
        super().tearDown()
        os.environ.pop("OPENAI_API_KEY", None)

    def _setup_tool(self):
        return _make_tool(MarketingSuggestUtmMappingsTool, self.team, self.user)

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_returns_string_and_dict(self):
        tool = self._setup_tool()
        mock_response = UtmMappingSuggestionsResponse(
            lookback_days_used=90,
            total_events_with_utm_in_window=500,
            total_unmatched_events_in_window=50,
        )
        with patch(
            "products.marketing_analytics.backend.max_tools.suggest_utm_mappings",
            new=AsyncMock(return_value=mock_response),
        ):
            content, artifact = await tool._arun_impl()

        assert isinstance(content, str)
        assert isinstance(artifact, dict)
        assert "90" in content

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_explicit_lookback_passed_to_service(self):
        tool = self._setup_tool()
        mock_response = UtmMappingSuggestionsResponse(
            lookback_days_used=60,
            total_events_with_utm_in_window=0,
            total_unmatched_events_in_window=0,
        )
        with patch(
            "products.marketing_analytics.backend.max_tools.suggest_utm_mappings",
            new=AsyncMock(return_value=mock_response),
        ) as mock_svc:
            await tool._arun_impl(lookback_days=60)

        mock_svc.assert_called_once()
        _args, kwargs = mock_svc.call_args
        assert kwargs["lookback_days"] == 60

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_explicit_lookback_clamped_to_max(self):
        tool = self._setup_tool()
        mock_response = UtmMappingSuggestionsResponse(
            lookback_days_used=365,
            total_events_with_utm_in_window=0,
            total_unmatched_events_in_window=0,
        )
        with patch(
            "products.marketing_analytics.backend.max_tools.suggest_utm_mappings",
            new=AsyncMock(return_value=mock_response),
        ) as mock_svc:
            await tool._arun_impl(lookback_days=2000)

        _args, kwargs = mock_svc.call_args
        assert kwargs["lookback_days"] <= MAX_LOOKBACK_DAYS
