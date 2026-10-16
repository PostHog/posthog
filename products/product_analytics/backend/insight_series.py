import re
import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from posthog.models import Team, User

from products.product_analytics.backend.facade.contracts import InsightSeries

ADDITIVE_MATH = {"total", "sum", "first_time_for_user", "first_matching_event_for_user"}
UNCHARTED_DISPLAYS = {
    "ActionsTable",
    "ActionsPie",
    "BoldNumber",
    "WorldMap",
    "ActionsBarValue",
    "ActionsLineGraphCumulative",
}
LOOKBACK = {"day": "-56d", "week": "-16w", "month": "-24m"}


def insight_series(
    team: Team,
    user: User,
    *,
    short_id: str,
    name: str | None,
    query: dict[str, Any],
    dashboard_filters: dict[str, Any] | None,
) -> InsightSeries | None:
    source = query.get("source", query)
    kind = source.get("kind")
    if kind == "TrendsQuery":
        series, period = _trends_series(team, user, source, dashboard_filters)
    elif kind == "HogQLQuery":
        if "{filters}" in (source.get("query") or ""):
            source = {**source, "filters": {**(source.get("filters") or {}), "dateRange": {"date_from": "-56d"}}}
        response = _run(team, user, source, dashboard_filters)
        series, period = _table_series(response.get("columns") or [], response.get("results") or [])
    else:
        return None
    if not series:
        return None
    display = source.get("trendsFilter") or {}
    return InsightSeries(
        short_id=short_id,
        name=name,
        series=series,
        period=period,
        averaged=_averaged(source),
        event_name=_event_name(source),
        value_format=display.get("aggregationAxisFormat"),
        value_prefix=display.get("aggregationAxisPrefix"),
        value_postfix=display.get("aggregationAxisPostfix"),
        decimal_places=display.get("decimalPlaces"),
    )


def _trends_series(
    team: Team, user: User, source: dict[str, Any], dashboard_filters: dict[str, Any] | None
) -> tuple[dict[str, list[tuple[date, float]]], str]:
    if ((source.get("trendsFilter") or {}).get("display") or "") in UNCHARTED_DISPLAYS:
        return {}, "day"
    interval = source.get("interval") or "day"
    if interval not in LOOKBACK:
        interval = "day"
    source = {**source, "interval": interval, "dateRange": {"date_from": LOOKBACK[interval]}}
    source.pop("compareFilter", None)
    response = _run(team, user, source, dashboard_filters)
    series: dict[str, list[tuple[date, float]]] = {}
    several = len(source.get("series") or []) > 1
    for result in response.get("results") or []:
        if not result.get("days") or result.get("compare_label") == "previous":
            continue
        label = str((result.get("action") or {}).get("custom_name") or result.get("label") or "Series")
        breakdown = result.get("breakdown_value")
        if breakdown not in (None, ""):
            value = ", ".join(str(b) for b in breakdown) if isinstance(breakdown, list) else str(breakdown)
            label = f"{label} · {value}" if several else value
        while label in series:
            label += " (2)"
        series[label] = [
            (date.fromisoformat(str(d)[:10]), float(v or 0)) for d, v in zip(result["days"], result["data"])
        ]
    return series, interval


def _table_series(columns: list[str], rows: list[list[Any]]) -> tuple[dict[str, list[tuple[date, float]]], str]:
    if not rows:
        return {}, "day"
    date_index = next(
        (
            i
            for i in range(len(columns))
            if sum(1 for r in rows if _parse_date(r[i])) >= 0.8 * len([r for r in rows if r[i] is not None]) > 0
        ),
        None,
    )
    if date_index is None:
        return {}, "day"
    numbers = [
        i
        for i in range(len(columns))
        if i != date_index and all(isinstance(r[i], int | float | Decimal) or r[i] is None for r in rows)
    ]
    texts = [i for i in range(len(columns)) if i not in numbers and i != date_index]
    if not numbers or len(texts) > 1:
        return {}, "day"
    sums: dict[str, dict[date, float]] = {}
    for row in rows:
        day = _parse_date(row[date_index])
        if day is None:
            continue
        for index in numbers[:1] if texts else numbers:
            value = float(row[index] or 0)
            if not math.isfinite(value):
                continue
            name = str(row[texts[0]]) if texts else columns[index]
            sums.setdefault(name, {}).setdefault(day, 0.0)
            sums[name][day] += value
    days = sorted({d for values in sums.values() for d in values})
    gap = min(((b - a).days for a, b in zip(days, days[1:])), default=0)
    period = "day" if gap <= 1 else "week" if gap <= 8 else "month" if gap <= 32 else ""
    if not period:
        return {}, "day"
    return {name: sorted(values.items()) for name, values in sums.items() if name and name != "None"}, period


def _averaged(source: dict[str, Any]) -> bool:
    if source.get("kind") != "TrendsQuery":
        return False
    trends = source.get("trendsFilter") or {}
    if trends.get("formula") or trends.get("formulas") or trends.get("formulaNodes"):
        return True
    return any((node.get("math") or "total") not in ADDITIVE_MATH for node in source.get("series") or [])


def _event_name(source: dict[str, Any]) -> str:
    nodes = source.get("series") or []
    if source.get("kind") != "TrendsQuery" or len(nodes) != 1:
        return ""
    return str(nodes[0].get("custom_name") or nodes[0].get("event") or nodes[0].get("name") or "")


def _run(team: Team, user: User, source: dict[str, Any], dashboard_filters: dict[str, Any] | None) -> dict[str, Any]:
    from posthog.api.services.query import process_query_dict  # noqa: PLC0415

    return _as_dict(process_query_dict(team, source, dashboard_filters_json=dashboard_filters, user=user))


def _as_dict(response: Any) -> dict[str, Any]:
    if isinstance(response, BaseModel):
        return response.model_dump()
    return response if isinstance(response, dict) else {}


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value[:10])
    return None
