import json
import time
from datetime import UTC, datetime, timedelta
from typing import Literal

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError
from rest_framework import status
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, force_authenticate
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.constants import AvailableFeature
from posthog.models import PropertyDefinition, Team
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.facade.contracts import PropertyAccessLevel
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import CheckResult, Dismissal
from products.signals.backend.enums import SignalSourceProduct, SignalSourceType
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportCheck,
    SignalScoutConfig,
    SignalScoutRun,
)
from products.signals.backend.report_check_agent import (
    AGENT_CHECK_RESULT_WINDOW,
    CHECK_DISPATCH_DEFER_AFTER,
    FALLBACK_CHECK_SKILL_NAME,
    build_check_run_note,
    reactivate_checks_errored_by_scout_pause,
    resolve_check_skill_name,
    run_agent_check,
)
from products.signals.backend.report_check_authoring import (
    CheckCreationError,
    cancel_check,
    create_check,
    create_checks_from_specs,
    replace_metric_check,
)
from products.signals.backend.report_check_execution import (
    CHECK_ERROR_RETRY_AFTER,
    CheckVerdict,
    collect_due_checks,
    evaluate_check_value,
    expire_overdue_checks,
    measure_check,
    record_check_verdict,
    resolve_check_query,
    run_due_report_checks,
)
from products.signals.backend.report_check_research import check_versions
from products.signals.backend.report_check_timing import metric_check_ready_at, metric_check_window_start
from products.signals.backend.report_checks import (
    AWAITING_DATA_RETRY_WAITS,
    DEFAULT_CHECK_EXPIRY_AFTER_LAST_RUN,
    DEFAULT_CHECK_SOAK_HOURS,
    MAX_ACTIVE_CHECKS_PER_REPORT,
    MAX_CHECK_HORIZON,
    MAX_CHECK_INSTRUCTIONS_LENGTH,
    MAX_CHECK_INTERVAL_MINUTES,
    MAX_CHECK_PROBE_HINT_LENGTH,
    MAX_CHECK_PROBE_HINTS,
    MAX_CHECK_RUNS,
    MAX_CHECK_SOAK_HOURS,
    MAX_CONSECUTIVE_CHECK_ERRORS,
    MIN_CHECK_INTERVAL_MINUTES,
    MIN_CHECK_SOAK_HOURS,
    AgentCheckConfig,
    CheckComparison,
    CheckConfigValidationError,
    CheckSpec,
    MetricThresholdConfig,
    parse_check_config,
    validate_metric_check_for_write,
)
from products.signals.backend.report_merge import merge_reports
from products.signals.backend.report_metric_access import ReportMetricAccessPolicy
from products.signals.backend.report_metric_refresh import MetricMeasurement
from products.signals.backend.report_monitoring import resolve_verified_monitoring_report
from products.signals.backend.scout_harness.tools.checks import (
    InvalidCheckResultError,
    InvalidCheckWriteError,
    cancel_report_check,
    create_report_check,
    list_report_checks,
    record_check_result,
)
from products.signals.backend.serializers import CHECK_RESULT_HIDDEN_EXPLANATION, SignalReportCheckWriteSerializer
from products.signals.backend.temporal.emitter import SignalEmitterInput
from products.signals.backend.test.report_metric_test_fixtures import trends_metric_query
from products.signals.backend.views import SignalReportCheckViewSet
from products.skills.backend.models.skills import LLMSkill
from products.tasks.backend.models import Task, TaskRun

_MEASURE = "products.signals.backend.report_check_execution.measure_metric"
_CAPTURE = "products.signals.backend.report_check_telemetry.posthoganalytics.capture"
_DISPATCH = "products.signals.backend.temporal.agentic.scout_scheduler.start_check_signals_scout_run"
_CONNECT = "posthog.temporal.common.client.sync_connect"
_FLAG_PAYLOAD = "products.signals.backend.scout_harness.run_gates._read_flag_payload"
_OTHER_SKILL = "signals-scout-error-tracking"
_EMIT_SIGNAL = "products.signals.backend.facade.api.emit_signal"
_ASYNC_CONNECT = "products.signals.backend.facade.api.async_connect"

_PAGEVIEWS = trends_metric_query(series=[{"kind": "EventsNode", "event": "$pageview"}])


def _threshold_config(**overrides: object) -> dict:
    return {"query": _PAGEVIEWS, "comparison": {"operator": "lte", "value": 10}, **overrides}


class TestCheckComparison(SimpleTestCase):
    @parameterized.expand(
        [
            ("lte_under", {"operator": "lte", "value": 10}, 4.0, "passed"),
            ("lte_on_bound", {"operator": "lte", "value": 10}, 10.0, "passed"),
            ("lte_over", {"operator": "lte", "value": 10}, 11.0, "failed"),
            ("gte_over", {"operator": "gte", "value": 10}, 12.0, "passed"),
            ("gte_on_bound", {"operator": "gte", "value": 10}, 10.0, "passed"),
            ("gte_under", {"operator": "gte", "value": 10}, 9.0, "failed"),
            ("between_inside", {"operator": "between", "bounds": {"lower": 1, "upper": 5}}, 3.0, "passed"),
            ("between_below", {"operator": "between", "bounds": {"lower": 1, "upper": 5}}, 0.5, "failed"),
            ("between_above", {"operator": "between", "bounds": {"lower": 1, "upper": 5}}, 9.0, "failed"),
        ]
    )
    def test_operator_maps_to_the_bound_it_names(self, _name, comparison, observed, expected_outcome) -> None:
        verdict = evaluate_check_value(
            comparison=CheckComparison.model_validate(comparison),
            observed_value=observed,
            subject="Checkout errors",
        )
        assert verdict.outcome == expected_outcome
        assert verdict.observed_value == observed
        assert verdict.explanation.strip()

    @parameterized.expand(
        [
            ("between_without_bounds", {"operator": "between", "value": 3}),
            ("lte_without_value", {"operator": "lte"}),
            ("lte_with_bounds", {"operator": "lte", "bounds": {"lower": 1, "upper": 2}}),
            ("inverted_bounds", {"operator": "between", "bounds": {"lower": 5, "upper": 1}}),
            ("boolean_value", {"operator": "lte", "value": True}),
        ]
    )
    def test_malformed_comparison_is_refused(self, _name, comparison) -> None:
        with self.assertRaises(CheckConfigValidationError):
            parse_check_config("metric_threshold", {"query": _PAGEVIEWS, "comparison": comparison})

    @parameterized.expand(
        [
            ("null_unit", _threshold_config(unit="m\x00s")),
            ("surrogate_unit", _threshold_config(unit="m\ud800s")),
            ("neither_source", {"comparison": {"operator": "lte", "value": 1}}),
            ("empty_metric_id", {"metric_id": "", "comparison": {"operator": "lte", "value": 1}}),
            (
                "unknown_config_key",
                {"query": _PAGEVIEWS, "comparison": {"operator": "lte", "value": 1}, "baselineValue": 3},
            ),
            (
                "unknown_comparison_key",
                {"query": _PAGEVIEWS, "comparison": {"operator": "lte", "value": 1, "tolerance": 2}},
            ),
            (
                "unknown_bounds_key",
                {
                    "query": _PAGEVIEWS,
                    "comparison": {"operator": "between", "bounds": {"lower": 1, "upper": 5, "step": 1}},
                },
            ),
            ("uppercase_metric_id", {"metric_id": "Checkout_Errors", "comparison": {"operator": "lte", "value": 1}}),
            (
                "unbounded_query",
                {
                    "query": trends_metric_query(
                        series=[{"kind": "EventsNode", "event": "$pageview"}], date_from="-400d"
                    ),
                    "comparison": {"operator": "lte", "value": 1},
                },
            ),
        ]
    )
    def test_malformed_metric_threshold_config_is_refused(self, _name, config) -> None:
        with self.assertRaises(CheckConfigValidationError):
            parse_check_config("metric_threshold", config)

    def test_a_padded_metric_reference_is_normalized_so_it_can_still_match(self) -> None:
        config = parse_check_config(
            "metric_threshold", {"metric_id": " checkout-errors ", "comparison": {"operator": "lte", "value": 1}}
        )

        assert isinstance(config, MetricThresholdConfig)
        assert config.metric_id == "checkout-errors"

    def test_unknown_kind_is_refused(self) -> None:
        with self.assertRaises(CheckConfigValidationError):
            parse_check_config("vibes", {"instructions": "look again"})

    @parameterized.expand(
        [
            ("count_query_with_percentage_format", _threshold_config(value_format="percentage_scaled")),
            ("affected_users_with_event_count", _threshold_config(metric_kind="affected_users", value_format="count")),
            ("duration_without_unit", _threshold_config(metric_kind="duration", value_format="duration")),
            (
                "negative_count_goal",
                _threshold_config(value_format="count", comparison={"operator": "lte", "value": -1}),
            ),
            ("fractional_count_baseline", _threshold_config(value_format="count", baseline_value=1.5)),
            (
                "fractional_count_bound",
                _threshold_config(
                    value_format="count", comparison={"operator": "between", "bounds": {"lower": 1, "upper": 2.5}}
                ),
            ),
            (
                "negative_duration_baseline",
                _threshold_config(metric_kind="duration", value_format="duration", unit="s", baseline_value=-1),
            ),
            ("nonfinite_goal", _threshold_config(comparison={"operator": "lte", "value": float("inf")})),
            (
                "nonfinite_bound",
                _threshold_config(comparison={"operator": "between", "bounds": {"lower": 0, "upper": float("inf")}}),
            ),
            (
                "scaled_rate_over_one",
                _threshold_config(
                    metric_kind="error_rate",
                    value_format="percentage_scaled",
                    query={
                        **_PAGEVIEWS,
                        "source": {
                            **_PAGEVIEWS["source"],
                            "trendsFilter": {"formula": "A / B", "aggregationAxisFormat": "percentage_scaled"},
                            "series": _PAGEVIEWS["source"]["series"] * 2,
                        },
                    },
                    comparison={"operator": "lte", "value": 1.1},
                ),
            ),
            (
                "rate_baseline_over_100",
                _threshold_config(
                    metric_kind="conversion_rate",
                    value_format="percentage",
                    query={
                        **_PAGEVIEWS,
                        "source": {
                            **_PAGEVIEWS["source"],
                            "trendsFilter": {"formula": "A / B * 100", "aggregationAxisFormat": "percentage"},
                            "series": _PAGEVIEWS["source"]["series"] * 2,
                        },
                    },
                    baseline_value=101,
                ),
            ),
        ]
    )
    def test_new_numeric_and_display_rules_do_not_reject_legacy_reads(self, _name: str, config: dict) -> None:
        parsed = parse_check_config("metric_threshold", config)
        assert isinstance(parsed, MetricThresholdConfig)
        with self.assertRaises(CheckConfigValidationError):
            validate_metric_check_for_write(parsed)

    @parameterized.expand(
        [
            ("whole_count", "custom", "count", None, 10.0, {}),
            ("nonnegative_duration", "duration", "duration", "ms", 1.5, {}),
            ("negative_custom", "custom", "number", None, -1.5, {}),
            ("negative_revenue", "revenue", "currency", "USD", -1.5, {}),
            (
                "scaled_rate",
                "error_rate",
                "percentage_scaled",
                None,
                1.0,
                {"aggregationAxisFormat": "percentage_scaled"},
            ),
            (
                "percentage_points",
                "conversion_rate",
                "percentage",
                None,
                100.0,
                {"aggregationAxisFormat": "percentage"},
            ),
        ]
    )
    def test_valid_numeric_formats_remain_writable(
        self, _name: str, kind: str, value_format: str, unit: str | None, value: float, trends_filter: dict
    ) -> None:
        query = {**_PAGEVIEWS, "source": {**_PAGEVIEWS["source"], "trendsFilter": trends_filter}}
        config = MetricThresholdConfig.model_validate(
            _threshold_config(
                query=query,
                metric_kind=kind,
                value_format=value_format,
                unit=unit,
                baseline_value=value,
                comparison={"operator": "lte", "value": value},
            )
        )
        validate_metric_check_for_write(config)


class TestMetricCheckTiming(SimpleTestCase):
    @parameterized.expand(
        [
            ("daily_rounding", "UTC", "2026-10-01T12:30:00+00:00", "-13d", False, "2026-10-15T00:00:00+00:00"),
            ("hourly_rounding", "UTC", "2026-10-01T12:30:00+00:00", "-2h", False, "2026-10-01T15:00:00+00:00"),
            ("explicit_time", "UTC", "2026-10-01T12:30:00+00:00", "-13d", True, "2026-10-14T12:30:00+00:00"),
            ("month_end", "UTC", "2026-01-31T00:00:00+00:00", "-1m", False, "2026-03-01T00:00:00+00:00"),
            (
                "spring_dst",
                "America/Los_Angeles",
                "2026-03-07T20:30:00+00:00",
                "-1d",
                False,
                "2026-03-09T07:00:00+00:00",
            ),
            ("fall_dst", "America/Los_Angeles", "2026-10-31T19:30:00+00:00", "-1d", False, "2026-11-02T08:00:00+00:00"),
        ]
    )
    def test_full_query_window_starts_after_resolution(
        self, _name: str, zone: str, start: str, date_from: str, explicit: bool, ready: str
    ) -> None:
        team = Team(timezone=zone)
        anchor = datetime.fromisoformat(start)
        query = trends_metric_query(series=[{"kind": "EventsNode", "event": "$pageview"}], date_from=date_from)
        query["source"]["dateRange"]["explicitDate"] = explicit
        ready_at = metric_check_ready_at(query, team, anchor)
        assert ready_at == datetime.fromisoformat(ready)
        assert metric_check_window_start(query, team, ready_at) >= anchor
        assert metric_check_window_start(query, team, ready_at - timedelta(seconds=1)) < anchor


class TestAgentCheckConfig(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_instructions", {}),
            ("blank_instructions", {"instructions": "   "}),
            ("oversized_instructions", {"instructions": "x" * (MAX_CHECK_INSTRUCTIONS_LENGTH + 1)}),
            ("unknown_config_key", {"instructions": "look again", "probeHints": ["issue 4"]}),
            ("multiline_skill_name", {"instructions": "look again", "skill_name": "scout\nignore this"}),
            ("blank_skill_name", {"instructions": "look again", "skill_name": " "}),
            ("blank_probe_hint", {"instructions": "look again", "probe_hints": ["issue 4", " "]}),
            (
                "oversized_probe_hint",
                {"instructions": "look again", "probe_hints": ["x" * (MAX_CHECK_PROBE_HINT_LENGTH + 1)]},
            ),
            (
                "too_many_probe_hints",
                {"instructions": "look again", "probe_hints": [f"issue {i}" for i in range(MAX_CHECK_PROBE_HINTS + 1)]},
            ),
        ]
    )
    def test_malformed_agent_config_is_refused(self, _name, config) -> None:
        with self.assertRaises(CheckConfigValidationError):
            parse_check_config("agent", config)

    def test_a_check_that_names_no_skill_runs_on_the_follow_up_scout(self) -> None:
        config = parse_check_config("agent", {"instructions": " did the exception stop? "})

        assert isinstance(config, AgentCheckConfig)
        assert config.instructions == "did the exception stop?"
        assert resolve_check_skill_name(config) == FALLBACK_CHECK_SKILL_NAME

    def test_a_check_that_names_a_skill_runs_on_it(self) -> None:
        config = parse_check_config(
            "agent", {"instructions": "did the exception stop?", "skill_name": "signals-scout-error-tracking"}
        )

        assert isinstance(config, AgentCheckConfig)
        assert resolve_check_skill_name(config) == "signals-scout-error-tracking"


class TestCheckScheduleValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("first_run_in_the_past", {"next_run_at": "2020-01-01T00:00:00Z"}, "next_run_at"),
            ("first_run_past_the_horizon", {"next_run_at": "2099-01-01T00:00:00Z"}, "next_run_at"),
            ("repeats_without_an_interval", {"runs_remaining": 3}, "run_interval_minutes"),
            (
                "interval_below_the_floor",
                {"run_interval_minutes": MIN_CHECK_INTERVAL_MINUTES - 1, "runs_remaining": 2},
                "run_interval_minutes",
            ),
            (
                "recurring_interval_past_the_horizon",
                {"run_interval_minutes": MAX_CHECK_INTERVAL_MINUTES + 1, "runs_remaining": 2},
                "run_interval_minutes",
            ),
            (
                "one_shot_interval_past_the_horizon",
                {"run_interval_minutes": 3_000_000_000},
                "run_interval_minutes",
            ),
            ("expiry_before_the_first_run", {"expires_at": "2020-01-01T00:00:00Z"}, "expires_at"),
            (
                "last_run_past_the_horizon",
                {"run_interval_minutes": 30 * 24 * 60, "runs_remaining": 5},
                "run_interval_minutes",
            ),
            ("both_a_metric_and_a_query", {"config": _threshold_config(metric_id="errors")}, "config"),
        ]
    )
    def test_an_impossible_request_is_refused(self, _name, overrides, field) -> None:
        serializer = SignalReportCheckWriteSerializer(
            data={"title": "Errors stay low", "kind": "metric_threshold", "config": _threshold_config(), **overrides}
        )
        assert not serializer.is_valid()
        assert field in serializer.errors

    def test_defaults_fill_in_a_whole_schedule(self) -> None:
        serializer = SignalReportCheckWriteSerializer(
            data={"title": "Errors stay low", "kind": "metric_threshold", "config": _threshold_config()}
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["next_run_at"] > timezone.now()
        assert serializer.validated_data["expires_at"] > serializer.validated_data["next_run_at"]
        assert (
            serializer.validated_data["expires_at"]
            == serializer.validated_data["next_run_at"] + DEFAULT_CHECK_EXPIRY_AFTER_LAST_RUN
        )
        assert serializer.validated_data["runs_remaining"] == 1

    @parameterized.expand(
        [
            ("one_shot_beyond_the_padding", 61, None, 1),
            ("recurring_to_the_run_ceiling", 7, 7 * 24 * 60, MAX_CHECK_RUNS),
        ]
    )
    def test_an_omitted_expiry_never_pushes_a_legal_schedule_past_the_horizon(
        self, _name, first_run_in_days, interval, runs
    ) -> None:
        overrides: dict = {
            "next_run_at": (timezone.now() + timedelta(days=first_run_in_days)).isoformat(),
            "runs_remaining": runs,
        }
        if interval is not None:
            overrides["run_interval_minutes"] = interval

        before = timezone.now()
        serializer = SignalReportCheckWriteSerializer(
            data={"title": "Errors stay low", "kind": "metric_threshold", "config": _threshold_config(), **overrides}
        )
        valid = serializer.is_valid()
        after = timezone.now()

        assert valid, serializer.errors
        assert before + MAX_CHECK_HORIZON <= serializer.validated_data["expires_at"] <= after + MAX_CHECK_HORIZON


class TestReportCheckExecution(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.RESOLVED, title="Fix")

    def _check(self, **overrides) -> SignalReportCheck:
        now = timezone.now()
        fields: dict = {
            "team": self.team,
            "report": self.report,
            "title": "Checkout errors stay low",
            "kind": SignalReportCheck.Kind.METRIC_THRESHOLD,
            "config": _threshold_config(),
            "measurement_start_at": self.report.monitoring_started_at or now - timedelta(days=32),
            "next_run_at": now - timedelta(minutes=1),
            "expires_at": now + timedelta(days=30),
        }
        fields.update(overrides)
        return SignalReportCheck.objects.for_team(self.team.id).create(**fields)

    def _results(self) -> list[SignalReportArtefact]:
        return list(
            SignalReportArtefact.objects.filter(
                report=self.report, type=SignalReportArtefact.ArtefactType.CHECK_RESULT
            ).order_by("created_at")
        )

    @parameterized.expand([("metric", "metric_threshold"), ("agent", "agent")])
    def test_monitoring_resolves_only_after_the_whole_schedule_passes(self, _name: str, kind: str) -> None:
        self.report.status = SignalReport.Status.MONITORING
        self.report.monitoring_started_at = timezone.now()
        self.report.save(update_fields=["status", "monitoring_started_at"])
        check = self._check(
            kind=kind,
            config=_threshold_config() if kind == "metric_threshold" else {"instructions": "Verify the fix."},
            run_interval_minutes=MIN_CHECK_INTERVAL_MINUTES,
            runs_remaining=2,
        )
        other = self._check()
        anchor = check.measurement_start_at
        with patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=False):
            with self.captureOnCommitCallbacks(execute=True):
                record_check_verdict(check, CheckVerdict(outcome="passed", explanation="The check holds."))
            self.report.refresh_from_db()
            self.assertEqual(self.report.status, SignalReport.Status.MONITORING)
            check.refresh_from_db()
            with self.captureOnCommitCallbacks(execute=True):
                record_check_verdict(check, CheckVerdict(outcome="passed", explanation="The check still holds."))
            self.report.refresh_from_db()
            self.assertEqual(self.report.status, SignalReport.Status.MONITORING)
            with self.captureOnCommitCallbacks(execute=True):
                record_check_verdict(other, CheckVerdict(outcome="passed", explanation="The other check holds."))
        self.report.refresh_from_db()
        check.refresh_from_db()
        assert self.report.status == SignalReport.Status.RESOLVED
        assert check.measurement_start_at == anchor

    @parameterized.expand([("failed",), ("errored",), ("inconclusive",)])
    def test_unsuccessful_verification_stays_on_the_monitoring_report(
        self, outcome: Literal["failed", "errored", "inconclusive"]
    ) -> None:
        self.report.status = SignalReport.Status.MONITORING
        self.report.monitoring_started_at = timezone.now()
        self.report.save(update_fields=["status", "monitoring_started_at"])
        check = self._check()
        verdict = CheckVerdict(
            outcome=outcome,
            explanation="The check could not confirm the outcome.",
            reason="unmeasurable" if outcome == "inconclusive" else None,
        )
        with self.captureOnCommitCallbacks(execute=True):
            record_check_verdict(check, verdict)
        self.report.refresh_from_db()
        assert self.report.status == SignalReport.Status.MONITORING
        assert json.loads(self._results()[0].content)["outcome"] == outcome

    def test_touching_an_old_failed_check_does_not_block_the_current_monitoring_period(self) -> None:
        self.report.status = SignalReport.Status.MONITORING
        self.report.monitoring_started_at = timezone.now()
        self.report.save(update_fields=["status", "monitoring_started_at"])
        old = self._check(
            status=SignalReportCheck.Status.FAILED,
            measurement_start_at=timezone.now() - timedelta(days=1),
        )
        old.save(update_fields=["updated_at"])
        current = self._check()
        with self.captureOnCommitCallbacks(execute=True):
            record_check_verdict(current, CheckVerdict(outcome="passed", explanation="The current fix holds."))
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, SignalReport.Status.RESOLVED)

    def test_a_partial_pass_at_the_horizon_does_not_resolve_monitoring(self) -> None:
        self.report.status = SignalReport.Status.MONITORING
        self.report.monitoring_started_at = timezone.now()
        self.report.save(update_fields=["status", "monitoring_started_at"])
        check = self._check(
            runs_remaining=2, run_interval_minutes=MIN_CHECK_INTERVAL_MINUTES, expires_at=timezone.now()
        )
        with self.captureOnCommitCallbacks(execute=True):
            record_check_verdict(check, CheckVerdict(outcome="passed", explanation="One run passed."))
        self.report.refresh_from_db()
        assert self.report.status == SignalReport.Status.MONITORING

    @parameterized.expand(
        [
            ("legacy_without_anchor", None, None, 1),
            ("legacy_recurring_near_expiry", None, 24 * 60, 3),
            ("legacy_recurring_horizon", None, 30 * 24 * 60, 3),
            ("prematurely_due", datetime(2026, 10, 1, 12, tzinfo=UTC), None, 1),
        ]
    )
    def test_incomplete_window_defers_without_a_verdict(
        self, _name: str, anchor: datetime | None, interval: int | None, runs: int
    ) -> None:
        now = datetime(2026, 10, 2, 12, tzinfo=UTC)
        with time_machine.travel(now, tick=False):
            check = self._check(measurement_start_at=anchor, run_interval_minutes=interval, runs_remaining=runs)
            original_expiry = check.expires_at
            with patch(_MEASURE) as measure:
                summary = run_due_report_checks()
            check.refresh_from_db()
            assert not measure.called
            assert summary.passed == summary.failed == summary.inconclusive == summary.errored == 0
            assert self._results() == []
            assert check.measurement_start_at == (anchor or now)
            assert check.next_run_at == metric_check_ready_at(_PAGEVIEWS, self.team, anchor or now)
            assert check.next_run_at < check.expires_at <= now + MAX_CHECK_HORIZON
            if anchor is None:
                last_run_at = check.next_run_at + timedelta(minutes=(interval or 0) * (runs - 1))
                assert check.expires_at == min(
                    last_run_at + DEFAULT_CHECK_EXPIRY_AFTER_LAST_RUN, now + MAX_CHECK_HORIZON
                )
                assert check.expires_at > original_expiry
            else:
                assert check.expires_at == original_expiry
            assert check.consecutive_errors == 0
            assert check.runs_remaining == runs

        with time_machine.travel(check.next_run_at, tick=False):
            with patch(_MEASURE, return_value=MetricMeasurement(value=3, measured_at=check.next_run_at, series=None)):
                summary = run_due_report_checks()
        check.refresh_from_db()
        assert summary.expired == 0
        assert summary.passed == 1
        assert check.runs_remaining == runs - 1
        assert len(self._results()) == 1

    @parameterized.expand(
        [
            ("legacy_window_exceeds_horizon", None, "-90d"),
            ("anchored_deadline_before_window", datetime(2026, 10, 2, 12, tzinfo=UTC), "-30d"),
        ]
    )
    def test_unreachable_window_records_inconclusive(self, _name: str, anchor: datetime | None, date_from: str) -> None:
        now = datetime(2026, 10, 2, 12, tzinfo=UTC)
        with time_machine.travel(now, tick=False):
            check = self._check(
                measurement_start_at=anchor,
                config=_threshold_config(
                    query=trends_metric_query(
                        series=[{"kind": "EventsNode", "event": "$pageview"}], date_from=date_from
                    )
                ),
            )
            original_expiry = check.expires_at
            with patch(_MEASURE) as measure:
                summary = run_due_report_checks()
        check.refresh_from_db()
        assert not measure.called
        assert summary.inconclusive == 1
        assert summary.expired == 0
        assert check.status == SignalReportCheck.Status.INCONCLUSIVE
        assert check.last_outcome_reason == "unmeasurable"
        assert check.expires_at == original_expiry
        assert check.next_run_at < now
        assert len(self._results()) == 1

    def test_a_one_shot_check_that_holds_retires_as_passed_with_a_result(self) -> None:
        check = self._check()
        with patch(_MEASURE, return_value=MetricMeasurement(value=3.0, measured_at=timezone.now(), series=None)):
            summary = run_due_report_checks()

        assert summary.passed == 1
        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.PASSED
        assert check.last_outcome == SignalReportCheck.Outcome.PASSED
        assert check.last_run_at is not None
        results = self._results()
        assert len(results) == 1
        assert '"outcome":"passed"' in results[0].content
        assert '"observed_value":3.0' in results[0].content

    def test_a_recorded_verdict_is_reported_for_adoption(self) -> None:
        self._check()
        with (
            patch(_CAPTURE) as capture,
            patch(_ASYNC_CONNECT, return_value=AsyncMock()),
            patch(_MEASURE, return_value=MetricMeasurement(value=42.0, measured_at=timezone.now(), series=None)),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                run_due_report_checks()

        # Filtered by event rather than counted: `_CAPTURE` patches an attribute on the shared
        # `posthoganalytics` module, so every other capture in the commit — the breach on a resolved
        # report emits a signal, which fires its own — lands on this same mock.
        evaluated = [
            call for call in capture.call_args_list if call.kwargs.get("event") == "signals_report_check_evaluated"
        ]
        assert len(evaluated) == 1
        properties = evaluated[0].kwargs["properties"]
        assert properties["outcome"] == "failed"
        assert properties["check_status"] == SignalReportCheck.Status.FAILED
        assert properties["kind"] == SignalReportCheck.Kind.METRIC_THRESHOLD
        assert properties["metric_source"] == "query"
        assert properties["run_id"] is None

    def test_a_check_that_breaches_retires_as_failed(self) -> None:
        check = self._check()
        with patch(_MEASURE, return_value=MetricMeasurement(value=42.0, measured_at=timezone.now(), series=None)):
            run_due_report_checks()

        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.FAILED
        assert '"outcome":"failed"' in self._results()[0].content

    def test_a_recurring_check_rearms_until_its_runs_are_spent(self) -> None:
        check = self._check(run_interval_minutes=MIN_CHECK_INTERVAL_MINUTES, runs_remaining=2)
        with patch(_MEASURE, return_value=MetricMeasurement(value=1.0, measured_at=timezone.now(), series=None)):
            run_due_report_checks()

        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.ACTIVE
        assert check.runs_remaining == 1
        assert check.next_run_at > timezone.now()

        check.next_run_at = timezone.now() - timedelta(minutes=1)
        check.save(update_fields=["next_run_at"])
        with patch(_MEASURE, return_value=MetricMeasurement(value=1.0, measured_at=timezone.now(), series=None)):
            run_due_report_checks()

        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.PASSED
        assert len(self._results()) == 2

    def test_a_recurring_check_retires_rather_than_running_past_its_horizon(self) -> None:
        check = self._check(
            run_interval_minutes=MIN_CHECK_INTERVAL_MINUTES,
            runs_remaining=2,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        with patch(_MEASURE, return_value=MetricMeasurement(value=1.0, measured_at=timezone.now(), series=None)):
            run_due_report_checks()

        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.PASSED

    def test_a_check_that_cannot_be_measured_retries_then_retires(self) -> None:
        check = self._check()
        for _ in range(MAX_CONSECUTIVE_CHECK_ERRORS):
            check.refresh_from_db()
            check.next_run_at = timezone.now() - timedelta(minutes=1)
            check.save(update_fields=["next_run_at"])
            with patch(_MEASURE, side_effect=ValueError("query returned no series")):
                run_due_report_checks()

        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.ERRORED
        assert len(self._results()) == MAX_CONSECUTIVE_CHECK_ERRORS

    def test_a_single_failure_to_measure_only_delays_the_check(self) -> None:
        check = self._check()
        with patch(_MEASURE, side_effect=ValueError("boom")):
            summary = run_due_report_checks()

        assert summary.errored == 1
        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.ACTIVE
        assert check.consecutive_errors == 1
        assert check.next_run_at >= timezone.now() + CHECK_ERROR_RETRY_AFTER - timedelta(minutes=1)

    def test_a_check_whose_stored_config_stopped_parsing_records_an_errored_run(self) -> None:
        check = self._check()
        # A config that parsed when it was written and no longer does, as a tightened query rule leaves it.
        SignalReportCheck.objects.for_team(self.team.id).filter(id=check.id).update(
            config={"comparison": {"operator": "lte", "value": 10}}
        )

        summary = run_due_report_checks()

        assert summary.errored == 1
        check.refresh_from_db()
        assert check.consecutive_errors == 1
        assert check.next_run_at > timezone.now()
        results = self._results()
        assert len(results) == 1
        assert '"outcome":"errored"' in results[0].content

    def test_an_errored_run_publishes_our_reason_but_not_a_raw_query_error(self) -> None:
        check = self._check()
        with patch(_MEASURE, side_effect=ValueError("metric query returned no series")):
            run_due_report_checks()

        assert "metric query returned no series" in self._results()[0].content

        check.refresh_from_db()
        check.next_run_at = timezone.now() - timedelta(minutes=1)
        check.save(update_fields=["next_run_at"])
        server_error = RuntimeError("DB::Exception: syntax error\nStack trace:\n0. secret internals")
        with patch(_MEASURE, side_effect=server_error):
            run_due_report_checks()

        latest = self._results()[-1].content
        assert '"outcome":"errored"' in latest
        assert "Stack trace" not in latest
        assert "secret internals" not in latest
        # Named like the passed and failed lines, so a report with several checks stays readable.
        assert "Checkout errors stay low could not be measured" in latest

    @parameterized.expand(
        [
            ("reopened", SignalReport.Status.READY),
            ("archived", SignalReport.Status.SUPPRESSED),
            ("awaiting_input", SignalReport.Status.PENDING_INPUT),
        ]
    )
    def test_an_active_check_on_an_unresolved_report_waits_for_the_next_resolve(self, _name, report_status) -> None:
        # An active row on an open report: a report that left `resolved`, or a row written before
        # the create path let the report decide. It must not run, and its old error streak must not
        # count against the soak that follows the next resolve.
        check = self._check(consecutive_errors=MAX_CONSECUTIVE_CHECK_ERRORS - 1)
        self.report.status = report_status
        self.report.save(update_fields=["status"])

        with patch(_MEASURE) as measure:
            summary = run_due_report_checks()

        assert not measure.called
        assert summary.errored == 0
        assert self._results() == []
        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.PENDING
        assert check.consecutive_errors == 0
        assert check.measurement_start_at is None

        before = timezone.now()
        with self.captureOnCommitCallbacks(execute=True):
            self.report.status = SignalReport.Status.RESOLVED
            self.report.save(update_fields=["status"])

        armed = SignalReportCheck.objects.for_team(self.team.id).get(id=check.id)
        assert armed.status == SignalReportCheck.Status.ACTIVE
        assert armed.measurement_start_at is not None
        assert before <= armed.measurement_start_at <= timezone.now()
        assert armed.next_run_at == metric_check_ready_at(_PAGEVIEWS, self.team, armed.measurement_start_at)
        assert armed.next_run_at >= before + timedelta(hours=MIN_CHECK_SOAK_HOURS)
        assert collect_due_checks(timezone.now()) == []

    def test_an_active_check_on_an_unresolved_report_is_never_due(self) -> None:
        self._check()
        self.report.status = SignalReport.Status.READY
        self.report.save(update_fields=["status"])

        assert collect_due_checks(timezone.now()) == []

    @parameterized.expand([("cancelled",), ("reopened",), ("new_monitoring_period",)])
    def test_a_check_invalidated_while_its_query_ran_records_nothing(self, reason: str) -> None:
        check = self._check()
        if reason == "cancelled":
            check.status = SignalReportCheck.Status.CANCELLED
            check.save(update_fields=["status"])
        else:
            self.report.status = SignalReport.Status.READY
            self.report.save(update_fields=["status"])
            if reason == "new_monitoring_period":
                with (
                    patch(
                        "products.signals.backend.report_content_gates.team_report_monitoring_enabled",
                        return_value=True,
                    ),
                    self.captureOnCommitCallbacks(execute=True),
                ):
                    self.report.save(update_fields=self.report.transition_to(SignalReport.Status.MONITORING))

        record_check_verdict(check, CheckVerdict(outcome="passed", explanation="held", observed_value=1.0))

        check.refresh_from_db()
        expected_status = {
            "cancelled": SignalReportCheck.Status.CANCELLED,
            "reopened": SignalReportCheck.Status.PENDING,
            "new_monitoring_period": SignalReportCheck.Status.ACTIVE,
        }[reason]
        assert check.status == expected_status
        assert check.last_run_at is None
        assert self._results() == []
        if reason == "new_monitoring_period":
            assert self.report.monitoring_started_at is not None
            assert check.measurement_start_at == self.report.monitoring_started_at
            assert check.next_run_at == metric_check_ready_at(_PAGEVIEWS, self.team, self.report.monitoring_started_at)

    @parameterized.expand([("no_checks", False), ("cancelled_only", True)])
    def test_monitoring_without_a_successful_check_requires_confirmation(self, _name: str, cancelled: bool) -> None:
        self.report.status = SignalReport.Status.MONITORING
        self.report.monitoring_started_at = timezone.now()
        self.report.save(update_fields=["status", "monitoring_started_at"])
        if cancelled:
            check = self._check()
            with self.captureOnCommitCallbacks(execute=True):
                cancel_check(check, reason="stopped_by_person", attribution=ArtefactAttribution.system())
        assert not resolve_verified_monitoring_report(team_id=self.team.id, report_id=str(self.report.id))
        self.report.refresh_from_db()
        assert self.report.status == SignalReport.Status.MONITORING

    def test_awaiting_data_backs_off_without_spending_the_error_budget_then_ends_inconclusive(self) -> None:
        check = self._check(
            consecutive_errors=MAX_CONSECUTIVE_CHECK_ERRORS - 1, expires_at=timezone.now() + MAX_CHECK_HORIZON
        )
        verdict = CheckVerdict(outcome="inconclusive", reason="awaiting_data", explanation="No deploy since the fix.")
        now = timezone.now()
        for expected_wait in (timedelta(hours=24), timedelta(hours=72), timedelta(days=7)):
            record_check_verdict(check, verdict, now=now)
            check.refresh_from_db()
            assert check.status == SignalReportCheck.Status.ACTIVE
            assert check.next_run_at == now + expected_wait
            assert check.consecutive_errors == MAX_CONSECUTIVE_CHECK_ERRORS - 1
            assert check.runs_remaining == 1
            now = check.next_run_at

        with patch(_CAPTURE) as capture, self.captureOnCommitCallbacks(execute=True):
            record_check_verdict(check, verdict, now=now)

        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.INCONCLUSIVE
        assert check.consecutive_inconclusive == len(AWAITING_DATA_RETRY_WAITS) + 1
        assert check.last_outcome_reason == SignalReportCheck.InconclusiveReason.AWAITING_DATA
        results = self._results()
        assert len(results) == len(AWAITING_DATA_RETRY_WAITS) + 1
        assert json.loads(results[-1].content)["reason"] == "awaiting_data"
        properties = capture.call_args.kwargs["properties"]
        assert properties["outcome"] == "inconclusive"
        assert properties["inconclusive_reason"] == "awaiting_data"
        assert properties["check_status"] == SignalReportCheck.Status.INCONCLUSIVE

    @parameterized.expand(
        [
            ("unmeasurable", "unmeasurable", timedelta(days=30)),
            ("needs_manual_verification", "needs_manual_verification", timedelta(days=30)),
            ("no_fix_to_measure", "no_fix_to_measure", timedelta(days=30)),
            ("awaiting_data_past_the_horizon", "awaiting_data", timedelta(hours=12)),
        ]
    )
    def test_an_inconclusive_verdict_that_waiting_cannot_settle_retires_the_check(
        self, _name, reason, expires_in
    ) -> None:
        check = self._check(expires_at=timezone.now() + expires_in)
        record_check_verdict(
            check, CheckVerdict(outcome="inconclusive", reason=reason, explanation="No denominator event.")
        )

        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.INCONCLUSIVE
        assert check.last_outcome_reason == reason
        assert check.consecutive_errors == 0

    def test_a_verdict_and_its_result_refuse_a_reason_that_does_not_match_the_outcome(self) -> None:
        with self.assertRaises(ValueError):
            CheckVerdict(outcome="inconclusive", explanation="Too few samples.")
        with self.assertRaises(ValueError):
            CheckVerdict(outcome="errored", reason="awaiting_data", explanation="The query failed.")
        with self.assertRaises(PydanticValidationError):
            CheckResult(check_id="c", kind="agent", title="t", outcome="inconclusive", explanation="Too few samples.")

    def test_an_unrun_check_past_its_horizon_expires(self) -> None:
        check = self._check(
            next_run_at=timezone.now() + timedelta(days=1), expires_at=timezone.now() - timedelta(days=1)
        )
        with patch(_CAPTURE) as capture:
            assert expire_overdue_checks(timezone.now()) == 1
        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.EXPIRED
        assert self._results() == []
        assert capture.call_args.kwargs["event"] == "signals_report_checks_expired"
        assert capture.call_args.kwargs["properties"]["never_ran_count"] == 1

    def test_a_check_past_its_horizon_is_not_due_even_when_the_sweep_has_not_reached_it(self) -> None:
        now = timezone.now()
        # The state every check reaches at its horizon: due, still active, and past its expiry.
        self._check(next_run_at=now - timedelta(days=2), expires_at=now - timedelta(days=1))

        assert collect_due_checks(now) == []

    def test_one_team_with_a_backlog_does_not_starve_another_team(self) -> None:
        now = timezone.now()
        for minutes in (30, 20, 10):
            self._check(next_run_at=now - timedelta(minutes=minutes))
        other_team = self.organization.teams.create(name="Other")
        other_report = SignalReport.objects.create(
            team=other_team, status=SignalReport.Status.RESOLVED, title="Other fix"
        )
        other_check = SignalReportCheck.objects.for_team(other_team.id).create(
            team=other_team,
            report=other_report,
            title="Their checkout errors stay low",
            kind=SignalReportCheck.Kind.METRIC_THRESHOLD,
            config=_threshold_config(),
            next_run_at=now - timedelta(minutes=5),
            expires_at=now + timedelta(days=30),
        )

        due = collect_due_checks(now, limit=2)

        assert other_check.id in {check.id for check in due}

    def test_a_check_riding_a_report_metric_measures_that_metric(self) -> None:
        self.report.metrics = [
            {
                "metric_id": "checkout-errors",
                "title": "Checkout errors",
                "kind": "occurrences",
                "query": _PAGEVIEWS,
            }
        ]
        self.report.save(update_fields=["metrics"])
        config = MetricThresholdConfig.model_validate(
            {"metric_id": "checkout-errors", "comparison": {"operator": "lte", "value": 1}}
        )
        assert resolve_check_query(config, self.report) == _PAGEVIEWS

    def test_a_check_riding_a_metric_whose_query_stopped_conforming_errors(self) -> None:
        # The runner reads one series out of the result, so a breakdown would turn an arbitrary
        # slice into a recorded verdict.
        self.report.metrics = [
            {
                "metric_id": "checkout-errors",
                "title": "Checkout errors",
                "kind": "occurrences",
                "query": {
                    **_PAGEVIEWS,
                    "source": {**_PAGEVIEWS["source"], "breakdownFilter": {"breakdown": "$browser"}},
                },
            }
        ]
        self.report.save(update_fields=["metrics"])
        check = self._check(config={"metric_id": "checkout-errors", "comparison": {"operator": "lte", "value": 1}})

        with patch(
            _MEASURE, return_value=MetricMeasurement(value=0.0, measured_at=timezone.now(), series=None)
        ) as measure:
            run_due_report_checks()

        assert not measure.called
        check.refresh_from_db()
        assert check.last_outcome == SignalReportCheck.Outcome.ERRORED
        assert '"outcome":"errored"' in self._results()[0].content

    def test_a_check_riding_a_metric_the_report_dropped_errors_rather_than_crashing(self) -> None:
        check = self._check(config={"metric_id": "gone", "comparison": {"operator": "lte", "value": 1}})
        run_due_report_checks()

        check.refresh_from_db()
        assert check.last_outcome == SignalReportCheck.Outcome.ERRORED
        assert '"outcome":"errored"' in self._results()[0].content


class TestReportCheckAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.RESOLVED, title="Fix")
        self.url = f"/api/projects/{self.team.id}/signals/reports/{self.report.id}/checks/"

    def _create(self, *, report: SignalReport | None = None, **overrides) -> SignalReportCheck:
        spec: dict = {
            "title": "Checkout errors stay low",
            "kind": SignalReportCheck.Kind.METRIC_THRESHOLD,
            "config": _threshold_config(),
            "next_run_at": timezone.now() + timedelta(days=7),
        }
        spec.update(overrides)
        return create_check(report=report or self.report, attribution=ArtefactAttribution.system(), **spec)

    def test_the_endpoint_does_not_create_checks(self) -> None:
        response = self.client.post(
            self.url,
            {"title": "Checkout errors stay low", "kind": "agent", "config": {"instructions": "Look at anything."}},
            format="json",
        )

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert not SignalReportCheck.objects.for_team(self.team.id).exists()

    def test_list_then_cancel(self) -> None:
        check = self._create()
        check_id = str(check.id)
        finished = self._create()
        SignalReportCheck.objects.for_team(self.team.id).filter(id=finished.id).update(
            status=SignalReportCheck.Status.PASSED, created_at=check.created_at + timedelta(minutes=1)
        )

        listed = self.client.get(self.url)
        assert [row["id"] for row in listed.json()["results"]] == [check_id, str(finished.id)]
        assert listed.json()["results"][0]["config"]["query"] == _PAGEVIEWS

        cancelled = self.client.delete(f"{self.url}{check_id}/")
        assert cancelled.status_code == status.HTTP_200_OK
        assert cancelled.json()["status"] == "cancelled"

        already_cancelled = self.client.delete(f"{self.url}{check_id}/")
        assert already_cancelled.status_code == status.HTTP_400_BAD_REQUEST
        assert self.client.post(f"{self.url}{check_id}/approve/").status_code == status.HTTP_400_BAD_REQUEST
        check.refresh_from_db()
        assert check.approved_at is None

    def test_approval_is_idempotent_and_does_not_change_the_schedule(self) -> None:
        check = self._create()
        approved_at = check.updated_at + timedelta(minutes=1)
        with time_machine.travel(approved_at, tick=False):
            first = self.client.post(f"{self.url}{check.id}/approve/")
        with time_machine.travel(approved_at + timedelta(minutes=1), tick=False):
            second = self.client.post(f"{self.url}{check.id}/approve/")

        assert first.status_code == status.HTTP_200_OK
        assert second.status_code == status.HTTP_200_OK
        check.refresh_from_db()
        assert check.approved_by_id == self.user.id
        assert check.approved_at == check.updated_at == approved_at
        assert datetime.fromisoformat(first.json()["updated_at"]) == approved_at
        assert first.json()["updated_at"] == second.json()["updated_at"]
        assert first.json()["next_run_at"] == second.json()["next_run_at"]
        assert check.status == SignalReportCheck.Status.ACTIVE

    @parameterized.expand(
        [
            ("missing_config", {}),
            ("fractional_count", _threshold_config(value_format="count", comparison={"operator": "lte", "value": 1.5})),
            (
                "malformed_hogql",
                _threshold_config(
                    query=trends_metric_query(
                        series=[{"kind": "EventsNode", "event": "$pageview", "math": "hogql", "math_hogql": "sum("}]
                    )
                ),
            ),
        ]
    )
    def test_invalid_metric_replacement_leaves_the_check_and_activity_unchanged(self, _name: str, config: dict) -> None:
        check = self._create()
        SignalReportCheck.objects.for_team(self.team.id).filter(id=check.id).update(approved_at=timezone.now())
        original_state = SignalReportCheck.objects.for_team(self.team.id).filter(id=check.id).values().get()
        log_count = SignalReportArtefact.objects.filter(report=self.report).count()

        rejected = self.client.post(
            f"{self.url}{check.id}/replace/", {"title": "Better metric", "config": config}, format="json"
        )
        assert rejected.status_code == status.HTTP_400_BAD_REQUEST
        assert SignalReportCheck.objects.for_team(self.team.id).filter(id=check.id).values().get() == original_state
        assert SignalReportCheck.objects.for_team(self.team.id).filter(report=self.report).count() == 1
        assert SignalReportArtefact.objects.filter(report=self.report).count() == log_count

    def test_replacement_keeps_a_check_moved_by_a_report_merge(self) -> None:
        SignalReport.objects.filter(id=self.report.id).update(status=SignalReport.Status.READY)
        self.report.refresh_from_db()
        check = self._create()
        survivor = SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY, title="Surviving fix")
        merge_reports(
            team=self.team,
            survivor=survivor,
            source_ids=[str(self.report.id)],
            attribution=ArtefactAttribution.from_user(self.user.id),
        )
        original_state = SignalReportCheck.objects.for_team(self.team.id).filter(id=check.id).values().get()
        log_count = SignalReportArtefact.objects.filter(report_id__in=[self.report.id, survivor.id]).count()
        request = APIRequestFactory().post(self.url)
        force_authenticate(request, user=self.user)

        with self.assertRaisesRegex(CheckCreationError, "moved to another report"):
            replace_metric_check(
                check=check,
                title="Revised goal",
                rationale="",
                config=_threshold_config(),
                attribution=ArtefactAttribution.from_user(self.user.id),
                access_policy=ReportMetricAccessPolicy(request=Request(request), team=self.team),
            )

        assert SignalReportCheck.objects.for_team(self.team.id).filter(id=check.id).values().get() == original_state
        assert original_state["report_id"] == survivor.id
        assert not SignalReportCheck.objects.for_team(self.team.id).filter(report=self.report).exists()
        assert SignalReportArtefact.objects.filter(report_id__in=[self.report.id, survivor.id]).count() == log_count

    @parameterized.expand(
        [
            ("minute_precision_soak", "-30d", MIN_CHECK_INTERVAL_MINUTES, 3, True),
            ("zero_soak", "-7d", MIN_CHECK_INTERVAL_MINUTES, 3, True, 0),
            ("longer_query_window", "-40d", 30 * 24 * 60, 3, False),
            ("last_run_at_expiry", "-7d", 30 * 24 * 60, 3, False, 30 * 24 * 60),
            ("fits_near_horizon", "-7d", 30 * 24 * 60, 3, True, 29 * 24 * 60),
            ("pending_longer_query", "-40d", 30 * 24 * 60, 3, False, 1450, SignalReport.Status.READY),
        ]
    )
    def test_replacement_preserves_only_recurring_schedules_that_fit(
        self,
        _name: str,
        date_from: str,
        interval: int,
        runs: int,
        fits: bool,
        stored_soak: int = 1450,
        report_status: str = SignalReport.Status.RESOLVED,
    ) -> None:
        now = datetime(2026, 10, 2, 12, tzinfo=UTC)
        with time_machine.travel(now, tick=False):
            SignalReport.objects.filter(id=self.report.id).update(status=report_status)
            self.report.refresh_from_db()
            check = self._create(
                config=_threshold_config(
                    query=trends_metric_query(series=[{"kind": "EventsNode", "event": "$pageview"}], date_from="-7d")
                ),
                run_interval_minutes=interval,
                runs_remaining=runs,
            )
            SignalReportCheck.objects.for_team(self.team.id).filter(id=check.id).update(
                soak_minutes=stored_soak, approved_at=now, approved_by=self.user
            )
            original_state = SignalReportCheck.objects.for_team(self.team.id).filter(id=check.id).values().get()
            log_count = SignalReportArtefact.objects.filter(report=self.report).count()
            config = _threshold_config(
                query=trends_metric_query(series=[{"kind": "EventsNode", "event": "$pageview"}], date_from=date_from),
                comparison={"operator": "lte", "value": 5},
            )
            payload: dict[str, object] = {"title": "Revised goal", "config": config}
            response = self.client.post(f"{self.url}{check.id}/replace/", payload, format="json")
        check.refresh_from_db()
        if not fits:
            assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
            assert "90-day horizon" in response.json()["error"]
            assert SignalReportCheck.objects.for_team(self.team.id).filter(id=check.id).values().get() == original_state
            assert SignalReportCheck.objects.for_team(self.team.id).filter(report=self.report).count() == 1
            assert SignalReportArtefact.objects.filter(report=self.report).count() == log_count
        else:
            assert response.status_code == status.HTTP_200_OK, response.json()
            replacement = SignalReportCheck.objects.for_team(self.team.id).get(id=response.json()["id"])
            assert check.status == SignalReportCheck.Status.CANCELLED
            assert replacement.soak_minutes == stored_soak
            assert replacement.run_interval_minutes == interval
            assert replacement.runs_remaining == runs
            assert replacement.approved_at is None
            assert replacement.approved_by_id is None
            assert replacement.status == SignalReportCheck.Status.ACTIVE
            last_run_at = replacement.next_run_at + timedelta(minutes=interval * (runs - 1))
            assert last_run_at < replacement.expires_at <= now + MAX_CHECK_HORIZON

    @parameterized.expand([("direct_query", False), ("metric_reference", True)])
    def test_replacement_cannot_schedule_queries_hidden_from_the_requester(self, _name: str, reference: bool) -> None:
        check = self._create()
        self.report.metrics = [{"metric_id": "pageviews", "query": _PAGEVIEWS}]
        self.report.save(update_fields=["metrics"])
        self.organization.available_product_features = [
            {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=PropertyDefinition.objects.create(
                team=self.team, name="secret_plan", property_type="String", type=PropertyDefinition.Type.EVENT
            ),
            organization_member=self.organization_membership,
            access_level=PropertyAccessLevel.NONE.value,
        )
        config: dict[str, object] = {"comparison": {"operator": "lte", "value": 5}}
        config.update({"metric_id": "pageviews"} if reference else {"query": _PAGEVIEWS})
        response = self.client.post(
            f"{self.url}{check.id}/replace/", {"title": "Revised goal", "config": config}, format="json"
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.ACTIVE
        assert SignalReportCheck.objects.for_team(self.team.id).filter(report=self.report).count() == 1

        task = Task.objects.create(team=self.team, created_by=self.user, title="Research a report")
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            state={"analytics_query_context": [_PAGEVIEWS], "task_summary": "Restricted measurement"},
        )
        trace = self.client.get(f"/api/projects/{self.team.id}/tasks/{task.id}/runs/{run.id}/session_logs/")
        assert trace.status_code == status.HTTP_403_FORBIDDEN
        summaries = self.client.post(
            f"/api/projects/{self.team.id}/tasks/summaries/", {"ids": [str(task.id)]}, format="json"
        )
        assert summaries.status_code == status.HTTP_200_OK
        assert summaries.json()["results"][0]["latest_run"]["task_summary"] is None

    def test_task_write_key_without_query_access_cannot_replace_a_metric_check(self) -> None:
        check = self._create()
        raw_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Task-only test key",
            user=self.user,
            secure_value=hash_key_value(raw_key),
            scopes=["task:write", "task:read"],
            scoped_teams=[self.team.id],
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_key}")
        response = self.client.post(
            f"{self.url}{check.id}/replace/",
            {"title": "Revised goal", "config": _threshold_config()},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.ACTIVE

    def test_a_created_check_is_reported_for_adoption(self) -> None:
        with patch(_CAPTURE) as capture:
            with self.captureOnCommitCallbacks(execute=True):
                check = self._create(run_interval_minutes=MIN_CHECK_INTERVAL_MINUTES, runs_remaining=2)

        assert capture.call_count == 1
        properties = capture.call_args.kwargs["properties"]
        assert capture.call_args.kwargs["event"] == "signals_report_check_created"
        assert properties["check_id"] == str(check.id)
        assert properties["kind"] == SignalReportCheck.Kind.METRIC_THRESHOLD
        assert properties["metric_source"] == "query"
        assert properties["run_interval_minutes"] == MIN_CHECK_INTERVAL_MINUTES
        assert properties["runs_remaining"] == 2

    def test_cancelling_does_not_overwrite_a_verdict_that_landed_first(self) -> None:
        check_id = str(self._create().id)
        # The row the request read before a run committed its verdict.
        stale = SignalReportCheck.objects.for_team(self.team.id).get(id=check_id)
        SignalReportCheck.objects.for_team(self.team.id).filter(id=check_id).update(
            status=SignalReportCheck.Status.PASSED, last_outcome=SignalReportCheck.Outcome.PASSED
        )

        with patch.object(SignalReportCheckViewSet, "get_object", return_value=stale):
            refused = self.client.delete(f"{self.url}{check_id}/")

        assert refused.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            SignalReportCheck.objects.for_team(self.team.id).get(id=check_id).status == SignalReportCheck.Status.PASSED
        )

    def test_a_metric_reference_is_resolved_and_copied_when_the_check_is_created(self) -> None:
        config = {"metric_id": "checkout-errors", "comparison": {"operator": "lte", "value": 10}}

        with self.assertRaises(CheckCreationError):
            self._create(config=config)
        assert not SignalReportCheck.objects.for_team(self.team.id).filter(report_id=self.report.id).exists()

        self.report.metrics = [
            {
                "metric_id": "checkout-errors",
                "title": "Checkout errors",
                "kind": "occurrences",
                "value_format": "count",
                "query": _PAGEVIEWS,
            }
        ]
        self.report.save(update_fields=["metrics"])
        stored = self._create(config={**config, "value_format": "percentage", "unit": "failure"})
        assert stored.config["metric_id"] == "checkout-errors"
        assert stored.config["query"] == _PAGEVIEWS
        assert stored.config["metric_kind"] == "occurrences"
        assert stored.config["value_format"] == "count"
        overridden = self._create(config={**config, "metric_kind": "custom", "value_format": "number", "unit": "USD"})
        assert overridden.config["metric_kind"] == "occurrences"
        assert overridden.config["value_format"] == "count"
        assert overridden.config["unit"] is None

        # Rewriting the metric under the same id must not move the check's target.
        rewritten = trends_metric_query(series=[{"kind": "EventsNode", "event": "$autocapture"}])
        self.report.metrics = [{**self.report.metrics[0], "query": rewritten}]
        self.report.save(update_fields=["metrics"])
        SignalReportCheck.objects.for_team(self.team.id).filter(id=stored.id).update(
            next_run_at=timezone.now() - timedelta(minutes=1), measurement_start_at=timezone.now() - timedelta(days=32)
        )
        with patch(
            _MEASURE, return_value=MetricMeasurement(value=0.0, measured_at=timezone.now(), series=None)
        ) as measure:
            run_due_report_checks()
        measured_query = measure.call_args.args[0]
        assert {key: value for key, value in measured_query["source"].items() if key != "dateRange"} == {
            key: value for key, value in _PAGEVIEWS["source"].items() if key != "dateRange"
        }
        assert measured_query["source"]["dateRange"]["explicitDate"] is True
        assert datetime.fromisoformat(measured_query["source"]["dateRange"]["date_from"]) >= timezone.now() - timedelta(
            days=32
        )

    @parameterized.expand([("same_query", False), ("changed_query", True)])
    def test_legacy_display_fields_only_come_from_the_metrics_original_query(self, _name: str, changed: bool) -> None:
        query = trends_metric_query(
            series=[{"kind": "EventsNode", "event": "completed"}, {"kind": "EventsNode", "event": "started"}],
        )
        query["source"]["trendsFilter"] = {"formula": "A / B", "aggregationAxisFormat": "percentage_scaled"}
        self.report.metrics = [
            {
                "metric_id": "conversion",
                "title": "Completion rate",
                "kind": "conversion_rate",
                "value_format": "percentage_scaled",
                "query": query,
            }
        ]
        self.report.save(update_fields=["metrics"])
        check = self._create(config={"metric_id": "conversion", "comparison": {"operator": "gte", "value": 0.1}})
        check.config = {
            key: value for key, value in check.config.items() if key not in ("metric_kind", "value_format", "unit")
        }
        check.save(update_fields=["config"])
        if changed:
            self.report.metrics[0]["query"] = _PAGEVIEWS
            self.report.save(update_fields=["metrics"])

        response = self.client.get(f"{self.url}{check.id}/")
        assert response.status_code == status.HTTP_200_OK
        config = response.json()["config"]
        assert config.get("value_format") == (None if changed else "percentage_scaled")
        assert config.get("metric_kind") == (None if changed else "conversion_rate")
        assert config["query"] == query
        check.refresh_from_db()
        assert "value_format" not in check.config

    def test_a_check_created_in_a_child_environment_stays_on_that_environment(self) -> None:
        child = Team.objects.create(organization=self.organization, name="Child", parent_team=self.team)
        report = SignalReport.objects.create(team=child, status=SignalReport.Status.RESOLVED, title="Fix")
        url = f"/api/projects/{child.id}/signals/reports/{report.id}/checks/"

        check_id = str(self._create(report=report).id)

        assert [row["id"] for row in self.client.get(url).json()["results"]] == [check_id]
        assert SignalReportCheck.all_teams.get(id=check_id).team_id == child.id

        SignalReportCheck.all_teams.filter(id=check_id).update(
            next_run_at=timezone.now() - timedelta(minutes=1), measurement_start_at=timezone.now() - timedelta(days=32)
        )
        with patch(_MEASURE, return_value=MetricMeasurement(value=0.0, measured_at=timezone.now(), series=None)):
            run_due_report_checks()
        result = SignalReportArtefact.objects.get(report=report, type=SignalReportArtefact.ArtefactType.CHECK_RESULT)
        assert result.team_id == child.id

    def test_a_property_restricted_member_cannot_read_a_checks_query_or_measured_values(self) -> None:
        secret_pageviews = trends_metric_query(
            series=[
                {
                    "kind": "EventsNode",
                    "event": "$pageview",
                    "properties": [
                        {"key": "secret_plan", "value": ["enterprise"], "operator": "exact", "type": "event"}
                    ],
                }
            ]
        )
        check_id = str(
            self._create(
                title="Enterprise pageviews stay low",
                config=_threshold_config(query=secret_pageviews, baseline_value=3),
            ).id
        )
        SignalReportCheck.objects.for_team(self.team.id).filter(id=check_id).update(
            next_run_at=timezone.now() - timedelta(minutes=1), measurement_start_at=timezone.now() - timedelta(days=32)
        )
        with patch(_MEASURE, return_value=MetricMeasurement(value=4.0, measured_at=timezone.now(), series=None)):
            run_due_report_checks()
        artefacts_url = f"/api/projects/{self.team.id}/signals/reports/{self.report.id}/artefacts/"

        def check_result() -> dict:
            return next(
                row["content"]
                for row in self.client.get(artefacts_url).json()["results"]
                if row["type"] == "check_result"
            )

        assert check_result()["observed_value"] == 4.0

        self.organization.available_product_features = [
            {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=PropertyDefinition.objects.create(
                team=self.team, name="secret_plan", property_type="String", type=PropertyDefinition.Type.EVENT
            ),
            organization_member=self.organization_membership,
            access_level=PropertyAccessLevel.NONE.value,
        )

        config = self.client.get(f"{self.url}{check_id}/").json()["config"]
        assert config["query"] is None
        assert config["baseline_value"] is None
        assert config["comparison"] == {"operator": "lte", "value": 10}

        hidden = check_result()
        assert hidden["outcome"] == "passed"
        assert hidden["observed_value"] is None
        assert hidden["baseline_value"] is None
        assert hidden["explanation"] == CHECK_RESULT_HIDDEN_EXPLANATION

    def test_an_agent_checks_verdict_is_readable_because_a_run_wrote_it(self) -> None:
        # The metric-access policy judges a stored query, which an agent check does not carry, so
        # gating its verdict on that policy would hide every agent result from every reader.
        check = self._create(
            title="Checkout 500s stay gone",
            kind=SignalReportCheck.Kind.AGENT,
            config={"instructions": "Re-read the issue and say whether it still fires."},
        )
        record_check_verdict(check, CheckVerdict(outcome="failed", explanation="The issue fired 30 times yesterday."))

        artefacts_url = f"/api/projects/{self.team.id}/signals/reports/{self.report.id}/artefacts/"
        result = next(
            row["content"] for row in self.client.get(artefacts_url).json()["results"] if row["type"] == "check_result"
        )
        assert result["explanation"] == "The issue fired 30 times yesterday."

    def test_a_report_carries_a_bounded_number_of_active_checks(self) -> None:
        for _ in range(MAX_ACTIVE_CHECKS_PER_REPORT):
            self._create()

        with self.assertRaises(CheckCreationError):
            self._create()

    def test_another_teams_report_is_not_reachable(self) -> None:
        other_team = self.organization.teams.create(name="Other")
        other_report = SignalReport.objects.create(team=other_team, status=SignalReport.Status.READY)
        response = self.client.get(
            f"/api/projects/{self.team.id}/signals/reports/{other_report.id}/checks/",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestAgentCheckDispatch(APIBaseTest):
    """The agent lane: what the coordinator does with a due `agent` check, and what it refuses."""

    def setUp(self) -> None:
        super().setUp()
        self.report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.RESOLVED, title="Checkout 500s"
        )
        self._enrol({"guaranteed_team_ids": [self.team.id]})
        LLMSkill.objects.create(team=self.team, name=FALLBACK_CHECK_SKILL_NAME, is_latest=True, deleted=False)
        self.scout_config = SignalScoutConfig.objects.create(
            team=self.team,
            skill_name=FALLBACK_CHECK_SKILL_NAME,
            status=SignalScoutConfig.Status.ACTIVE,
            enabled=True,
        )

    def _enrol(self, payload: dict) -> None:
        flag = patch(_FLAG_PAYLOAD, return_value=payload)
        flag.start()
        self.addCleanup(flag.stop)

    def _check(self, **overrides) -> SignalReportCheck:
        now = timezone.now()
        fields: dict = {
            "team": self.team,
            "report": self.report,
            "title": "Checkout 500s stay gone",
            "kind": SignalReportCheck.Kind.AGENT,
            "config": {"instructions": "Re-read the issue and say whether it still fires."},
            "next_run_at": now - timedelta(minutes=1),
            "expires_at": now + timedelta(days=30),
        }
        fields.update(overrides)
        return SignalReportCheck.objects.for_team(self.team.id).create(**fields)

    def _results(self) -> list[SignalReportArtefact]:
        return list(
            SignalReportArtefact.objects.filter(
                report=self.report, type=SignalReportArtefact.ArtefactType.CHECK_RESULT
            ).order_by("created_at")
        )

    def test_a_due_check_starts_a_run_and_waits_for_it(self) -> None:
        check = self._check()
        with patch(_CONNECT), patch(_DISPATCH, return_value="wf-1") as dispatch:
            summary = run_due_report_checks()

        assert summary.dispatched == 1
        assert dispatch.call_args.kwargs["skill_name"] == FALLBACK_CHECK_SKILL_NAME
        assert dispatch.call_args.kwargs["team_id"] == self.team.id
        check.refresh_from_db()
        # Still owed: a dispatch is not a verdict, so nothing is recorded and the row stays active
        # with its next look pushed past the window the run has to answer in.
        assert check.status == SignalReportCheck.Status.ACTIVE
        assert check.dispatched_at is not None
        assert check.next_run_at > timezone.now() + AGENT_CHECK_RESULT_WINDOW - timedelta(minutes=5)
        assert self._results() == []

    def test_a_report_reopened_after_collection_does_not_dispatch_a_check(self) -> None:
        check = self._check()
        self.report.status = SignalReport.Status.READY
        self.report.save(update_fields=["status"])

        with patch(_CONNECT), patch(_DISPATCH) as dispatch:
            assert run_agent_check(check) == "deferred"

        dispatch.assert_not_called()
        check.refresh_from_db()
        assert check.dispatched_at is None
        assert self._results() == []

    def test_the_run_note_carries_the_brief_and_the_resolution_note(self) -> None:
        SignalReportArtefact.append_dismissal(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=Dismissal(reason="resolved", note="Shipped the retry fix"),
            attribution=ArtefactAttribution.system(),
        )
        check = self._check(
            rationale="The fix was a retry, which can mask rather than remove the error.",
            config={"instructions": "Re-read the issue.", "probe_hints": ["issue 4821"]},
        )

        note = build_check_run_note(check, AgentCheckConfig.model_validate(check.config))

        assert str(check.id) in note
        assert "Checkout 500s stay gone" in note
        assert "which can mask rather than remove the error" in note
        assert "issue 4821" in note
        assert "Shipped the retry fix" in note
        assert "scout-check-record-result" in note

    def test_a_dispatched_run_is_listed_on_its_check_and_records_its_verdict(self) -> None:
        check = self._check()
        with patch(_CONNECT), patch(_DISPATCH, return_value="wf-1") as dispatch:
            run_due_report_checks()
        assert dispatch.call_args.kwargs["check_id"] == str(check.id)

        (queued,) = list_report_checks(team=self.team, report_id=str(self.report.id))
        assert (queued.run_state, queued.waiting_on_run, queued.dispatched_run_id) == ("queued", True, None)

        task = Task.objects.create(team=self.team, title="t", description="d")
        run = SignalScoutRun.objects.create(
            task_run=TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS),
            team=self.team,
            scout_config=self.scout_config,
            skill_name=FALLBACK_CHECK_SKILL_NAME,
            skill_version=1,
            metadata={"check_id": dispatch.call_args.kwargs["check_id"]},
        )
        (running,) = list_report_checks(team=self.team, report_id=str(self.report.id))
        assert (running.run_state, running.dispatched_run_id) == ("running", str(run.id))

        result = record_check_result(
            team=self.team, run=run, check_id=str(check.id), outcome="passed", explanation="No events since the fix."
        )

        assert result.check_status == SignalReportCheck.Status.PASSED
        (closed,) = list_report_checks(team=self.team, report_id=str(self.report.id))
        assert (closed.run_state, closed.waiting_on_run) == (SignalReportCheck.Status.PASSED, False)

    def test_a_check_naming_a_scout_runs_on_that_scout(self) -> None:
        LLMSkill.objects.create(team=self.team, name=_OTHER_SKILL, is_latest=True, deleted=False)
        SignalScoutConfig.objects.create(
            team=self.team, skill_name=_OTHER_SKILL, status=SignalScoutConfig.Status.ACTIVE, enabled=True
        )
        self._check(config={"instructions": "Re-read the issue.", "skill_name": _OTHER_SKILL})

        with patch(_CONNECT), patch(_DISPATCH, return_value="wf-1") as dispatch:
            run_due_report_checks()

        assert dispatch.call_args.kwargs["skill_name"] == _OTHER_SKILL

    @parameterized.expand(
        [
            (
                "warned_lane_still_runs",
                {
                    "enabled": True,
                    "status": SignalScoutConfig.Status.PENDING_PAUSE,
                    "pause_reason": SignalScoutConfig.PauseReason.NO_OUTPUT,
                },
                None,
            ),
            ("missing_lane", None, "has no"),
        ]
    )
    def test_a_lane_that_cannot_run_records_a_visible_errored_result(self, _name, config_state, expected) -> None:
        if config_state is None:
            self.scout_config.delete()
        else:
            for field, value in config_state.items():
                setattr(self.scout_config, field, value)
            self.scout_config.save()
        check = self._check()

        with patch(_CONNECT), patch(_DISPATCH, return_value="wf-1") as dispatch:
            summary = run_due_report_checks()

        # A scout the harness only warned is still scheduled, so a check on it still runs.
        if expected is None:
            assert summary.dispatched == 1
            dispatch.assert_called_once()
            assert self._results() == []
            return

        assert summary.errored == 1
        dispatch.assert_not_called()
        results = self._results()
        assert len(results) == 1
        assert '"outcome":"errored"' in results[0].content
        assert expected in results[0].content
        check.refresh_from_db()
        assert check.consecutive_errors == 1

    def test_a_check_on_a_retired_scout_runs_on_the_follow_up_scout(self) -> None:
        # Retiring a scout must not turn every open check bound to it into an errored result on a
        # report. The fallback scout re-measures resolved reports for a living, so it answers them.
        LLMSkill.objects.create(team=self.team, name="signals-scout-health-checks", is_latest=True, deleted=False)
        SignalScoutConfig.objects.create(
            team=self.team,
            skill_name="signals-scout-health-checks",
            status=SignalScoutConfig.Status.PAUSED_BY_SYSTEM,
            pause_reason=SignalScoutConfig.PauseReason.RETIRED,
            enabled=False,
        )
        self._check(
            config={
                "instructions": "Re-read the issue and say whether it still fires.",
                "skill_name": "signals-scout-health-checks",
            }
        )

        with patch(_CONNECT), patch(_DISPATCH, return_value="wf-1") as dispatch:
            summary = run_due_report_checks()

        assert summary.dispatched == 1
        assert dispatch.call_args.kwargs["skill_name"] == FALLBACK_CHECK_SKILL_NAME
        assert self._results() == []

    @parameterized.expand([("named_lane", "signals-scout-health-checks"), ("fallback_lane", None)])
    def test_a_check_on_a_paused_scout_waits_for_the_resume_without_spending_errors(self, _name, skill_name) -> None:
        # A pause is somebody's decision, so the check neither runs on another scout nor burns its
        # error budget while the pause lasts.
        if skill_name is None:
            scout_config = self.scout_config
            scout_config.enabled = False
            scout_config.save()
            config = {"instructions": "Re-read the issue and say whether it still fires."}
        else:
            LLMSkill.objects.create(team=self.team, name=skill_name, is_latest=True, deleted=False)
            scout_config = SignalScoutConfig.objects.create(team=self.team, skill_name=skill_name, enabled=False)
            config = {"instructions": "Re-read the issue and say whether it still fires.", "skill_name": skill_name}
        check = self._check(config=config)

        for _ in range(MAX_CONSECUTIVE_CHECK_ERRORS):
            SignalReportCheck.objects.for_team(self.team.id).filter(id=check.id).update(
                next_run_at=timezone.now() - timedelta(minutes=1)
            )
            with patch(_CONNECT), patch(_DISPATCH) as dispatch:
                summary = run_due_report_checks()
            assert summary.deferred == 1
            dispatch.assert_not_called()

        assert self._results() == []
        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.ACTIVE
        assert check.consecutive_errors == 0

        scout_config.enabled = True
        scout_config.save()
        check.refresh_from_db()
        assert check.next_run_at <= timezone.now()
        with patch(_CONNECT), patch(_DISPATCH, return_value="wf-1") as dispatch:
            summary = run_due_report_checks()

        assert summary.dispatched == 1
        assert dispatch.call_args.kwargs["skill_name"] == (skill_name or FALLBACK_CHECK_SKILL_NAME)

    def test_an_unenrolled_project_records_an_errored_result(self) -> None:
        self._enrol({"guaranteed_team_ids": []})
        self._check()

        with patch(_CONNECT), patch(_DISPATCH) as dispatch:
            summary = run_due_report_checks()

        assert summary.errored == 1
        dispatch.assert_not_called()
        assert len(self._results()) == 1

    def test_a_lane_already_running_waits_instead_of_spending_an_error(self) -> None:
        task = Task.objects.create(team=self.team, title="t", description="d")
        task_run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        SignalScoutRun.objects.create(
            task_run=task_run,
            team=self.team,
            scout_config=self.scout_config,
            skill_name=FALLBACK_CHECK_SKILL_NAME,
            skill_version=1,
        )
        check = self._check()

        with patch(_CONNECT), patch(_DISPATCH) as dispatch, patch(_CAPTURE) as capture:
            summary = run_due_report_checks()

        assert summary.deferred == 1
        dispatch.assert_not_called()
        assert capture.call_args.kwargs["event"] == "signals_report_check_dispatch"
        assert capture.call_args.kwargs["properties"]["outcome"] == "deferred"
        assert capture.call_args.kwargs["properties"]["reason"] == "run_in_flight"
        assert self._results() == []
        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.ACTIVE
        assert check.consecutive_errors == 0
        assert check.dispatched_at is None
        assert check.next_run_at > timezone.now() + CHECK_DISPATCH_DEFER_AFTER - timedelta(minutes=5)

    def test_a_dispatch_that_never_started_leaves_the_check_unclaimed(self) -> None:
        check = self._check()
        with patch(_CONNECT), patch(_DISPATCH, side_effect=WorkflowAlreadyStartedError("id", "type")):
            summary = run_due_report_checks()

        assert summary.deferred == 1
        check.refresh_from_db()
        assert check.dispatched_at is None
        assert check.status == SignalReportCheck.Status.ACTIVE

    @parameterized.expand([("live_lane", True), ("paused_lane", False)])
    def test_a_run_that_never_records_a_result_errors_the_check_unless_its_lane_is_paused(
        self, _name, lane_enabled
    ) -> None:
        now = timezone.now()
        check = self._check(dispatched_at=now - AGENT_CHECK_RESULT_WINDOW, next_run_at=now - timedelta(minutes=1))
        self.scout_config.enabled = lane_enabled
        self.scout_config.save()

        with patch(_CONNECT), patch(_DISPATCH) as dispatch:
            summary = run_due_report_checks()

        dispatch.assert_not_called()
        check.refresh_from_db()
        assert check.dispatched_at is None
        assert check.status == SignalReportCheck.Status.ACTIVE
        if lane_enabled:
            assert summary.errored == 1
            assert check.consecutive_errors == 1
            assert "ended without recording a result" in self._results()[0].content
        else:
            assert summary.deferred == 1
            assert check.consecutive_errors == 0
            assert self._results() == []
            assert check.next_run_at > now + CHECK_DISPATCH_DEFER_AFTER - timedelta(minutes=5)

    @parameterized.expand(
        [
            (
                "paused_refusal",
                "The `signals-scout-inbox-validation` scout is paused, so the check could not run.",
                True,
            ),
            ("other_error", "the follow-up run ended without recording a result.", False),
        ]
    )
    def test_the_repair_reactivates_only_checks_a_paused_refusal_retired(self, _name, reason, reactivated) -> None:
        check = self._check(consecutive_errors=MAX_CONSECUTIVE_CHECK_ERRORS - 1)
        record_check_verdict(
            check, CheckVerdict(outcome="errored", explanation=f"{check.title}: {reason}"), now=timezone.now()
        )
        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.ERRORED

        dry_run = reactivate_checks_errored_by_scout_pause(apply=False)
        summary = reactivate_checks_errored_by_scout_pause(apply=True)

        assert (dry_run.matched, dry_run.reactivated) == (int(reactivated), 0)
        assert summary.reactivated == int(reactivated)
        check.refresh_from_db()
        if reactivated:
            assert check.status == SignalReportCheck.Status.ACTIVE
            assert check.consecutive_errors == 0
            with patch(_CONNECT), patch(_DISPATCH, return_value="wf-1"):
                assert run_due_report_checks().dispatched == 1
        else:
            assert check.status == SignalReportCheck.Status.ERRORED


