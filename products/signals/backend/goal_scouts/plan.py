import math
from datetime import timedelta

from posthog.dataclasses import frozen

from products.experiments.backend.facade.api import estimate_running_time
from products.experiments.backend.facade.contracts import RunningTimeMetricType

from .metrics import Metric, Observed

MIN_OBSERVATIONS = 300
MIN_DAYS = 2
DEFAULT_MDE = 30.0
EXPOSURE_GRACE = timedelta(hours=48)


@frozen
class Readiness:
    ready: bool
    note: str


@frozen
class PlanAnchor:
    mde: float
    sample_size: int
    audience: int | None
    days: int | None


@frozen
class MeasureShape:
    metric_type: RunningTimeMetricType
    baseline_value: float


def readiness(found: Observed) -> Readiness:
    days = max(found.days, MIN_DAYS) if found.tracked_before_window else found.days
    if found.participants >= MIN_OBSERVATIONS and days >= MIN_DAYS:
        return Readiness(ready=True, note="")
    rate = found.participants / days if days > 0 else 0
    left_for_data = (MIN_OBSERVATIONS - found.participants) / rate if rate else None
    left = max(left_for_data or 0, MIN_DAYS - days)
    eta = (
        f" About {math.ceil(left)} more days."
        if left_for_data is not None or found.participants >= MIN_OBSERVATIONS
        else ""
    )
    return Readiness(
        ready=False,
        note=f"Waiting for data: {min(found.participants, MIN_OBSERVATIONS)} of {MIN_OBSERVATIONS} observations.{eta}",
    )


def measure_shape(measured: Metric) -> MeasureShape | None:
    value = measured.current
    if value is None or value == 0:
        return None
    if measured.unit == "%":
        return MeasureShape(metric_type="funnel", baseline_value=value / 100) if 0 < value < 100 else None
    if 0 < value < 1:
        return MeasureShape(metric_type="funnel", baseline_value=value)
    return MeasureShape(metric_type="mean_sum_or_avg", baseline_value=abs(value))


def daily_audience(found: Observed) -> int | None:
    return round(found.participants / found.days) if found.days >= 1 else None


def plan_days(sample_size: int, audience: int | None) -> int | None:
    if not audience or audience <= 0:
        return None
    return max(math.ceil(sample_size / audience), MIN_DAYS)


def plan_anchor(measured: Metric, audience: int | None, mde: float = DEFAULT_MDE) -> PlanAnchor | None:
    shape = measure_shape(measured)
    if shape is None:
        return None
    estimate = estimate_running_time(
        metric_type=shape.metric_type,
        baseline_value=shape.baseline_value,
        minimum_detectable_effect=mde,
        exposures_per_day=audience,
    )
    if estimate is None:
        return None
    return PlanAnchor(
        mde=mde,
        sample_size=estimate.sample_size,
        audience=audience,
        days=plan_days(estimate.sample_size, audience),
    )


def plan_refusal(measured: Metric, *, days: int, mde: float, audience: int) -> str:
    anchor = plan_anchor(measured, audience, mde)
    needed = anchor.days if anchor is not None and anchor.days is not None else MIN_DAYS
    if days < needed:
        return f"This test needs at least {needed} days to find a {mde:g}% change with {audience:,} people a day."
    return ""
