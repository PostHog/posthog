from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.report_check_evaluation import evaluate_check_value
from products.signals.backend.report_check_evidence import (
    EvidenceCount,
    EvidenceQualification,
    EvidenceReason,
    EvidenceScope,
    EvidenceSource,
    EvidenceStatus,
    MetricEvidence,
    qualify_metric_evidence,
)
from products.signals.backend.report_checks import CheckComparison

_START = datetime(2026, 10, 21, tzinfo=UTC)
_SCOPE = EvidenceScope(team_id=1, population="checkout attempts", start=_START, end=_START + timedelta(hours=4))


class TestMetricEvidence(SimpleTestCase):
    @parameterized.expand(
        [
            ("positive_count", "count", 1, None, "sufficient", "positive_total"),
            ("positive_sum", "sum", 0.5, None, "sufficient", "positive_total"),
            ("zero_adverse_events_with_activity", "count", 0, 1, "sufficient", "relevant_activity"),
            ("zero_sum_with_activity", "sum", 0, 1, "sufficient", "relevant_activity"),
            ("no_activity", "count", 0, 0, "insufficient", "no_activity"),
            ("no_activity_measurement", "count", 0, None, "insufficient", "activity_unavailable"),
            ("zero_sum_without_activity", "sum", 0, None, "insufficient", "activity_unavailable"),
            ("signed_sum_needs_policy", "sum", -1, 1, "unsupported", "unsupported_value"),
            ("unsupported_aggregate", "unsupported", 100, 100, "unsupported", "unsupported_source"),
            ("unavailable_measurement", "count", None, 100, "insufficient", "measurement_unavailable"),
        ]
    )
    def test_totals_require_their_own_evidence(
        self,
        _name: str,
        source: EvidenceSource,
        value: float | None,
        activity: int | None,
        status: EvidenceStatus,
        reason: EvidenceReason,
    ) -> None:
        evidence = MetricEvidence(
            scope=_SCOPE,
            source=source,
            value=value,
            activity=EvidenceCount(scope=_SCOPE, value=activity) if activity is not None else None,
        )

        assert qualify_metric_evidence(evidence) == EvidenceQualification(status=status, reason=reason)

    @parameterized.expand(
        [
            (f"{source}_{name}", source, value, denominator, minimum, status, reason)
            for source in ("rate", "average")
            for name, value, denominator, minimum, status, reason in [
                ("missing", 0, None, 10, "insufficient", "denominator_unavailable"),
                ("empty", 0, 0, 10, "insufficient", "empty_denominator"),
                ("below_minimum", 0, 9, 10, "insufficient", "insufficient_denominator"),
                ("at_minimum", 0, 10, 10, "sufficient", "qualifying_denominator"),
                ("no_policy", 0.5, 100, None, "insufficient", "minimum_denominator_unspecified"),
                ("positive_without_denominator", 0.5, None, 10, "insufficient", "denominator_unavailable"),
            ]
        ]
    )
    def test_rates_and_averages_require_an_explicit_denominator_policy(
        self,
        _name: str,
        source: EvidenceSource,
        value: float,
        denominator: int | None,
        minimum: int | None,
        status: EvidenceStatus,
        reason: EvidenceReason,
    ) -> None:
        evidence = MetricEvidence(
            scope=_SCOPE,
            source=source,
            value=value,
            activity=EvidenceCount(scope=_SCOPE, value=100),
            denominator=EvidenceCount(scope=_SCOPE, value=denominator) if denominator is not None else None,
        )

        assert qualify_metric_evidence(evidence, minimum_denominator=minimum) == EvidenceQualification(
            status=status, reason=reason
        )

    @parameterized.expand(
        [
            ("team", "count", replace(_SCOPE, team_id=2)),
            ("population", "count", replace(_SCOPE, population="unrelated activity")),
            ("baseline", "rate", replace(_SCOPE, start=_START - timedelta(hours=4), end=_START)),
            ("partial_window", "average", replace(_SCOPE, end=_START + timedelta(hours=1))),
        ]
    )
    def test_supporting_counts_must_cover_the_relevant_population_and_window(
        self, _name: str, source: EvidenceSource, scope: EvidenceScope
    ) -> None:
        count = EvidenceCount(scope=scope, value=100)
        evidence = MetricEvidence(scope=_SCOPE, source=source, value=0, activity=count, denominator=count)

        assert qualify_metric_evidence(evidence, minimum_denominator=10) == EvidenceQualification(
            status="insufficient", reason="scope_mismatch"
        )

    def test_a_short_final_window_needs_no_interim_samples_and_still_can_fail_its_target(self) -> None:
        observed_value = 1.0
        evidence = MetricEvidence(scope=_SCOPE, source="count", value=observed_value)

        assert qualify_metric_evidence(evidence).status == "sufficient"
        assert (
            evaluate_check_value(
                comparison=CheckComparison(operator="lte", value=0), observed_value=observed_value, subject="Errors"
            ).outcome
            == "failed"
        )

    def test_a_matching_zero_does_not_prove_success_without_activity(self) -> None:
        observed_value = 0.0
        evidence = MetricEvidence(scope=_SCOPE, source="count", value=observed_value)

        assert (
            evaluate_check_value(
                comparison=CheckComparison(operator="lte", value=0), observed_value=observed_value, subject="Errors"
            ).outcome
            == "passed"
        )
        assert qualify_metric_evidence(evidence).status == "insufficient"

    def test_a_query_error_is_distinct_from_missing_or_insufficient_evidence(self) -> None:
        evidence = MetricEvidence(scope=_SCOPE, source="rate", query_error=True)

        assert qualify_metric_evidence(evidence) == EvidenceQualification(status="errored", reason="query_error")

    def test_an_empty_window_cannot_qualify(self) -> None:
        evidence = MetricEvidence(scope=replace(_SCOPE, end=_START), source="count", value=1)

        assert qualify_metric_evidence(evidence) == EvidenceQualification(status="insufficient", reason="empty_window")

    @parameterized.expand([("negative", -1), ("fractional", 0.5), ("boolean", True), ("nonfinite", float("inf"))])
    def test_invalid_counts_cannot_supply_evidence(self, _name: str, value: float) -> None:
        with self.assertRaises(ValueError):
            EvidenceCount(scope=_SCOPE, value=cast(int, value))
        with self.assertRaises(ValueError):
            MetricEvidence(scope=_SCOPE, source="count", value=value)

    @parameterized.expand([("zero", 0), ("negative", -1), ("fractional", 0.5), ("boolean", True)])
    def test_invalid_minimums_cannot_qualify_a_denominator(self, _name: str, minimum: float) -> None:
        evidence = MetricEvidence(
            scope=_SCOPE, source="rate", value=0, denominator=EvidenceCount(scope=_SCOPE, value=10)
        )

        with self.assertRaises(ValueError):
            qualify_metric_evidence(evidence, minimum_denominator=cast(int, minimum))

    @parameterized.expand(
        [
            ("missing_population", "", _SCOPE.start, _SCOPE.end),
            ("naive_start", _SCOPE.population, _SCOPE.start.replace(tzinfo=None), _SCOPE.end),
            ("naive_end", _SCOPE.population, _SCOPE.start, _SCOPE.end.replace(tzinfo=None)),
            ("reversed_window", _SCOPE.population, _SCOPE.end, _SCOPE.start),
        ]
    )
    def test_invalid_scopes_cannot_supply_evidence(
        self, _name: str, population: str, start: datetime, end: datetime
    ) -> None:
        with self.assertRaises(ValueError):
            EvidenceScope(team_id=_SCOPE.team_id, population=population, start=start, end=end)

    def test_a_query_error_cannot_also_supply_a_measured_value(self) -> None:
        with self.assertRaises(ValueError):
            MetricEvidence(scope=_SCOPE, source="count", value=1, query_error=True)
