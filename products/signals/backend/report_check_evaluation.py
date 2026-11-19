from __future__ import annotations

from posthog.schema import (
    AlertCondition,
    AlertConditionType,
    InsightsThresholdBounds,
    InsightThreshold,
    InsightThresholdType,
)

from posthog.dataclasses import frozen

from products.alerts.backend.facade.evaluation import (
    ComparableSeries,
    ExtractionResult,
    SeriesPoint,
    evaluate_threshold,
)
from products.signals.backend.report_checks import CheckComparison, CheckInconclusiveReason, CheckOutcome

MAX_CHECK_ERROR_REASON_LENGTH = 300


@frozen
class CheckVerdict:
    outcome: CheckOutcome
    explanation: str
    observed_value: float | None = None
    # Required on an `inconclusive` verdict and refused on any other, so a stored reason always
    # explains the outcome next to it.
    reason: CheckInconclusiveReason | None = None

    def __post_init__(self) -> None:
        if (self.outcome == "inconclusive") != (self.reason is not None):
            raise ValueError("an `inconclusive` verdict needs a reason, and no other verdict takes one")


def _threshold_for(comparison: CheckComparison) -> InsightThreshold:
    """The alerts threshold whose breach is exactly this comparison's failure.

    The alerts comparator breaches on `value < lower` or `value > upper`, so `gte` is a lower bound,
    `lte` an upper one, and `between` both.
    """
    if comparison.operator == "between":
        assert comparison.bounds is not None
        bounds = InsightsThresholdBounds(lower=comparison.bounds.lower, upper=comparison.bounds.upper)
    elif comparison.operator == "gte":
        bounds = InsightsThresholdBounds(lower=comparison.value)
    else:
        bounds = InsightsThresholdBounds(upper=comparison.value)
    return InsightThreshold(type=InsightThresholdType.ABSOLUTE, bounds=bounds)


def describe_comparison(comparison: CheckComparison) -> str:
    if comparison.operator == "between":
        assert comparison.bounds is not None
        return f"between {comparison.bounds.lower} and {comparison.bounds.upper}"
    return f"at most {comparison.value}" if comparison.operator == "lte" else f"at least {comparison.value}"


def evaluate_check_value(*, comparison: CheckComparison, observed_value: float, subject: str) -> CheckVerdict:
    """Compare one measured value against the check's expectation."""

    result = ExtractionResult(
        series=[
            ComparableSeries(label=subject, points=[SeriesPoint(date=None, value=observed_value)], current_index=0)
        ],
        subject=subject,
        framed=False,
    )
    evaluation = evaluate_threshold(
        result,
        AlertCondition(type=AlertConditionType.ABSOLUTE_VALUE),
        _threshold_for(comparison),
    )
    if evaluation.breaches:
        return CheckVerdict(outcome="failed", explanation=evaluation.breaches[0], observed_value=observed_value)
    return CheckVerdict(
        outcome="passed",
        explanation=f"{subject} ({observed_value}) is {describe_comparison(comparison)}, as expected",
        observed_value=observed_value,
    )


def errored_check_explanation(error: Exception, *, subject: str) -> str:
    """The line a report reader sees when a run could not be measured.

    It opens with the check's title, as the passed and failed lines do, so a report carrying several
    checks does not log entries a reader cannot tell apart.

    Our own validation and resolution failures name something the reader can act on, so they are
    kept. Anything else is reduced to the fixed line: a query error can carry generated SQL and a
    server stack trace, which `ExposedCHQueryError` exists to keep out of user-facing text, and the
    artefact log is permanent and rendered as written. Measurement callers log the whole error.
    """
    reason = str(error).strip() if isinstance(error, ValueError | TimeoutError) else ""
    if not reason:
        return f"{subject} could not be measured."
    return f"{subject} could not be measured: {reason[:MAX_CHECK_ERROR_REASON_LENGTH]}"