class TestCheckResultTool(APIBaseTest):
    """`scout-check-record-result`: which checks a run may close, and what closing one does."""

    def setUp(self) -> None:
        super().setUp()
        self.report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.RESOLVED, title="Checkout 500s"
        )
        self.scout_config = SignalScoutConfig.objects.create(
            team=self.team,
            skill_name=FALLBACK_CHECK_SKILL_NAME,
            status=SignalScoutConfig.Status.ACTIVE,
            enabled=True,
        )
        task = Task.objects.create(team=self.team, title="t", description="d")
        task_run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        self.scout_run = SignalScoutRun.objects.create(
            task_run=task_run,
            team=self.team,
            scout_config=self.scout_config,
            skill_name=FALLBACK_CHECK_SKILL_NAME,
            skill_version=1,
        )
        # A live lane for the other scout, so a check naming it is one another scout really
        # owns rather than one the dispatch would have resolved onto the fallback anyway.
        LLMSkill.objects.create(team=self.team, name=_OTHER_SKILL, is_latest=True, deleted=False)

    def _check(self, **overrides) -> SignalReportCheck:
        now = timezone.now()
        fields: dict = {
            "team": self.team,
            "report": self.report,
            "title": "Checkout 500s stay gone",
            "kind": SignalReportCheck.Kind.AGENT,
            "config": {"instructions": "Re-read the issue."},
            "next_run_at": now + AGENT_CHECK_RESULT_WINDOW,
            "expires_at": now + timedelta(days=30),
            "dispatched_at": now,
        }
        fields.update(overrides)
        return SignalReportCheck.objects.for_team(self.team.id).create(**fields)

    def _record(self, check: SignalReportCheck, **overrides):
        payload: dict = {"outcome": "failed", "explanation": "The issue fired 30 times yesterday."}
        payload.update(overrides)
        return record_check_result(team=self.team, run=self.scout_run, check_id=str(check.id), **payload)

    def test_a_verdict_closes_the_check_and_lands_on_the_report(self) -> None:
        check = self._check()

        result = self._record(check, observed_value=30.0)

        assert result.check_status == SignalReportCheck.Status.FAILED
        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.FAILED
        assert check.dispatched_at is None
        assert check.last_outcome == SignalReportCheck.Outcome.FAILED
        artefact = SignalReportArtefact.objects.get(
            report=self.report, type=SignalReportArtefact.ArtefactType.CHECK_RESULT
        )
        assert '"outcome":"failed"' in artefact.content
        assert "fired 30 times yesterday" in artefact.content
        assert f'"run_id":"{self.scout_run.id}"' in artefact.content

    def test_a_previous_monitoring_periods_agent_run_cannot_answer_the_new_check(self) -> None:
        self.report.status = SignalReport.Status.MONITORING
        self.report.monitoring_started_at = self.scout_run.created_at + timedelta(minutes=1)
        self.report.save(update_fields=["status", "monitoring_started_at"])
        check = self._check()
        self.scout_run.metadata = {"check_id": str(check.id)}
        self.scout_run.save(update_fields=["metadata"])

        with self.assertRaisesRegex(InvalidCheckResultError, "newer monitoring period"):
            self._record(check)
        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.ACTIVE
        assert not SignalReportArtefact.objects.filter(
            report=self.report, type=SignalReportArtefact.ArtefactType.CHECK_RESULT
        ).exists()

    @parameterized.expand([("on_its_lane", False), ("bound_to_the_run", True)])
    def test_a_pass_rearms_a_recurring_check_for_its_next_look(self, _name, bind_run) -> None:
        check = self._check(run_interval_minutes=MIN_CHECK_INTERVAL_MINUTES, runs_remaining=2)
        if bind_run:
            self.scout_run.metadata = {"check_id": str(check.id)}
            self.scout_run.save(update_fields=["metadata"])

        result = self._record(check, outcome="passed", explanation="No events since the fix merged.")

        assert result.check_status == SignalReportCheck.Status.ACTIVE
        assert result.runs_remaining == 1
        with self.assertRaises(InvalidCheckResultError):
            self._record(check, outcome="passed", explanation="No events since the fix merged.")
        check.refresh_from_db()
        assert check.dispatched_at is None
        assert check.runs_remaining == 1
        assert check.next_run_at > timezone.now() + timedelta(minutes=MIN_CHECK_INTERVAL_MINUTES - 5)

    @parameterized.expand(
        [
            ("not_due_and_no_run_is_waiting", {"dispatched_at": None}),
            ("already_finished", {"status": SignalReportCheck.Status.CANCELLED}),
            ("waiting_for_its_report", {"status": SignalReportCheck.Status.PENDING, "dispatched_at": None}),
            ("another_scout_owns_it", {"config": {"instructions": "x", "skill_name": _OTHER_SKILL}}),
            ("the_coordinator_measures_it", {"kind": SignalReportCheck.Kind.METRIC_THRESHOLD}),
        ]
    )
    def test_a_check_this_run_was_not_sent_to_answer_is_refused(self, _name, overrides) -> None:
        check = self._check(**overrides)

        with self.assertRaises(InvalidCheckResultError):
            self._record(check)

        assert not SignalReportArtefact.objects.filter(
            report=self.report, type=SignalReportArtefact.ArtefactType.CHECK_RESULT
        ).exists()

    @parameterized.expand(
        [
            ("due_and_not_dispatched_yet", {"dispatched_at": None, "next_run_at": timezone.now()}, False),
            (
                "dispatched_to_this_run_on_a_lane_that_resolves_elsewhere_now",
                {"config": {"instructions": "x", "skill_name": _OTHER_SKILL}},
                True,
            ),
        ]
    )
    def test_a_check_this_run_may_answer_is_recorded(self, _name, overrides, bind_run) -> None:
        check = self._check(**overrides)
        if bind_run:
            self.scout_run.metadata = {"check_id": str(check.id)}
            self.scout_run.save(update_fields=["metadata"])

        result = self._record(check)

        assert result.check_status == SignalReportCheck.Status.FAILED

    @parameterized.expand(
        [
            ("its_report_is_ready", SignalReport.Status.READY, timedelta(days=30)),
            ("its_report_is_suppressed", SignalReport.Status.SUPPRESSED, timedelta(days=30)),
            ("its_horizon_passed", SignalReport.Status.RESOLVED, -timedelta(minutes=1)),
        ]
    )
    def test_a_due_check_the_coordinator_would_not_dispatch_is_paused(self, _name, report_status, expires_in) -> None:
        SignalReport.objects.filter(id=self.report.id).update(status=report_status)
        now = timezone.now()
        check = self._check(dispatched_at=None, next_run_at=now - timedelta(hours=1), expires_at=now + expires_in)

        (listed,) = list_report_checks(team=self.team, report_id=str(self.report.id))
        assert listed.run_state == "paused"
        with self.assertRaises(InvalidCheckResultError):
            self._record(check)

        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.ACTIVE
        assert not SignalReportArtefact.objects.filter(
            report=self.report, type=SignalReportArtefact.ArtefactType.CHECK_RESULT
        ).exists()

    def test_another_projects_check_is_not_reachable(self) -> None:
        other_team = self.organization.teams.create(name="Other")
        other_report = SignalReport.objects.create(team=other_team, status=SignalReport.Status.RESOLVED)
        other_check = SignalReportCheck.objects.for_team(other_team.id).create(
            team=other_team,
            report=other_report,
            title="Theirs",
            kind=SignalReportCheck.Kind.AGENT,
            config={"instructions": "Re-read the issue."},
            next_run_at=timezone.now() + timedelta(days=1),
            expires_at=timezone.now() + timedelta(days=30),
            dispatched_at=timezone.now(),
        )

        with self.assertRaises(InvalidCheckResultError):
            self._record(other_check)

    @parameterized.expand(
        [
            ("awaiting_data_looks_again", "awaiting_data", SignalReportCheck.Status.ACTIVE),
            ("unmeasurable_ends_the_check", "unmeasurable", SignalReportCheck.Status.INCONCLUSIVE),
        ]
    )
    def test_an_inconclusive_verdict_records_its_reason(self, _name: str, reason: str, expected_status: str) -> None:
        check = self._check()

        result = self._record(check, outcome="inconclusive", reason=reason, explanation="No traffic since the fix.")

        assert result.check_status == expected_status
        check.refresh_from_db()
        assert check.last_outcome == SignalReportCheck.Outcome.INCONCLUSIVE
        assert check.last_outcome_reason == reason
        assert check.consecutive_errors == 0
        artefact = SignalReportArtefact.objects.get(
            report=self.report, type=SignalReportArtefact.ArtefactType.CHECK_RESULT
        )
        assert f'"reason":"{reason}"' in artefact.content

    @parameterized.expand(
        [
            ("blank_explanation", {"explanation": "  "}),
            ("unknown_outcome", {"outcome": "maybe"}),
            ("inconclusive_without_a_reason", {"outcome": "inconclusive"}),
            ("inconclusive_with_an_unknown_reason", {"outcome": "inconclusive", "reason": "tired"}),
            ("a_reason_on_another_outcome", {"outcome": "errored", "reason": "awaiting_data"}),
        ]
    )
    def test_a_malformed_verdict_is_refused(self, _name, overrides) -> None:
        check = self._check()

        with self.assertRaises(InvalidCheckResultError):
            self._record(check, **overrides)


