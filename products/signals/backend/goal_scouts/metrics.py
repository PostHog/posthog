import math
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.cache import cache

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.product_analytics.backend.facade.api import get_insight_series, saved_insight_for_read
from products.product_analytics.backend.facade.contracts import InsightDeliveryEvidence, InsightSeries
from products.product_analytics.backend.facade.measurement import insight_delivery_evidence

PERCENT_FORMATS = frozenset({"percentage", "percentage_scaled"})
DELIVERY_CACHE_SECONDS = 300
WINDOW_EDGE = timedelta(hours=1)


@frozen
class Metric:
    name: str
    unit: str
    values: list[float]
    dates: list[str]
    current: float | None
    message: str


@frozen
class Observed:
    participants: int
    days: float
    tracked_before_window: bool


def empty_metric(name: str, message: str, unit: str = "") -> Metric:
    return Metric(name=name, unit=unit, values=[], dates=[], current=None, message=message)


def insight_series(team: Team, user: User, short_id: str, *, blocking: bool) -> InsightSeries | None:
    with tags_context(product=Product.SIGNALS, feature=Feature.QUERY, team_id=team.id, user_id=user.id):
        return get_insight_series(team=team, user=user, short_id=short_id, blocking=blocking)


def delivery(
    team: Team, user: User, short_id: str, *, workload: Workload, since: datetime | None = None
) -> InsightDeliveryEvidence | None:
    key = f"signals:goal-delivery:{team.id}:{user.id}:{short_id}:{since.isoformat() if since else ''}"
    cached = cache.get(key)
    if isinstance(cached, InsightDeliveryEvidence):
        return cached
    found = insight_delivery_evidence(team=team, user=user, short_id=short_id, workload=workload, since=since)
    if found is not None:
        cache.set(key, found, DELIVERY_CACHE_SECONDS)
    return found


def observed(found: InsightDeliveryEvidence | None) -> Observed:
    if found is None or found.first_event_at is None:
        return Observed(participants=0, days=0.0, tracked_before_window=False)
    start = max(found.first_event_at, found.window_start)
    end = min(found.last_event_at or found.window_end, found.window_end)
    return Observed(
        participants=found.participants,
        days=max((end - start).total_seconds() / 86400, 0.0),
        tracked_before_window=found.first_event_at - found.window_start <= WINDOW_EDGE,
    )


def _observed_points(
    team: Team, user: User, short_id: str, points: list[tuple[str, float]], workload: Workload
) -> tuple[list[tuple[str, float]], bool]:
    found = delivery(team, user, short_id, workload=workload)
    zone = ZoneInfo(team.timezone)
    first = found.first_event_at.astimezone(zone).date().isoformat() if found and found.first_event_at else None
    last = found.last_event_at.astimezone(zone).date().isoformat() if found and found.last_event_at else None
    if first is None or last is None:
        return [], False
    kept = [(day, value) for day, value in points if first <= day <= last]
    return kept, bool(points) and last >= points[-1][0]


def metric(
    team: Team, user: User, short_id: str | None, *, blocking: bool = False, workload: Workload = Workload.ONLINE
) -> Metric:
    if not short_id:
        return empty_metric("Goal", "Connect a saved insight to measure this goal.")
    result = insight_series(team, user, short_id, blocking=blocking)
    if result is None:
        insight = saved_insight_for_read(team=team, user=user, short_id=short_id)
        return empty_metric(insight.name if insight and insight.name else "Goal", "Waiting for insight data.")
    name = result.name or "Goal"
    if len(result.series) != 1:
        return empty_metric(name, "Choose an insight with a single series for this goal.")
    unit = result.value_postfix or ("%" if result.value_format in PERCENT_FORMATS else "")
    scale = 100 if result.value_format == "percentage_scaled" else 1
    points = [
        (day.isoformat(), float(value) * scale)
        for day, value in next(iter(result.series.values()))
        if math.isfinite(value)
    ]
    if result.averaged_series and any(value == 0 for _, value in points):
        points, current_period_observed = _observed_points(team, user, short_id, points, workload)
        if not current_period_observed:
            return Metric(
                name=name,
                unit=unit,
                values=[value for _, value in points],
                dates=[day for day, _ in points],
                current=None,
                message="Waiting for observations in the current measurement period.",
            )
    values = [value for _, value in points]
    return Metric(
        name=name,
        unit=unit,
        values=values,
        dates=[day for day, _ in points],
        current=values[-1] if values else None,
        message="" if values else "No data yet.",
    )


def measure_problem(team: Team, user: User, short_id: str) -> str:
    if saved_insight_for_read(team=team, user=user, short_id=short_id) is None:
        return "Choose a saved insight you can view in this project."
    result = insight_series(team, user, short_id, blocking=False)
    if result is not None and len(result.series) != 1:
        return "Choose a saved insight with one series."
    return ""


def meets(direction: str, target: Decimal | None, value: float | None) -> bool:
    if value is None or target is None:
        return False
    return value <= float(target) if direction == "decrease" else value >= float(target)
