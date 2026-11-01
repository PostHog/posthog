import time
from datetime import timedelta
from uuid import uuid4

import time_machine
from posthog.test.base import BaseTest, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.workload import Workload
from posthog.models import Organization, Team

from products.product_analytics.backend.facade.contracts import TrendsQueryRunResult
from products.signals.backend.models import (
    SignalReport,
    SignalReportCheck,
    SignalReportMonitoringAttempt,
    SignalReportMonitoringResult,
)
from products.signals.backend.report_check_execution import run_due_report_checks
from products.signals.backend.report_check_final_candidates import FinalCheck
from products.signals.backend.report_check_final_metrics import collect_due_final_metrics, run_due_final_metrics
from products.signals.backend.report_check_metric_evaluation import metric_evidence_source
from products.signals.backend.report_checks import MAX_CONSECUTIVE_CHECK_ERRORS, MetricThresholdConfig
from products.signals.backend.report_metric_refresh import MetricMeasurement, MetricQueryBudgetExhausted
from products.signals.backend.report_monitoring_attempts import check_definition_version, complete_implementation
from products.signals.backend.test.report_metric_test_fixtures import trends_metric_query

_MEASURE = "products.signals.backend.report_check_metric_evaluation.measure_metric"
_FLAG = "products.signals.backend.report_content_gates.feature_enabled_or_false"


class TestMetricEvidenceAdapter(SimpleTestCase):
    @parameterized.expand(
        [
            ("ratio", "formula", "A / B", "total", "rate"),
            ("trailing_semicolon", "formula", "A / B;", "total", "rate"),
            ("percentage", "formulas", "(A / B) * 100", "total", "rate"),
            ("reverse_percentage", "formulaNodes", "100 * (B / A)", "total", "rate"),
            ("sum_ratio", "formula", "A / B", "sum", "unsupported"),
            ("distinct_ratio", "formula", "A / B", "dau", "unsupported"),
            ("difference", "formula", "A - B", "total", "unsupported"),
            ("self_ratio", "formula", "A / A", "total", "unsupported"),
            ("compound_denominator", "formula", "A / (A + B)", "total", "unsupported"),
        ]
    )
    def test_only_count_ratios_have_a_denominator_adapter(
        self, _name: str, formula_key: str, formula: str, math: str, expected: str
    ) -> None:
        query = trends_metric_query(
            series=[
                {"kind": "EventsNode", "event": "error", "math": math, "math_property": "amount"},
                {"kind": "EventsNode", "event": "attempt", "math": "total"},
            ]
        )
        query["source"]["trendsFilter"] = {
            formula_key: [{"formula": formula}]
            if formula_key == "formulaNodes"
            else [formula]
            if formula_key == "formulas"
            else formula
        }
        if formula_key != "formula":
            query["source"]["trendsFilter"]["formula"] = "A - B"
        config = MetricThresholdConfig.model_validate({"query": query, "comparison": {"operator": "lte", "value": 1}})
        assert metric_evidence_source(config) == expected

    @parameterized.expand(
        [
            ("default_count", None, None, "count"),
            ("raw_count", "total", None, "count"),
            ("event_sum", "sum", "amount", "sum"),
            ("average_needs_policy", "avg", "amount", "average"),
            ("session_sum", "sum", "$session_duration", "unsupported"),
            ("session_count", "total", "$session_duration", "unsupported"),
            ("implicit_session_count", None, "$session_duration", "unsupported"),
            ("typed_session_count", "total", "$pageview_count", "unsupported", "session_properties"),
            ("event_property_count", "total", "$pageview_count", "count", "event_properties"),
            ("missing_property", "sum", None, "unsupported"),
            ("unique_people", "dau", None, "unsupported"),
            ("custom_expression", "hogql", None, "unsupported"),
        ]
    )
    def test_source_semantics_do_not_follow_display_format(
        self,
        _name: str,
        math: str | None,
        property_name: str | None,
        expected: str,
        property_type: str | None = None,
    ) -> None:
        entity = {"kind": "EventsNode", "event": "checkout", "math": math}
        if property_name is not None:
            entity["math_property"] = property_name
        if property_type is not None:
            entity["math_property_type"] = property_type
        config = MetricThresholdConfig.model_validate(
            {"query": trends_metric_query(series=[entity]), "comparison": {"operator": "gte", "value": 1}}
        )
        assert metric_evidence_source(config) == expected

    @parameterized.expand([("sampled",), ("formula",), ("person_property",)])
    def test_unsupported_shapes_cannot_qualify_through_a_scalar(self, shape: str) -> None:
        query = trends_metric_query(
            series=[{"kind": "EventsNode", "event": "checkout", "math": "sum", "math_property": "amount"}]
        )
        if shape == "sampled":
            query["source"]["samplingFactor"] = 0.5
        elif shape == "formula":
            query["source"]["trendsFilter"] = {"formula": "A * 2"}
        else:
            query["source"]["series"][0]["math_property_type"] = "person_properties"
        config = MetricThresholdConfig.model_validate({"query": query, "comparison": {"operator": "gte", "value": 1}})
        assert metric_evidence_source(config) == "unsupported"


