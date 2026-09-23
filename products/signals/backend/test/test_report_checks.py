import json
import time
from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError
from rest_framework import status
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.constants import AvailableFeature
from posthog.models import PropertyDefinition, Team

from products.access_control.backend.facade.contracts import PropertyAccessLevel
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import Dismissal
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
    resolve_check_skill_name,
)
from products.signals.backend.report_check_authoring import (
    CheckCreationError,
    arm_pending_checks,
    create_check,
    create_checks_from_specs,
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
from products.signals.backend.report_checks import (
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
    AgentCheckConfig,
    CheckComparison,
    CheckConfigValidationError,
    CheckSpec,
    MetricThresholdConfig,
    parse_check_config,
)
from products.signals.backend.report_metric_refresh import MetricMeasurement
from products.signals.backend.scout_harness.tools.checks import (
    InvalidCheckResultError,
    InvalidCheckWriteError,
    cancel_report_check,
    create_report_check,
    list_report_checks,
    record_check_result,
)
from products.signals.backend.serializers import CHECK_RESULT_HIDDEN_EXPLANATION, SignalReportCheckWriteSerializer
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
            patch(_MEASURE, return_value=MetricMeasurement(value=42.0, measured_at=timezone.now(), series=None)),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                run_due_report_checks()

        assert capture.call_count == 1
        properties = capture.call_args.kwargs["properties"]
        assert capture.call_args.kwargs["event"] == "signals_report_check_evaluated"
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

    def test_a_suppressed_report_pauses_its_checks(self) -> None:
        self._check()
        self.report.status = SignalReport.Status.SUPPRESSED
        self.report.save(update_fields=["status"])
        assert collect_due_checks(timezone.now()) == []

        self.report.status = SignalReport.Status.RESOLVED
        self.report.save(update_fields=["status"])
        assert len(collect_due_checks(timezone.now())) == 1

    def test_a_check_cancelled_while_its_query_ran_records_nothing(self) -> None:
        check = self._check()
        check.status = SignalReportCheck.Status.CANCELLED
        check.save(update_fields=["status"])

        record_check_verdict(check, CheckVerdict(outcome="passed", explanation="held", observed_value=1.0))

        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.CANCELLED
        assert self._results() == []

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
        check_id = str(self._create().id)

        listed = self.client.get(self.url)
        assert [row["id"] for row in listed.json()["results"]] == [check_id]
        assert listed.json()["results"][0]["config"]["query"] == _PAGEVIEWS

        cancelled = self.client.delete(f"{self.url}{check_id}/")
        assert cancelled.status_code == status.HTTP_200_OK
        assert cancelled.json()["status"] == "cancelled"

        already_cancelled = self.client.delete(f"{self.url}{check_id}/")
        assert already_cancelled.status_code == status.HTTP_400_BAD_REQUEST

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
            {"metric_id": "checkout-errors", "title": "Checkout errors", "kind": "occurrences", "query": _PAGEVIEWS}
        ]
        self.report.save(update_fields=["metrics"])
        stored = self._create(config=config)
        assert stored.config["metric_id"] == "checkout-errors"
        assert stored.config["query"] == _PAGEVIEWS

        # Rewriting the metric under the same id must not move the check's target.
        rewritten = trends_metric_query(series=[{"kind": "EventsNode", "event": "$autocapture"}])
        self.report.metrics = [{**self.report.metrics[0], "query": rewritten}]
        self.report.save(update_fields=["metrics"])
        SignalReportCheck.objects.for_team(self.team.id).filter(id=stored.id).update(
            next_run_at=timezone.now() - timedelta(minutes=1)
        )
        with patch(
            _MEASURE, return_value=MetricMeasurement(value=0.0, measured_at=timezone.now(), series=None)
        ) as measure:
            run_due_report_checks()
        assert measure.call_args.args[0] == _PAGEVIEWS

    def test_a_check_created_in_a_child_environment_stays_on_that_environment(self) -> None:
        child = Team.objects.create(organization=self.organization, name="Child", parent_team=self.team)
        report = SignalReport.objects.create(team=child, status=SignalReport.Status.RESOLVED, title="Fix")
        url = f"/api/projects/{child.id}/signals/reports/{report.id}/checks/"

        check_id = str(self._create(report=report).id)

        assert [row["id"] for row in self.client.get(url).json()["results"]] == [check_id]
        assert SignalReportCheck.all_teams.get(id=check_id).team_id == child.id

        SignalReportCheck.all_teams.filter(id=check_id).update(next_run_at=timezone.now() - timedelta(minutes=1))
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
            next_run_at=timezone.now() - timedelta(minutes=1)
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
            ("paused_lane", {"enabled": False, "status": SignalScoutConfig.Status.PAUSED_BY_USER}, "is paused"),
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

    def test_a_check_on_a_scout_a_person_paused_still_reports_the_refusal(self) -> None:
        # A pause is somebody's decision, so saying the check could not run is more honest than
        # quietly answering the question on another scout.
        LLMSkill.objects.create(team=self.team, name="signals-scout-health-checks", is_latest=True, deleted=False)
        SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-health-checks", enabled=False)
        self._check(
            config={
                "instructions": "Re-read the issue and say whether it still fires.",
                "skill_name": "signals-scout-health-checks",
            }
        )

        with patch(_CONNECT), patch(_DISPATCH) as dispatch:
            summary = run_due_report_checks()

        assert summary.errored == 1
        dispatch.assert_not_called()
        assert "is paused" in self._results()[0].content

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

    def test_a_run_that_never_records_a_result_errors_the_check(self) -> None:
        now = timezone.now()
        check = self._check(dispatched_at=now - AGENT_CHECK_RESULT_WINDOW, next_run_at=now - timedelta(minutes=1))

        with patch(_CONNECT), patch(_DISPATCH) as dispatch:
            summary = run_due_report_checks()

        assert summary.errored == 1
        dispatch.assert_not_called()
        check.refresh_from_db()
        assert check.dispatched_at is None
        assert check.consecutive_errors == 1
        assert "ended without recording a result" in self._results()[0].content


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

    def test_a_pass_rearms_a_recurring_check_for_its_next_look(self) -> None:
        check = self._check(run_interval_minutes=MIN_CHECK_INTERVAL_MINUTES, runs_remaining=2)

        result = self._record(check, outcome="passed", explanation="No events since the fix merged.")

        assert result.check_status == SignalReportCheck.Status.ACTIVE
        assert result.runs_remaining == 1
        check.refresh_from_db()
        assert check.dispatched_at is None
        assert check.next_run_at > timezone.now() + timedelta(minutes=MIN_CHECK_INTERVAL_MINUTES - 5)

    @parameterized.expand(
        [
            ("no_run_is_waiting", {"dispatched_at": None}),
            ("already_finished", {"status": SignalReportCheck.Status.CANCELLED}),
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

    @parameterized.expand([("blank_explanation", {"explanation": "  "}), ("unknown_outcome", {"outcome": "maybe"})])
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

    def test_a_pending_check_is_never_due_while_its_report_is_unresolved(self) -> None:
        self._pending()

        # Well past the soak, but the clock has not started: the report is still open.
        assert collect_due_checks(timezone.now() + timedelta(days=7)) == []

    def test_resolving_the_report_arms_the_check_for_resolve_plus_soak(self) -> None:
        check = self._pending()
        before = timezone.now()

        self._resolve()

        check.refresh_from_db()
        assert check.status == SignalReportCheck.Status.ACTIVE
        soak = timedelta(hours=DEFAULT_CHECK_SOAK_HOURS)
        assert before + soak <= check.next_run_at <= timezone.now() + soak
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
            "expires_at": now + timedelta(days=30),
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
        soak = timedelta(days=3)
        assert check.status == SignalReportCheck.Status.ACTIVE
        assert before + soak <= check.next_run_at <= timezone.now() + soak

    def test_a_check_on_a_resolved_report_runs_on_the_date_the_run_named(self) -> None:
        self.report.status = SignalReport.Status.RESOLVED
        self.report.save(update_fields=["status"])
        first_run = timezone.now() + timedelta(days=3)

        check = SignalReportCheck.objects.for_team(self.team.id).get(id=self._create(next_run_at=first_run).check_id)

        assert check.status == SignalReportCheck.Status.ACTIVE
        assert check.next_run_at == first_run
        assert check.soak_minutes is None

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
        written = self._create()

        cancelled = cancel_report_check(team=self.team, run=self.scout_run, check_id=written.check_id)

        assert cancelled.status == SignalReportCheck.Status.CANCELLED
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
            )

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
        )
        newer = create_checks_from_specs(
            report=self.report,
            specs=[self._spec(title="Checkout errors stay under 5 a day")],
            attribution=ArtefactAttribution.system(),
        )
        create_checks_from_specs(report=self.report, specs=[], attribution=ArtefactAttribution.system())

        older[0].refresh_from_db()
        newer[0].refresh_from_db()
        assert older[0].status == SignalReportCheck.Status.CANCELLED
        assert newer[0].status == SignalReportCheck.Status.PENDING

    def test_a_spec_naming_a_metric_the_report_does_not_have_is_dropped(self) -> None:
        written = create_checks_from_specs(
            report=self.report,
            specs=[self._spec(config={"metric_id": "invented", "comparison": {"operator": "lte", "value": 10}})],
            attribution=ArtefactAttribution.system(),
        )

        assert written == []
        assert not SignalReportCheck.objects.for_team(self.team.id).filter(report=self.report).exists()

    def test_a_spec_written_after_the_report_resolved_starts_its_soak_at_once(self) -> None:
        self.report.status = SignalReport.Status.RESOLVED
        self.report.save(update_fields=["status"])
        before = timezone.now()

        written = create_checks_from_specs(
            report=self.report, specs=[self._spec()], attribution=ArtefactAttribution.system()
        )

        # Nothing left to wait for, so the check is armed rather than held for a resolve that already happened.
        soak = timedelta(hours=DEFAULT_CHECK_SOAK_HOURS)
        assert written[0].status == SignalReportCheck.Status.ACTIVE
        assert before + soak <= written[0].next_run_at <= timezone.now() + soak

    def test_a_longer_soak_is_honoured_for_a_fix_that_reaches_users_slowly(self) -> None:
        written = create_checks_from_specs(
            report=self.report, specs=[self._spec(soak_hours=72)], attribution=ArtefactAttribution.system()
        )

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

        arm_pending_checks(team_id=self.team.id, report_id=open_report.id, resolved_at=timezone.now())

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