class TestPendingChecks(APIBaseTest):
    """A check written before the fix exists: it waits for the report to resolve, then soaks."""

    def setUp(self) -> None:
        super().setUp()
        self.report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY, title="Fix")

    def _pending(self, **overrides) -> SignalReportCheck:
        return create_check(
            report=self.report,
            title="Checkout errors stay low",
            kind=SignalReportCheck.Kind.METRIC_THRESHOLD,
            config=_threshold_config(),
            attribution=ArtefactAttribution.system(),
            soak_minutes=DEFAULT_CHECK_SOAK_HOURS * 60,
            **overrides,
        )

    def _resolve(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            self.report.status = SignalReport.Status.RESOLVED
            self.report.save(update_fields=["status"])

    @parameterized.expand([("enabled", True, 200), ("disabled", False, 400)])
    @override_settings(DEBUG=False)
    def test_monitoring_entry_is_gated_and_starts_the_measurement_window(
        self, _name: str, enabled: bool, expected_code: int
    ) -> None:
        check = self._pending()
        url = f"/api/projects/{self.team.id}/signals/reports/{self.report.id}/state/"
        with patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=enabled):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(url, {"state": "monitoring"}, format="json")
        assert response.status_code == expected_code, response.json()
        self.report.refresh_from_db()
        check.refresh_from_db()
        if not enabled:
            assert self.report.status == SignalReport.Status.READY
            assert self.report.monitoring_started_at is None
            assert check.status == SignalReportCheck.Status.PENDING
            return
        assert self.report.status == SignalReport.Status.MONITORING
        assert check.measurement_start_at == self.report.monitoring_started_at
        assert collect_due_checks(check.next_run_at) == [check]
        anchor = check.measurement_start_at
        with patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=False):
            with self.captureOnCommitCallbacks(execute=True):
                assert self.client.post(url, {"state": "monitoring"}, format="json").status_code == 200
                assert self.client.post(url, {"state": "resolved"}, format="json").status_code == 200
        check.refresh_from_db()
        assert check.measurement_start_at == anchor

    def test_a_pending_check_is_never_due_while_its_report_is_unresolved(self) -> None:
        self._pending()

        # Well past the soak, but the clock has not started: the report is still open.
        assert collect_due_checks(timezone.now() + timedelta(days=7)) == []

    @parameterized.expand([("metric", "metric_threshold"), ("agent", "agent")])
    def test_restoring_monitoring_starts_a_fresh_window_even_when_the_flag_is_off(self, _name: str, kind: str) -> None:
        check = create_check(
            report=self.report,
            title="Verify the fix",
            kind=kind,
            config=_threshold_config() if kind == "metric_threshold" else {"instructions": "Verify the fix."},
            attribution=ArtefactAttribution.system(),
            soak_minutes=DEFAULT_CHECK_SOAK_HOURS * 60,
        )
        with patch("products.signals.backend.report_content_gates.team_report_monitoring_enabled", return_value=True):
            with self.captureOnCommitCallbacks(execute=True):
                self.report.save(update_fields=self.report.transition_to(SignalReport.Status.MONITORING))
        first_anchor = self.report.monitoring_started_at
        self.report.save(update_fields=self.report.transition_to(SignalReport.Status.SUPPRESSED))
        assert self.report.monitoring_started_at is None
        with time_machine.travel(timezone.now() + timedelta(days=10), tick=False):
            restored_at = timezone.now()
            with patch(
                "products.signals.backend.report_content_gates.team_report_monitoring_enabled", return_value=False
            ):
                with self.captureOnCommitCallbacks(execute=True):
                    self.report.save(update_fields=self.report.transition_to(self.report.restore_target_status()))
        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.ACTIVE
        assert check.measurement_start_at == self.report.monitoring_started_at == restored_at
        assert check.measurement_start_at != first_anchor
        assert check.next_run_at > restored_at

    def test_resolving_the_report_waits_for_a_full_query_window_after_the_soak(self) -> None:
        check = self._pending()
        before = timezone.now()

        self._resolve()

        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.ACTIVE
        assert check.measurement_start_at is not None
        assert before <= check.measurement_start_at <= timezone.now()
        assert check.soak_minutes == DEFAULT_CHECK_SOAK_HOURS * 60
        assert check.next_run_at == metric_check_ready_at(_PAGEVIEWS, self.team, check.measurement_start_at)
        assert collect_due_checks(check.next_run_at + timedelta(minutes=1)) == [check]

    @parameterized.expand(
        [
            # Every resolve path ends in the same save, which is why the arming hangs off the model
            # rather off each caller: a merged pull request, a person in the inbox, and an MCP state
            # write all have to start the same clock.
            ("merged_pull_request", {"_status_from_pr_state": True}),
            ("resolved_by_a_caller", {"_close_pr_on_resolve": True}),
            ("resolved_with_no_marker", {}),
        ]
    )
    def test_every_resolve_path_starts_the_clock(self, _name: str, markers: dict) -> None:
        check = self._pending()

        with self.captureOnCommitCallbacks(execute=True):
            for marker, value in markers.items():
                setattr(self.report, marker, value)
            self.report.status = SignalReport.Status.RESOLVED
            self.report.save(update_fields=["status"])

        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.ACTIVE

    def test_an_edit_after_the_resolve_does_not_re_arm_an_answered_check(self) -> None:
        check = self._pending()
        self._resolve()
        check.refresh_from_db()
        armed_at = check.next_run_at

        with self.captureOnCommitCallbacks(execute=True):
            self.report.title = "Fix, retitled"
            self.report.save(update_fields=["title"])

        check.refresh_from_db()
        assert check.next_run_at == armed_at

    def test_longer_soak_and_agent_timing_are_preserved(self) -> None:
        metric = create_check(
            report=self.report,
            title="Short metric",
            kind="metric_threshold",
            config=_threshold_config(
                query=trends_metric_query(series=[{"kind": "EventsNode", "event": "$pageview"}], date_from="-1d")
            ),
            attribution=ArtefactAttribution.system(),
            soak_minutes=3 * 24 * 60,
        )
        agent = create_check(
            report=self.report,
            title="Investigate",
            kind="agent",
            config={"instructions": "Look for the exception."},
            attribution=ArtefactAttribution.system(),
            soak_minutes=24 * 60,
        )
        resolved_at = timezone.now()
        with time_machine.travel(resolved_at, tick=False), self.captureOnCommitCallbacks(execute=True):
            self.report.save(update_fields=self.report.transition_to(SignalReport.Status.RESOLVED))
        metric.refresh_from_db()
        agent.refresh_from_db()
        assert metric.next_run_at == resolved_at + timedelta(days=3)
        assert agent.next_run_at == resolved_at + timedelta(days=1)
        assert agent.measurement_start_at is None

    @parameterized.expand(
        [
            ("long_query_window", "-365d", 60, None, 1),
            ("long_recurring_schedule", "-40d", 60, 30 * 24 * 60, 3),
        ]
    )
    def test_measurement_schedule_outside_the_horizon_is_rejected_before_resolution(
        self, _name: str, date_from: str, soak_minutes: int, interval: int | None, runs: int
    ) -> None:
        log_count = SignalReportArtefact.objects.filter(report=self.report).count()
        with self.assertRaisesRegex(CheckCreationError, "90-day horizon"):
            create_check(
                report=self.report,
                title="Unreachable metric",
                kind="metric_threshold",
                config=_threshold_config(
                    query=trends_metric_query(
                        series=[{"kind": "EventsNode", "event": "$pageview"}], date_from=date_from
                    )
                ),
                attribution=ArtefactAttribution.system(),
                soak_minutes=soak_minutes,
                run_interval_minutes=interval,
                runs_remaining=runs,
            )
        assert not SignalReportCheck.objects.for_team(self.team.id).filter(report=self.report).exists()
        assert SignalReportArtefact.objects.filter(report=self.report).count() == log_count

    def test_invalid_legacy_config_does_not_prevent_other_checks_from_arming(self) -> None:
        invalid = self._pending()
        valid = self._pending()
        SignalReportCheck.objects.for_team(self.team.id).filter(id=invalid.id).update(config={})
        self._resolve()
        invalid.refresh_from_db()
        valid.refresh_from_db()
        assert invalid.status == valid.status == SignalReportCheck.Status.ACTIVE
        assert valid.measurement_start_at is not None
        assert valid.next_run_at == metric_check_ready_at(_PAGEVIEWS, self.team, valid.measurement_start_at)

    def test_a_pending_check_retires_when_its_report_never_resolves(self) -> None:
        check = self._pending()

        assert expire_overdue_checks(timezone.now() + MAX_CHECK_HORIZON + timedelta(minutes=1)) == 1

        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.EXPIRED

    def test_pending_checks_count_against_the_reports_limit(self) -> None:
        for _ in range(MAX_ACTIVE_CHECKS_PER_REPORT):
            self._pending()

        with self.assertRaises(CheckCreationError):
            self._pending()

    def test_a_check_naming_a_metric_the_report_does_not_have_is_refused(self) -> None:
        with self.assertRaises(CheckCreationError):
            create_check(
                report=self.report,
                title="Checkout errors stay low",
                kind=SignalReportCheck.Kind.METRIC_THRESHOLD,
                config={"metric_id": "checkout-errors", "comparison": {"operator": "lte", "value": 10}},
                attribution=ArtefactAttribution.system(),
                soak_minutes=60,
            )