class TestFinalMetricExecution(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.now = timezone.now()
        self.enterContext(time_machine.travel(self.now, tick=False))
        self.flag = self.enterContext(patch(_FLAG, return_value=True))
        self.report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="Checkout succeeds"
        )

    def _member(
        self,
        *,
        soak_minutes: int | None = 60,
        math: str = "total",
        math_property: str = "amount",
        math_property_type: str | None = None,
        definition: bool = True,
        formula: bool = False,
        scaling: str = "fixed",
        event: str = "checkout",
        rate_formula: str | None = None,
    ) -> FinalCheck:
        config = {
            "query": trends_metric_query(
                series=[{"kind": "EventsNode", "event": event, "math": math, "math_property": math_property}]
            ),
            "comparison": {"operator": "gte", "value": 10},
        }
        if math_property_type is not None:
            config["query"]["source"]["series"][0]["math_property_type"] = math_property_type
        if definition:
            config["monitoring"] = {"reference_period_minutes": 120, "threshold_scaling": scaling}
        if formula:
            config["query"]["source"]["trendsFilter"] = {"formula": "A * 2"}
        if rate_formula is not None:
            config["query"]["source"]["series"].append(
                {"kind": "EventsNode", "event": f"{event}_attempt", "math": "total"}
            )
            config["query"]["source"]["properties"] = [
                {"key": "environment", "value": ["production"], "operator": "exact", "type": "event"}
            ]
            config["query"]["source"]["trendsFilter"] = {"formula": rate_formula}
            config["comparison"] = {"operator": "lte", "value": 2 if "100" in rate_formula else 0.02}
        check = SignalReportCheck.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            report=self.report,
            title="Successful checkouts",
            kind="metric_threshold",
            config=config,
            soak_minutes=soak_minutes,
            next_run_at=self.now,
            expires_at=self.now + timedelta(days=30),
            runs_remaining=3,
        )
        start = self.now - timedelta(hours=2)
        attempt = complete_implementation(team_id=self.team.id, report_id=self.report.id, monitoring_started_at=start)
        assert attempt is not None
        check.refresh_from_db()
        check.report.refresh_from_db()
        return FinalCheck(
            check=check,
            attempt_id=attempt.id,
            definition_version=attempt.check_versions[str(check.id)],
            window_start=start,
            window_end=start + timedelta(minutes=soak_minutes or 0),
        )

    def _run(self) -> None:
        run_due_final_metrics(now=timezone.now(), deadline=time.monotonic() + 120, limit=50)

    @parameterized.expand(
        [
            ("pass", "total", 12, "passed"),
            ("failure", "total", 3, "failed"),
            ("sum", "sum", 12.5, "passed"),
            ("zero_count", "total", 0, "inconclusive"),
            ("zero_sum", "sum", 0, "inconclusive"),
            ("negative_sum", "sum", -1, "inconclusive"),
            ("rate_pass", "total", 0.01, "passed", "A / B", 100),
            ("terminated_rate", "total", 0.01, "passed", "A / B;", 100),
            ("rate_fail", "total", 0.03, "failed", "A / B", 100),
            ("zero_rate_with_activity", "total", 0, "passed", "A / B", 1),
            ("zero_rate_without_activity", "total", 0, "inconclusive", "A / B", 0),
            ("percentage_pass", "total", 1, "passed", "A / B * 100", 100),
            ("reverse_rate", "total", 0.01, "passed", "B / A", 100),
        ]
    )
    def test_final_results_separate_evidence_from_matching_and_aggregate_report_outcomes(
        self,
        _name: str,
        math: str,
        value: float,
        outcome: str,
        rate_formula: str | None = None,
        denominator: int | None = None,
    ) -> None:
        member = self._member(math=math, rate_formula=rate_formula)
        source_values = None
        if denominator is not None:
            numerator = value * denominator / (100 if rate_formula and "100" in rate_formula else 1)
            source_values = [denominator, numerator] if rate_formula == "B / A" else [numerator, denominator]
        measurement = MetricMeasurement(value=value, measured_at=self.now, series=None, source_values=source_values)
        with (
            patch("products.signals.backend.report_check_telemetry.ph_background_capture") as capture,
            self.captureOnCommitCallbacks(execute=True),
            patch(_MEASURE, return_value=measurement) as measure,
        ):
            summary = run_due_report_checks(now=self.now)
            self._run()
        result = SignalReportMonitoringResult.objects.for_team(self.team.id).get()
        assert result.outcome == outcome
        event = capture.return_value.call_args.kwargs
        assert event["event"] == "signals_report_monitoring_evaluated"
        assert event["uuid"] == str(result.id)
        assert event["properties"]["outcome"] == outcome
        assert result.window_start == member.window_start and result.window_end == member.window_end
        assert result.definition_version == member.definition_version
        assert str(value) in result.explanation
        assert len(result.evidence_refs) == (3 if rate_formula else 2)
        query = measure.call_args_list[0].args[0]
        assert query["source"]["dateRange"] == {
            "date_from": member.window_start.isoformat(),
            "date_to": member.window_end.isoformat(),
            "explicitDate": True,
            "excludeIncompletePeriods": False,
        }
        assert measure.call_args.kwargs["workload"] == Workload.OFFLINE
        assert measure.call_args.kwargs["ch_user"] == ClickHouseUser.SIGNALS
        assert measure.call_count == 1
        if rate_formula:
            assert len(query["source"]["series"]) == 2
            assert "formula" not in query["source"]["trendsFilter"]
            assert measure.call_args.kwargs["formula"] == rate_formula
            assert member.check.config["query"]["source"]["trendsFilter"]["formula"] == rate_formula
        assert sum([summary.passed, summary.failed, summary.inconclusive]) == 1
        self.report.refresh_from_db()
        member.check.refresh_from_db()
        expected_status = {
            "passed": SignalReport.Status.RESOLVED,
            "failed": SignalReport.Status.CLOSED,
        }.get(outcome, SignalReport.Status.MONITORING)
        assert self.report.status == expected_status
        assert member.check.runs_remaining == 3
        assert member.check.last_outcome == (outcome if outcome in {"passed", "failed"} else None)
        if denominator == 0:
            assert result.evidence_status == "insufficient" and result.evidence_reason == "empty_denominator"
        elif value == 0 and rate_formula is None:
            assert result.evidence_status == "insufficient" and result.evidence_reason == "activity_unavailable"
        elif value < 0:
            assert result.evidence_status == "unsupported"

    @parameterized.expand(
        [
            ("empty_window",),
            ("missing_definition",),
            ("formula",),
            ("average",),
            ("session_duration_count",),
            ("session_property_count",),
        ]
    )
    def test_unmeasurable_members_get_explicit_results_without_querying(self, variant: str) -> None:
        self._member(
            soak_minutes=0 if variant == "empty_window" else 60,
            definition=variant != "missing_definition",
            math="avg" if variant == "average" else "total",
            math_property={
                "session_duration_count": "$session_duration",
                "session_property_count": "$pageview_count",
            }.get(variant, "amount"),
            math_property_type="session_properties" if variant == "session_property_count" else None,
            formula=variant == "formula",
        )
        with patch(_MEASURE) as measure:
            self._run()
            self._run()
        result = SignalReportMonitoringResult.objects.for_team(self.team.id).get()
        assert result.outcome == "inconclusive"
        assert (
            result.evidence_reason
            == {
                "empty_window": "empty_window",
                "missing_definition": "missing_monitoring_definition",
                "formula": "unsupported_source",
                "average": "minimum_denominator_unspecified",
                "session_duration_count": "unsupported_source",
                "session_property_count": "unsupported_source",
            }[variant]
        )
        measure.assert_not_called()

    @parameterized.expand(
        [
            ("exhausted", False),
            ("recovered", True),
            ("rate_exhausted", False, "A / B"),
            ("rate_recovered", True, "A / B"),
        ]
    )
    def test_query_errors_retry_three_times_on_fixed_windows_and_remain_durable(
        self, _name: str, recovered: bool, rate_formula: str | None = None
    ) -> None:
        member = self._member(rate_formula=rate_formula)
        responses = [
            RuntimeError("private query detail"),
            RuntimeError("private query detail"),
            MetricMeasurement(
                value=0 if rate_formula else 12,
                measured_at=self.now,
                series=None,
                source_values=[0, 12] if rate_formula else None,
            )
            if recovered
            else RuntimeError("private query detail"),
        ]
        with patch(_MEASURE, side_effect=responses) as measure:
            for minutes, expected_calls in [(0, 1), (4, 1), (5, 2), (19, 2), (20, 3), (120, 3)]:
                with time_machine.travel(self.now + timedelta(minutes=minutes), tick=False):
                    self._run()
                assert measure.call_count == expected_calls
        results = list(SignalReportMonitoringResult.objects.for_team(self.team.id).order_by("created_at"))
        assert len(results) == 3 and len({result.submission_id for result in results}) == 3
        assert all(
            result.window_start == member.window_start and result.window_end == member.window_end for result in results
        )
        assert [result.outcome for result in results] == ["errored", "errored", "passed" if recovered else "errored"]
        assert all("private query detail" not in result.explanation for result in results)

    @parameterized.expand([("fixed", "failed"), ("linear", "passed")])
    def test_final_comparison_uses_the_authored_scaling_policy(self, scaling: str, outcome: str) -> None:
        self._member(scaling=scaling)
        with patch(_MEASURE, return_value=MetricMeasurement(value=6, measured_at=self.now, series=None)):
            self._run()
        assert SignalReportMonitoringResult.objects.for_team(self.team.id).get().outcome == outcome

    @parameterized.expand([("metric",), ("rate_inputs",)])
    def test_cached_predeadline_results_cannot_establish_a_final_pass(self, stale: str) -> None:
        member = self._member(rate_formula="A / B" if stale == "rate_inputs" else None)
        measurement = MetricMeasurement(
            value=0 if stale == "rate_inputs" else 12,
            measured_at=member.window_end - timedelta(seconds=1),
            series=None,
            source_values=[0, 12] if stale == "rate_inputs" else None,
        )
        with patch(
            _MEASURE,
            return_value=measurement,
        ):
            self._run()
        result = SignalReportMonitoringResult.objects.for_team(self.team.id).get()
        assert result.evidence_status == "insufficient" and result.expectation_matches is None

    @parameterized.expand([("total", 3), ("sum", 6), ("total", 0.03, "A / B"), ("total", 3, "A / B * 100")])
    def test_real_query_excludes_events_outside_the_fixed_window_and_population(
        self, math: str, value: float, rate_formula: str | None = None
    ) -> None:
        population = f"checkout-{uuid4()}"
        member = self._member(math=math, event=population, rate_formula=rate_formula)
        for timestamp, event, count in [
            (member.window_start - timedelta(seconds=1), population, 20),
            (member.window_start + timedelta(minutes=1), population, 3),
            (member.window_end + timedelta(seconds=1), population, 20),
            (member.window_start + timedelta(minutes=1), "unrelated", 20),
        ]:
            for _ in range(count):
                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id="test-user",
                    timestamp=timestamp,
                    properties={"amount": 2, "environment": "production"},
                )
        if rate_formula:
            for timestamp, environment, count in [
                (member.window_start + timedelta(minutes=1), "production", 100),
                (member.window_start + timedelta(minutes=1), "test", 100),
                (member.window_start - timedelta(seconds=1), "production", 100),
                (member.window_end + timedelta(seconds=1), "production", 100),
            ]:
                for _ in range(count):
                    _create_event(
                        team=self.team,
                        event=f"{population}_attempt",
                        distinct_id="test-user",
                        timestamp=timestamp,
                        properties={"environment": environment},
                    )
        flush_persons_and_events()
        self._run()
        result = SignalReportMonitoringResult.objects.for_team(self.team.id).get()
        assert result.outcome == "failed" and result.evidence_status == "sufficient", result.explanation
        assert str(float(value)) in result.explanation
        if rate_formula:
            assert "Denominator: 100" in result.explanation

    @parameterized.expand([("count", None), ("rate_inputs", "A / B")])
    def test_budget_deferral_does_not_spend_a_technical_retry(self, _name: str, rate_formula: str | None) -> None:
        self._member(rate_formula=rate_formula)
        with patch(_MEASURE, side_effect=MetricQueryBudgetExhausted):
            self._run()
        assert not SignalReportMonitoringResult.objects.for_team(self.team.id).exists()
        assert len(collect_due_final_metrics(self.now, limit=10)) == 1

    def test_cached_empty_rate_cannot_use_a_newer_denominator_after_budget_deferral(self) -> None:
        self._member(rate_formula="A / B")
        deferred = False

        def query_response(*, query: dict[str, object], **kwargs: object) -> TrendsQueryRunResult:
            nonlocal deferred
            trends_filter = query["trendsFilter"]
            series = query["series"]
            assert isinstance(trends_filter, dict) and isinstance(series, list)
            cached_formula = bool(trends_filter.get("formula"))
            if cached_formula:
                results = [{"aggregated_value": 0}]
            elif not deferred:
                deferred = True
                raise MetricQueryBudgetExhausted
            else:
                results = [{"aggregated_value": 10} for _ in series]
            return TrendsQueryRunResult(results=results, last_refresh=self.now if cached_formula else timezone.now())

        with patch(
            "products.signals.backend.report_metric_refresh.run_cached_trends_query", side_effect=query_response
        ):
            self._run()
            assert not SignalReportMonitoringResult.objects.for_team(self.team.id).exists()
            with time_machine.travel(self.now + timedelta(minutes=1), tick=False):
                self._run()
        result = SignalReportMonitoringResult.objects.for_team(self.team.id).get()
        assert result.outcome == "failed", result.explanation
        assert "Denominator: 10" in result.explanation

    @parameterized.expand([("short", 19.9, False), ("full", 20.0, True)])
    def test_only_queries_with_the_full_timeout_can_spend_a_technical_retry(
        self, _name: str, remaining_seconds: float, spends_retry: bool
    ) -> None:
        self._member()
        with (
            patch("time.monotonic", return_value=0),
            patch(
                "products.signals.backend.report_metric_refresh.run_cached_trends_query", side_effect=TimeoutError
            ) as query,
        ):
            for _ in range(3):
                summary = run_due_final_metrics(now=self.now, deadline=remaining_seconds, limit=50)
        assert query.call_count == int(spends_retry)
        results = SignalReportMonitoringResult.objects.for_team(self.team.id)
        if spends_retry:
            assert results.get().outcome == "errored"
            assert query.call_args.kwargs["max_execution_time_seconds"] == 20
        else:
            assert summary.deferred == 1
            assert not results.exists()
            assert len(collect_due_final_metrics(self.now, limit=10)) == 1

    @parameterized.expand([("cancelled",), ("archived",), ("definition",), ("disabled",), ("reopened",)])
    def test_query_results_cannot_cross_lifecycle_or_definition_changes(self, change: str) -> None:
        member = self._member()

        def change_during_query(*args: object, **kwargs: object) -> MetricMeasurement:
            if change == "cancelled":
                SignalReportCheck.objects.for_team(self.team.id).filter(id=member.check.id).update(status="cancelled")
            elif change == "definition":
                SignalReportCheck.objects.for_team(self.team.id).filter(id=member.check.id).update(
                    title="A new expectation"
                )
            elif change == "disabled":
                self.flag.return_value = False
            else:
                SignalReport.objects.filter(id=self.report.id, team_id=self.team.id).update(
                    status="suppressed" if change == "archived" else "ready"
                )
            return MetricMeasurement(value=12, measured_at=self.now, series=None)

        with patch(_MEASURE, side_effect=change_during_query):
            self._run()
        assert not SignalReportMonitoringResult.objects.for_team(self.team.id).exists()

    @parameterized.expand([("errored",), ("expired",)])
    def test_final_verification_keeps_errored_and_expired_snapshot_members(self, status: str) -> None:
        member = self._member()
        SignalReportCheck.objects.for_team(self.team.id).filter(id=member.check.id).update(
            status=status,
            measurement_start_at=member.window_start,
            consecutive_errors=MAX_CONSECUTIVE_CHECK_ERRORS,
            expires_at=self.now - timedelta(minutes=1),
        )
        with patch(_MEASURE, return_value=MetricMeasurement(value=12, measured_at=self.now, series=None)):
            self._run()
        assert SignalReportMonitoringResult.objects.for_team(self.team.id).get().outcome == "passed"
        member.check.refresh_from_db()
        assert member.check.status == status
        assert member.check.consecutive_errors == MAX_CONSECUTIVE_CHECK_ERRORS

    def test_stale_collections_cannot_duplicate_a_logical_submission(self) -> None:
        self._member()
        due = collect_due_final_metrics(self.now, limit=10)
        assert due[0].submission_id == collect_due_final_metrics(self.now, limit=10)[0].submission_id
        with (
            patch("products.signals.backend.report_check_final_metrics.collect_due_final_metrics", return_value=due),
            patch(_MEASURE, side_effect=RuntimeError) as measure,
        ):
            self._run()
            self._run()
        assert measure.call_count == 1
        assert SignalReportMonitoringResult.objects.for_team(self.team.id).count() == 1

    @parameterized.expand([("disabled",), ("stale_definition",)])
    def test_ineligible_members_cannot_fill_the_bounded_candidate_batch(self, variant: str) -> None:
        member = self._member()
        disabled_org = Organization.objects.create(name="Monitoring disabled")
        start = self.now - timedelta(hours=3)
        for _ in range(10):
            team = Team.objects.create(organization=disabled_org)
            report = SignalReport.objects.create(team=team, status="monitoring", monitoring_started_at=start)
            check = SignalReportCheck.objects.for_team(team.id).create(
                team_id=team.id,
                report=report,
                title="Old check",
                kind="metric_threshold",
                config=member.check.config,
                soak_minutes=60,
                next_run_at=self.now,
                expires_at=self.now + timedelta(days=1),
            )
            SignalReportMonitoringAttempt.objects.for_team(team.id).create(
                team_id=team.id,
                report=report,
                monitoring_started_at=start,
                check_versions={str(check.id): check_definition_version(check)},
            )
            if variant == "stale_definition":
                SignalReportCheck.objects.for_team(team.id).filter(id=check.id).update(title="Changed target")
        with patch(
            "products.signals.backend.report_lifecycle.organization_report_monitoring_enabled",
            side_effect=lambda organization_id: variant != "disabled" or organization_id != disabled_org.id,
        ):
            due = collect_due_final_metrics(self.now, limit=1)
        assert [entry.member.check.id for entry in due] == [member.check.id]

    @parameterized.expand([("before_deadline",), ("missing_soak",), ("not_in_snapshot",), ("edited",), ("disabled",)])
    def test_due_work_requires_current_snapshotted_obligations(self, variant: str) -> None:
        member = self._member(
            soak_minutes=180 if variant == "before_deadline" else None if variant == "missing_soak" else 60
        )
        if variant == "not_in_snapshot":
            SignalReportCheck.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                report=self.report,
                title="Added after implementation",
                kind="metric_threshold",
                config=member.check.config,
                soak_minutes=60,
                next_run_at=self.now,
                expires_at=self.now + timedelta(days=30),
            )
            SignalReportCheck.objects.for_team(self.team.id).filter(id=member.check.id).update(status="cancelled")
        elif variant == "edited":
            SignalReportCheck.objects.for_team(self.team.id).filter(id=member.check.id).update(title="Changed target")
        elif variant == "disabled":
            self.flag.return_value = False
        with patch(_MEASURE) as measure:
            self._run()
        measure.assert_not_called()
        assert not SignalReportMonitoringResult.objects.for_team(self.team.id).exists()
