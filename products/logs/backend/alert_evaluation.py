from collections.abc import Sequence
from itertools import pairwise

from posthog.schema import (
    AlertCondition,
    AlertConditionType,
    InsightsThresholdBounds,
    InsightThreshold,
    InsightThresholdType,
)

from posthog.dataclasses import frozen
from posthog.tasks.alerts.utils import AlertEvaluationResult

from products.alerts.backend.evaluation.comparator import evaluate_threshold
from products.alerts.backend.evaluation.contract import ComparableSeries, ExtractionResult, SeriesPoint
from products.logs.backend.alert_check_query import BucketedCount
from products.logs.backend.alert_error_classifier import AlertErrorCode, classify
from products.logs.backend.alert_state_machine import CheckResult
from products.logs.backend.models import MAX_EVALUATION_PERIODS, LogsAlertConfiguration


@frozen
class LogsAlertEvaluation:
    check: CheckResult
    bucket_results: tuple[AlertEvaluationResult, ...]
    breaches: tuple[bool, ...]
    error_code: AlertErrorCode | None = None


def evaluate_logs_alert(
    alert: LogsAlertConfiguration,
    *,
    buckets: Sequence[BucketedCount] | None,
    error: Exception | None = None,
    query_duration_ms: int | None = None,
) -> LogsAlertEvaluation:
    """Score supplied rolling counts without queries, diagnostics, or model mutation.

    Bucket results and breach flags are newest-first, including implicit zero counts.
    Each bucket uses the shared absolute comparator; the logs lifecycle still owns N-of-M.
    """
    if error is not None:
        classified = classify(error)
        return LogsAlertEvaluation(
            check=CheckResult(
                result_count=None,
                threshold_breached=False,
                error_message=classified.user_message,
                is_transient_error=classified.is_transient,
            ),
            bucket_results=(),
            breaches=(),
            error_code=classified.code,
        )
    if buckets is None:
        raise ValueError("Supply buckets or a query error")
    if alert.threshold_operator not in ("above", "below") or alert.threshold_count < 1:
        raise ValueError("Expected a positive logs threshold and an above/below operator")
    if not 1 <= alert.datapoints_to_alarm <= alert.evaluation_periods <= MAX_EVALUATION_PERIODS:
        raise ValueError("Invalid logs N-of-M configuration")
    if len(buckets) > alert.evaluation_periods or any(b.count < 0 for b in buckets):
        raise ValueError("Expected at most M nonnegative rolling counts")
    if any(a.timestamp >= b.timestamp for a, b in pairwise(buckets)):
        raise ValueError("Rolling counts must be oldest-first with distinct timestamps")

    bounds = (
        InsightsThresholdBounds(upper=alert.threshold_count)
        if alert.threshold_operator == "above"
        else InsightsThresholdBounds(lower=alert.threshold_count)
    )
    threshold = InsightThreshold(type=InsightThresholdType.ABSOLUTE, bounds=bounds)
    condition = AlertCondition(type=AlertConditionType.ABSOLUTE_VALUE)
    points = [SeriesPoint(date=b.timestamp.isoformat(), value=b.count) for b in reversed(buckets)]
    points.extend(SeriesPoint(date=None, value=0) for _ in range(alert.evaluation_periods - len(points)))
    results = tuple(
        evaluate_threshold(
            ExtractionResult(
                series=[ComparableSeries(label="", points=[point], current_index=0)],
                subject="The log count",
                framed=False,
            ),
            condition,
            threshold,
        )
        for point in points
    )
    breaches = tuple(bool(result.breaches) for result in results)
    return LogsAlertEvaluation(
        check=CheckResult(
            result_count=buckets[-1].count if buckets else 0,
            threshold_breached=breaches[0],
            query_duration_ms=query_duration_ms if query_duration_ms is not None else 0,
        ),
        bucket_results=results,
        breaches=breaches,
    )