class TestFailedCheckResurfaces(APIBaseTest):
    """What happens when a deterministic check breaches on a report nobody is looking at any more."""

    def setUp(self) -> None:
        super().setUp()
        self.report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.RESOLVED, title="Checkout 500s"
        )

    def _check(self, **overrides) -> SignalReportCheck:
        now = timezone.now()
        fields: dict = {
            "team": self.team,
            "report": self.report,
            "title": "Checkout errors stay low",
            "kind": SignalReportCheck.Kind.METRIC_THRESHOLD,
            "config": _threshold_config(baseline_value=40.0),
            "measurement_start_at": now - timedelta(days=32),
            "next_run_at": now - timedelta(minutes=1),
            "expires_at": now + timedelta(days=30),
        }
        fields.update(overrides)
        return SignalReportCheck.objects.for_team(self.team.id).create(**fields)

    def _run_and_capture(self, check: SignalReportCheck, *, value: float):
        with patch(_EMIT_SIGNAL, new=AsyncMock(return_value=None)) as emit:
            with self.captureOnCommitCallbacks(execute=True):
                with patch(
                    _MEASURE, return_value=MetricMeasurement(value=value, measured_at=timezone.now(), series=None)
                ):
                    record_check_verdict(check, measure_check(check, deadline=time.monotonic() + 30))
        return emit

    def test_a_breach_on_a_resolved_report_emits_one_signal_naming_the_origin(self) -> None:
        check = self._check()

        emit = self._run_and_capture(check, value=42.0)

        assert emit.call_count == 1
        sent = emit.call_args.kwargs
        assert sent["source_product"] == SignalSourceProduct.SIGNALS_CHECK
        assert sent["source_type"] == SignalSourceType.CHECK_FAILED
        assert sent["extra"]["report_id"] == str(self.report.id)
        assert sent["extra"]["check_id"] == str(check.id)
        assert sent["extra"]["baseline_value"] == 40.0
        assert str(self.report.id) in sent["description"]

    def test_the_breach_signal_clears_both_gates_inside_emission(self) -> None:
        # `_run_and_capture` mocks `emit_signal` away, so no test above reaches the two gates inside
        # it. Both refuse this pair by default: `check_failed` is deliberately absent from the
        # configurable `SourceType` set, so a row-backed enable check can never pass, and an
        # unregistered input variant makes `validate_signal_input` raise "Unknown signal type".
        # The producer logs and swallows either one, so the whole follow-up-check path goes quiet.
        check = self._check()
        client = AsyncMock()

        with (
            patch(_ASYNC_CONNECT, return_value=client),
            patch(_MEASURE, return_value=MetricMeasurement(value=42.0, measured_at=timezone.now(), series=None)),
            self.captureOnCommitCallbacks(execute=True),
        ):
            record_check_verdict(check, measure_check(check, deadline=time.monotonic() + 30))

        emitted = [
            call.args[1].signal
            for call in client.start_workflow.call_args_list
            if isinstance(call.args[1], SignalEmitterInput)
        ]
        assert [(signal.source_product, signal.source_type) for signal in emitted] == [
            (SignalSourceProduct.SIGNALS_CHECK, SignalSourceType.CHECK_FAILED)
        ]
        assert emitted[0].extra["report_id"] == str(self.report.id)

    def test_a_breach_on_a_report_still_being_worked_emits_nothing(self) -> None:
        SignalReport.objects.filter(id=self.report.id).update(status=SignalReport.Status.READY)
        check = self._check()
        check.refresh_from_db()

        emit = self._run_and_capture(check, value=42.0)

        assert emit.call_count == 0

    def test_a_pass_on_a_resolved_report_emits_nothing(self) -> None:
        check = self._check()

        emit = self._run_and_capture(check, value=1.0)

        assert emit.call_count == 0

    def test_an_agent_check_breach_emits_nothing_because_its_scout_can_file(self) -> None:
        check = self._check(
            kind=SignalReportCheck.Kind.AGENT,
            config={"instructions": "Re-read the issue."},
            dispatched_at=timezone.now(),
        )

        with patch(_EMIT_SIGNAL, new=AsyncMock(return_value=None)) as emit:
            with self.captureOnCommitCallbacks(execute=True):
                record_check_verdict(check, CheckVerdict(outcome="failed", explanation="Still firing."))

        assert emit.call_count == 0


class TestScoutCheckTools(APIBaseTest):
    """`scout-report-check-create` / `-list` / `-cancel`: what a run may write, read, and stop."""

    def setUp(self) -> None:
        super().setUp()
        self.report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="Checkout 500s"
        )
        self.scout_config = SignalScoutConfig.objects.create(
            team=self.team,
            skill_name=FALLBACK_CHECK_SKILL_NAME,
            status=SignalScoutConfig.Status.ACTIVE,
            enabled=True,
        )
        self.task = Task.objects.create(team=self.team, title="t", description="d")
        task_run = TaskRun.objects.create(task=self.task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        self.scout_run = SignalScoutRun.objects.create(
            task_run=task_run,
            team=self.team,
            scout_config=self.scout_config,
            skill_name=FALLBACK_CHECK_SKILL_NAME,
            skill_version=1,
        )

    def _create(self, **overrides):
        now = timezone.now()
        payload: dict = {
            "report_id": str(self.report.id),
            "title": "Checkout errors stay low",
            "kind": SignalReportCheck.Kind.METRIC_THRESHOLD,
            "config": _threshold_config(baseline_value=40.0),
            "next_run_at": now + timedelta(days=3),
            "expires_at": now + timedelta(days=60),
        }
        payload.update(overrides)
        return create_report_check(team=self.team, run=self.scout_run, **payload)

    def test_a_written_check_is_attributed_to_the_runs_task(self) -> None:
        summary = self._create()

        check = SignalReportCheck.objects.for_team(self.team.id).get(id=summary.check_id)
        assert check.task_id == self.task.id
        assert check.report_id == self.report.id

    @parameterized.expand([(SignalReport.Status.READY,), (SignalReport.Status.SUPPRESSED,)])
    def test_a_check_on_an_unresolved_report_waits_for_the_resolve(self, report_status: str) -> None:
        self.report.status = report_status
        self.report.save(update_fields=["status"])

        check = SignalReportCheck.objects.for_team(self.team.id).get(id=self._create().check_id)

        assert check.status == SignalReportCheck.Status.PENDING
        # The gap the run left before its date is what the check waits out after the resolve.
        assert check.soak_minutes == 3 * 24 * 60
        assert collect_due_checks(timezone.now() + timedelta(days=7)) == []

    def test_the_resolve_starts_the_clock_on_a_check_a_run_dated(self) -> None:
        check = SignalReportCheck.objects.for_team(self.team.id).get(id=self._create().check_id)
        before = timezone.now()

        with self.captureOnCommitCallbacks(execute=True):
            self.report.status = SignalReport.Status.RESOLVED
            self.report.save(update_fields=["status"])

        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.ACTIVE
        assert check.measurement_start_at is not None
        assert before <= check.measurement_start_at <= timezone.now()
        assert check.soak_minutes == 3 * 24 * 60
        assert check.next_run_at == metric_check_ready_at(_PAGEVIEWS, self.team, check.measurement_start_at)

    def test_a_recurring_check_keeps_its_initial_soak_after_reopening(self) -> None:
        self.report.status = SignalReport.Status.RESOLVED
        self.report.save(update_fields=["status"])
        first_run = timezone.now() + timedelta(days=3)

        check = SignalReportCheck.objects.for_team(self.team.id).get(
            id=self._create(next_run_at=first_run, run_interval_minutes=24 * 60, runs_remaining=3).check_id
        )

        assert check.status == SignalReportCheck.Status.ACTIVE
        assert check.measurement_start_at is not None
        assert check.next_run_at == metric_check_ready_at(_PAGEVIEWS, self.team, check.measurement_start_at)
        assert check.soak_minutes == 3 * 24 * 60
        record_check_verdict(check, CheckVerdict(outcome="passed", explanation="held"), now=first_run)
        self.report.status = SignalReport.Status.READY
        self.report.save(update_fields=["status"])
        run_due_report_checks(now=first_run + timedelta(hours=1))

        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.PENDING
        assert check.soak_minutes == 3 * 24 * 60

    def test_a_date_beyond_the_longest_soak_becomes_the_longest_soak(self) -> None:
        check = SignalReportCheck.objects.for_team(self.team.id).get(
            id=self._create(next_run_at=timezone.now() + timedelta(days=60)).check_id
        )

        assert check.soak_minutes == MAX_CHECK_SOAK_HOURS * 60

    def test_a_run_reads_back_the_checks_it_would_otherwise_duplicate(self) -> None:
        written = self._create()

        listed = list_report_checks(team=self.team, report_id=str(self.report.id))

        assert [summary.check_id for summary in listed] == [written.check_id]

    def test_cancelling_stops_the_check_and_refuses_a_second_cancel(self) -> None:
        written = self._create(kind=SignalReportCheck.Kind.AGENT, config={"instructions": "Re-read the issue."})
        SignalReportCheck.objects.for_team(self.team.id).filter(id=written.check_id).update(
            status=SignalReportCheck.Status.ACTIVE, dispatched_at=timezone.now() - timedelta(days=30)
        )
        self.scout_run.metadata = {"check_id": written.check_id}
        self.scout_run.save(update_fields=["metadata"])

        cancelled = cancel_report_check(team=self.team, run=self.scout_run, check_id=written.check_id)

        assert (cancelled.status, cancelled.waiting_on_run) == (SignalReportCheck.Status.CANCELLED, False)
        (listed,) = list_report_checks(team=self.team, report_id=str(self.report.id))
        assert (listed.run_state, listed.waiting_on_run, listed.dispatched_run_id) == (
            SignalReportCheck.Status.CANCELLED,
            False,
            None,
        )
        with self.assertRaises(InvalidCheckWriteError):
            cancel_report_check(team=self.team, run=self.scout_run, check_id=written.check_id)

    def test_a_dry_run_scout_neither_writes_nor_cancels_a_check(self) -> None:
        written = self._create()
        self.scout_config.emit = False
        self.scout_config.save(update_fields=["emit"])

        with self.assertRaises(InvalidCheckWriteError):
            self._create(title="Written by a preview run")
        with self.assertRaises(InvalidCheckWriteError):
            cancel_report_check(team=self.team, run=self.scout_run, check_id=written.check_id)

        check = SignalReportCheck.objects.for_team(self.team.id).get()
        assert check.status == SignalReportCheck.Status.PENDING

    def test_another_projects_report_is_not_reachable(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        other_report = SignalReport.objects.create(team=other_team, status=SignalReport.Status.READY, title="theirs")

        with self.assertRaises(InvalidCheckWriteError):
            self._create(report_id=str(other_report.id))


class TestResearchAuthoredChecks(APIBaseTest):
    """The verification turn's specs, written alongside the metrics they measure."""

    def setUp(self) -> None:
        super().setUp()
        self.report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Checkout 500s",
            metrics=[{"metric_id": "checkout-errors", "title": "Checkout errors", "query": _PAGEVIEWS}],
        )

    def _spec(self, **overrides) -> CheckSpec:
        payload: dict = {
            "title": "Checkout errors stay under 10 a day",
            "kind": "metric_threshold",
            "config": {
                "metric_id": "checkout-errors",
                "comparison": {"operator": "lte", "value": 10},
                "baseline_value": 40.0,
            },
        }
        payload.update(overrides)
        return CheckSpec.model_validate(payload)

    def test_a_spec_becomes_a_pending_check_carrying_the_metrics_query(self) -> None:
        with patch(_CAPTURE) as capture, self.captureOnCommitCallbacks(execute=True):
            written = create_checks_from_specs(
                report=self.report, specs=[self._spec()], attribution=ArtefactAttribution.system()
            ).created

        assert len(written) == 1
        check = written[0]
        assert check.status == SignalReportCheck.Status.PENDING
        assert check.soak_minutes == DEFAULT_CHECK_SOAK_HOURS * 60
        assert check.config["query"] == _PAGEVIEWS
        assert capture.call_args.kwargs["event"] == "signals_report_check_created"
        assert capture.call_args.kwargs["properties"]["check_status"] == SignalReportCheck.Status.PENDING

    def test_a_newer_research_pass_replaces_the_pending_checks_of_an_older_one(self) -> None:
        older = create_checks_from_specs(
            report=self.report, specs=[self._spec()], attribution=ArtefactAttribution.system()
        ).created
        newer = create_checks_from_specs(
            report=self.report,
            specs=[self._spec(title="Checkout errors stay under 5 a day")],
            attribution=ArtefactAttribution.system(),
        ).created
        create_checks_from_specs(report=self.report, specs=[], attribution=ArtefactAttribution.system())

        older[0].refresh_from_db()
        newer[0].refresh_from_db()
        assert older[0].status == SignalReportCheck.Status.CANCELLED
        assert newer[0].status == SignalReportCheck.Status.CANCELLED

    @parameterized.expand(
        [
            ("current_config", False, "unchanged"),
            ("config_written_before_display_fields", True, "unchanged"),
            ("revise_approved", False, "revise"),
            ("retire_approved", False, "retire"),
            ("omitted_metric_defaults", False, "unchanged", "metric_defaults"),
            ("omitted_agent_defaults", False, "unchanged", "agent_defaults"),
            ("revise_recurring", False, "revise", "recurring"),
            ("omitted_existing_wait", False, "unchanged", "omitted_wait"),
            ("revise_omitted_existing_wait", False, "revise", "omitted_wait"),
            ("longer_wait", False, "revise", "longer_wait"),
            ("invalid_stored_config", False, "revise", "invalid_stored"),
        ]
    )
    def test_research_reviews_approved_checks(
        self, _name: str, legacy_config: bool, action: str, variant: str = ""
    ) -> None:
        spec = self._spec()
        if variant == "metric_defaults":
            spec.config["baseline_value"] = None
        elif variant == "agent_defaults":
            spec = self._spec(kind="agent", config={"instructions": "Check the issue again."})
        existing = create_checks_from_specs(
            report=self.report, specs=[spec], attribution=ArtefactAttribution.system()
        ).created[0]
        approved_at = timezone.now()
        stored_config = dict(existing.config)
        if variant == "metric_defaults":
            stored_config["comparison"]["bounds"] = None
            stored_config.pop("baseline_value")
        elif variant == "agent_defaults":
            stored_config.update(probe_hints=[], skill_name=None)
        if variant == "invalid_stored":
            stored_config["retired_config_field"] = "obsolete"
        if variant == "omitted_wait":
            SignalReportCheck.objects.for_team(self.team.id).filter(id=existing.id).update(soak_minutes=72 * 60)
        if variant == "recurring":
            SignalReportCheck.objects.for_team(self.team.id).filter(id=existing.id).update(
                soak_minutes=1450, run_interval_minutes=7 * 24 * 60, runs_remaining=3
            )
        if legacy_config:
            stored_config = {
                key: value for key, value in stored_config.items() if key not in {"metric_kind", "value_format", "unit"}
            }
        SignalReportCheck.objects.for_team(self.team.id).filter(id=existing.id).update(
            approved_at=approved_at, config=stored_config
        )
        existing.refresh_from_db()
        original_schedule = (existing.next_run_at, existing.expires_at, existing.updated_at)
        specs = (
            []
            if action == "retire"
            else [self._spec(title="Revised goal", existing_check_id=existing.id)]
            if action == "revise"
            else [spec]
        )

        if variant == "omitted_wait":
            specs[0] = self._spec(title=specs[0].title, existing_check_id=existing.id)
        if variant == "invalid_stored":
            specs = [self._spec(existing_check_id=existing.id)]
        elif variant == "longer_wait":
            specs[0] = specs[0].model_copy(update={"soak_hours": 72})
        written = create_checks_from_specs(
            report=self.report,
            specs=specs,
            attribution=ArtefactAttribution.system(),
            checks_snapshot=check_versions([existing]),
        ).created

        existing.refresh_from_db()
        assert existing.status == (
            SignalReportCheck.Status.PENDING if action == "unchanged" else SignalReportCheck.Status.CANCELLED
        )
        assert existing.approved_at == approved_at
        if action == "unchanged":
            assert (existing.next_run_at, existing.expires_at, existing.updated_at) == original_schedule
        assert len(written) == (1 if action == "revise" else 0)
        if written:
            assert written[0].title == (spec.title if variant == "invalid_stored" else "Revised goal")
            assert written[0].approved_at is None
            assert written[0].soak_minutes == (72 * 60 if variant == "longer_wait" else existing.soak_minutes)
            assert written[0].run_interval_minutes == existing.run_interval_minutes
            assert written[0].runs_remaining == existing.runs_remaining
        assert SignalReportCheck.objects.for_team(self.team.id).filter(report=self.report).count() == (
            2 if action == "revise" else 1
        )

    def test_terminal_check_during_reconciliation_does_not_drop_new_specs(self) -> None:
        older = create_checks_from_specs(
            report=self.report, specs=[self._spec()], attribution=ArtefactAttribution.system()
        ).created[0]

        def expire_before_cancel(check: SignalReportCheck, **kwargs) -> bool:
            SignalReportCheck.objects.for_team(self.team.id).filter(id=check.id).update(
                status=SignalReportCheck.Status.EXPIRED
            )
            return cancel_check(check, **kwargs)

        with patch("products.signals.backend.report_check_authoring.cancel_check", side_effect=expire_before_cancel):
            newer = create_checks_from_specs(
                report=self.report,
                specs=[self._spec(title="Replacement goal")],
                attribution=ArtefactAttribution.system(),
            ).created
        older.refresh_from_db()
        assert older.status == SignalReportCheck.Status.EXPIRED
        assert len(newer) == 1
        assert newer[0].title == "Replacement goal"
        assert newer[0].status == SignalReportCheck.Status.PENDING

    @parameterized.expand(
        [
            ("replacement",),
            ("external_agent",),
            ("approval",),
            ("replacement_during_research", True),
            ("approval_during_research", True),
            ("task_check_during_research", True),
        ]
    )
    def test_research_preserves_person_selected_pending_checks(
        self, selection: str, capture_snapshot: bool = False
    ) -> None:
        original = create_checks_from_specs(
            report=self.report,
            specs=[self._spec()],
            attribution=ArtefactAttribution.from_agent(self.user.id, "test-client")
            if selection == "external_agent"
            else ArtefactAttribution.system(),
        ).created[0]
        snapshot = check_versions([original]) if capture_snapshot else None
        url = f"/api/projects/{self.team.id}/signals/reports/{self.report.id}/checks/{original.id}/"
        if selection.startswith("replacement"):
            response = self.client.post(
                f"{url}replace/",
                {"title": "Person-selected goal", "config": self._spec().config},
                format="json",
            )
            assert response.status_code == status.HTTP_200_OK, response.json()
        elif selection.startswith("approval"):
            response = self.client.post(f"{url}approve/")
            assert response.status_code == status.HTTP_200_OK, response.json()
        elif selection == "task_check_during_research":
            create_check(
                report=self.report,
                title="Task-selected goal",
                rationale="",
                kind="metric_threshold",
                config=self._spec().config,
                attribution=ArtefactAttribution.from_task(
                    str(Task.objects.create(team=self.team, title="Select a check", description="").id)
                ),
                soak_minutes=60,
            )
        checks = SignalReportCheck.objects.for_team(self.team.id).filter(report=self.report).order_by("id")
        selected_state = list(checks.values())
        log_count = SignalReportArtefact.objects.filter(report=self.report).count()

        create_checks_from_specs(
            report=self.report,
            specs=[self._spec(title="New research goal")],
            attribution=ArtefactAttribution.system(),
            checks_snapshot=snapshot,
        )

        assert list(checks.values()) == selected_state
        assert SignalReportArtefact.objects.filter(report=self.report).count() == log_count

    def test_research_keeps_a_check_with_a_minute_level_soak(self) -> None:
        existing = create_checks_from_specs(
            report=self.report, specs=[self._spec()], attribution=ArtefactAttribution.system()
        ).created[0]
        SignalReportCheck.objects.for_team(self.team.id).filter(id=existing.id).update(soak_minutes=1450)

        assert (
            create_checks_from_specs(
                report=self.report, specs=[self._spec()], attribution=ArtefactAttribution.system()
            ).created
            == []
        )

        existing.refresh_from_db()
        assert existing.status == SignalReportCheck.Status.PENDING
        assert existing.soak_minutes == 1450

    def test_a_spec_naming_a_metric_the_report_does_not_have_is_dropped(self) -> None:
        written = create_checks_from_specs(
            report=self.report,
            specs=[self._spec(config={"metric_id": "invented", "comparison": {"operator": "lte", "value": 10}})],
            attribution=ArtefactAttribution.system(),
        ).created

        assert written == []
        assert not SignalReportCheck.objects.for_team(self.team.id).filter(report=self.report).exists()

    def test_a_spec_written_after_the_report_resolved_starts_its_soak_at_once(self) -> None:
        self.report.status = SignalReport.Status.RESOLVED
        self.report.save(update_fields=["status"])
        before = timezone.now()

        written = create_checks_from_specs(
            report=self.report, specs=[self._spec()], attribution=ArtefactAttribution.system()
        ).created

        assert written[0].status == SignalReportCheck.Status.ACTIVE
        assert written[0].measurement_start_at is not None
        assert before <= written[0].measurement_start_at <= timezone.now()
        assert written[0].soak_minutes == DEFAULT_CHECK_SOAK_HOURS * 60
        assert written[0].next_run_at == metric_check_ready_at(_PAGEVIEWS, self.team, written[0].measurement_start_at)

    def test_a_longer_soak_is_honoured_for_a_fix_that_reaches_users_slowly(self) -> None:
        written = create_checks_from_specs(
            report=self.report, specs=[self._spec(soak_hours=72)], attribution=ArtefactAttribution.system()
        ).created

        assert written[0].soak_minutes == 72 * 60

    @parameterized.expand(
        [
            ("no_baseline_is_still_a_check", {"comparison": {"operator": "lte", "value": 10}}, True),
            ("a_config_that_does_not_match_the_kind", {"instructions": "look at it"}, False),
        ]
    )
    def test_a_spec_must_carry_a_config_its_kind_accepts(self, _name: str, config: dict, valid: bool) -> None:
        payload = {"title": "t", "kind": "metric_threshold", "config": {"metric_id": "checkout-errors", **config}}
        if valid:
            assert CheckSpec.model_validate(payload).kind == "metric_threshold"
        else:
            with self.assertRaises(PydanticValidationError):
                CheckSpec.model_validate(payload)


class TestReportCheckLifecycleLog(APIBaseTest):
    """The activity entries a check leaves other than its verdict.

    Without them the log is silent for the whole soak window, which is the stretch a reader most
    wants explained: a check that never ran and one that was stopped both read as "nothing
    happened".
    """

    def setUp(self) -> None:
        super().setUp()
        self.report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.RESOLVED, title="Fix")
        self.url = f"/api/projects/{self.team.id}/signals/reports/{self.report.id}/checks/"

    def _create(self, **overrides) -> SignalReportCheck:
        spec: dict = {
            "title": "Checkout errors stay low",
            "kind": SignalReportCheck.Kind.METRIC_THRESHOLD,
            "config": _threshold_config(),
            "next_run_at": timezone.now() + timedelta(days=7),
        }
        spec.update(overrides)
        return create_check(report=self.report, attribution=ArtefactAttribution.system(), **spec)

    def _entries(self, artefact_type: str, report: SignalReport | None = None) -> list[dict]:
        return [
            json.loads(artefact.content)
            for artefact in SignalReportArtefact.objects.filter(
                report=report or self.report, type=artefact_type
            ).order_by("created_at")
        ]

    def test_writing_a_check_opens_the_log_with_its_date_and_its_lane(self) -> None:
        check = self._create(
            kind=SignalReportCheck.Kind.AGENT,
            config={"instructions": "Read the issue again.", "skill_name": "signals-scout-error-tracking"},
        )

        entries = self._entries(SignalReportArtefact.ArtefactType.CHECK_SCHEDULED)
        assert len(entries) == 1
        assert entries[0]["check_id"] == str(check.id)
        assert entries[0]["title"] == "Checkout errors stay low"
        assert entries[0]["skill_name"] == "signals-scout-error-tracking"
        assert entries[0]["arms_on_resolve"] is False
        assert entries[0]["next_run_at"] == check.next_run_at.isoformat()

    def test_a_check_waiting_on_the_resolve_says_so_and_is_not_logged_twice_when_armed(self) -> None:
        open_report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY, title="Open")
        check = create_check(
            report=open_report,
            title="Checkout errors stay low",
            kind=SignalReportCheck.Kind.METRIC_THRESHOLD,
            config=_threshold_config(),
            soak_minutes=DEFAULT_CHECK_SOAK_HOURS * 60,
            attribution=ArtefactAttribution.system(),
        )

        with self.captureOnCommitCallbacks(execute=True):
            open_report.save(update_fields=open_report.transition_to(SignalReport.Status.RESOLVED))

        entries = self._entries(SignalReportArtefact.ArtefactType.CHECK_SCHEDULED, open_report)
        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.ACTIVE
        assert len(entries) == 1
        assert entries[0]["arms_on_resolve"] is True
        assert entries[0]["soak_minutes"] == DEFAULT_CHECK_SOAK_HOURS * 60

    def test_the_sweep_logs_each_check_it_retires_and_says_it_never_ran(self) -> None:
        check = self._create()
        SignalReportCheck.objects.for_team(self.team.id).filter(id=check.id).update(
            expires_at=timezone.now() - timedelta(days=1)
        )

        assert expire_overdue_checks(timezone.now()) == 1

        entries = self._entries(SignalReportArtefact.ArtefactType.CHECK_EXPIRED)
        assert len(entries) == 1
        assert entries[0]["check_id"] == str(check.id)
        assert entries[0]["last_run_at"] is None

    def test_the_sweep_logs_nothing_for_a_check_whose_report_resolved_under_it(self) -> None:
        overdue = self._create()
        SignalReportCheck.objects.for_team(self.team.id).filter(id=overdue.id).update(
            expires_at=timezone.now() - timedelta(days=1)
        )
        armed = self._create(title="Still watched")

        assert expire_overdue_checks(timezone.now()) == 1

        entries = self._entries(SignalReportArtefact.ArtefactType.CHECK_EXPIRED)
        armed.refresh_from_db()
        assert armed.status == SignalReportCheck.Status.ACTIVE
        assert [entry["check_id"] for entry in entries] == [str(overdue.id)]

    def test_stopping_a_check_from_the_report_logs_who_stopped_it(self) -> None:
        check = self._create()

        cancelled = self.client.delete(f"{self.url}{check.id}/")

        assert cancelled.status_code == status.HTTP_200_OK
        entries = self._entries(SignalReportArtefact.ArtefactType.CHECK_CANCELLED)
        assert len(entries) == 1
        assert entries[0]["check_id"] == str(check.id)
        assert entries[0]["reason"] == "stopped_by_person"

    def test_a_refused_cancel_logs_nothing(self) -> None:
        check = self._create()
        SignalReportCheck.objects.for_team(self.team.id).filter(id=check.id).update(
            status=SignalReportCheck.Status.PASSED
        )

        refused = self.client.delete(f"{self.url}{check.id}/")

        assert refused.status_code == status.HTTP_400_BAD_REQUEST
        assert self._entries(SignalReportArtefact.ArtefactType.CHECK_CANCELLED) == []

    def test_a_re_research_pass_logs_the_pending_checks_it_replaced(self) -> None:
        open_report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY, title="Open")
        replaced = create_check(
            report=open_report,
            title="Checkout errors stay low",
            kind=SignalReportCheck.Kind.METRIC_THRESHOLD,
            config=_threshold_config(),
            soak_minutes=DEFAULT_CHECK_SOAK_HOURS * 60,
            attribution=ArtefactAttribution.system(),
        )

        create_checks_from_specs(
            report=open_report,
            specs=[
                CheckSpec.model_validate(
                    {
                        "title": "Checkout errors stay under 5 a day",
                        "rationale": "The retry fix should hold.",
                        "kind": "metric_threshold",
                        "config": {"query": _PAGEVIEWS, "comparison": {"operator": "lte", "value": 5}},
                    }
                )
            ],
            attribution=ArtefactAttribution.system(),
        )

        entries = self._entries(SignalReportArtefact.ArtefactType.CHECK_CANCELLED, open_report)
        assert len(entries) == 1
        assert entries[0]["check_id"] == str(replaced.id)
        assert entries[0]["reason"] == "replaced_by_research"
