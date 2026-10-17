import json
from datetime import date
from typing import Any

from pydantic import BaseModel

from posthog.hogql_queries.apply_dashboard_filters import resolve_effective_dashboard_filters
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team, User

from products.product_analytics.backend.facade.contracts import InsightDashboardContext, InsightSeries

ADDITIVE_MATH = {
    "total",
    "sum",
    "first_time_for_user",
    "first_matching_event_for_user",
    "first_time_for_group",
    "first_matching_event_for_group",
}
UNCHARTED_DISPLAYS = {
    "ActionsTable",
    "ActionsPie",
    "BoldNumber",
    "WorldMap",
    "ActionsBarValue",
    "ActionsLineGraphCumulative",
    "SlopeGraph",
}
LOOKBACK = {"day": "-56d", "week": "-16w", "month": "-24m"}
DATE_FILTERS = ("date_from", "date_to", "explicitDate", "interval", "compareFilter")
EXECUTION_MODE = ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE


def _run(
    team: Team,
    user: User,
    source: dict[str, Any],
    filters: dict[str, Any] | None,
    variables: dict[str, Any] | None,
) -> dict[str, Any]:
    from posthog.api.services.query import process_query_dict  # noqa: PLC0415

    response = process_query_dict(
        team,
        source,
        dashboard_filters_json=filters,
        variables_override_json=variables,
        execution_mode=EXECUTION_MODE,
        user=user,
    )
    return response.model_dump() if isinstance(response, BaseModel) else response


def _value_key(result: dict[str, Any], position: int) -> str:
    order = (result.get("action") or {}).get("order")
    payload: dict[str, Any] = {
        "series": order if isinstance(order, int) else f"formula{position + 1}" if position else "formula"
    }
    if "breakdown_value" in result:
        breakdown = result["breakdown_value"]
        payload["breakdown_value"] = breakdown if isinstance(breakdown, list) else [breakdown]
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _visible(trends: dict[str, Any], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    customizations = trends.get("resultCustomizations") or {}
    if not customizations:
        return results
    by_position = trends.get("resultCustomizationBy") == "position"
    ranked = sorted(range(len(results)), key=lambda i: (results[i].get("action") or {}).get("order") or 0)
    positions = {index: rank for rank, index in enumerate(ranked)}
    return [
        result
        for index, result in enumerate(results)
        if not (
            customizations.get(str(positions[index]) if by_position else _value_key(result, positions[index])) or {}
        ).get("hidden")
    ]


def insight_series(
    team: Team,
    user: User,
    *,
    short_id: str,
    name: str | None,
    query: dict[str, Any],
    dashboard: InsightDashboardContext | None,
) -> InsightSeries | None:
    dashboard_filters: dict[str, Any] = {}
    variables: dict[str, Any] | None = None
    if dashboard is not None:
        effective = resolve_effective_dashboard_filters(query, dashboard.filters, dashboard.tile_filters)
        query = effective.query
        dashboard_filters = effective.filters or {}
        variables = dashboard.variables
    filters = {key: value for key, value in dashboard_filters.items() if key not in DATE_FILTERS}
    source = query.get("source", query)
    trends = source.get("trendsFilter") or {}
    if source.get("kind") != "TrendsQuery" or trends.get("display") in UNCHARTED_DISPLAYS:
        return None
    interval = dashboard_filters.get("interval") or source.get("interval") or "day"
    if interval not in LOOKBACK:
        interval = "day"
    date_range = source.get("dateRange") or {}
    if interval == "day" and date_range.get("daysOfWeek"):
        return None
    kept = {key: value for key, value in date_range.items() if key not in DATE_FILTERS}
    bounded = {key: value for key, value in source.items() if key != "compareFilter"}
    bounded.update(
        interval=interval,
        dateRange={**kept, "date_from": LOOKBACK[interval], "excludeIncompletePeriods": True},
        trendsFilter={**{k: v for k, v in trends.items() if k != "smoothingIntervals"}, "metricShowChange": False},
    )
    response = _run(team, user, bounded, filters, variables)
    formula = bool(trends.get("formula") or trends.get("formulas") or trends.get("formulaNodes"))
    several = len(source.get("series") or []) > 1
    series: dict[str, list[tuple[date, float]]] = {}
    averaged: list[str] = []
    for result in _visible(trends, response.get("results") or []):
        if not result.get("days"):
            continue
        action = result.get("action") or {}
        shown = str(result.get("label") or "Series")
        label = str(action.get("custom_name") or action.get("name") or shown)
        breakdown = result.get("breakdown_value")
        if breakdown not in (None, ""):
            if action:
                value = shown.removeprefix(f"{action.get('name')} - ") if several else shown
            else:
                value = ", ".join(str(b) for b in breakdown) if isinstance(breakdown, list) else str(breakdown)
            label = f"{label} · {value}" if several else value
        while label in series:
            label += " (2)"
        series[label] = [
            (date.fromisoformat(str(d)[:10]), float(v or 0)) for d, v in zip(result["days"], result["data"])
        ]
        if formula or (action.get("math") or "total") not in ADDITIVE_MATH:
            averaged.append(label)
    if not series:
        return None
    nodes = source.get("series") or []
    node = nodes[0] if len(nodes) == 1 else {}
    places = trends.get("decimalPlaces")
    return InsightSeries(
        short_id=short_id,
        name=name,
        series=series,
        period=interval,
        averaged_series=averaged,
        event_name=str(node.get("custom_name") or node.get("event") or node.get("name") or ""),
        value_format=trends.get("aggregationAxisFormat"),
        value_prefix=trends.get("aggregationAxisPrefix"),
        value_postfix=trends.get("aggregationAxisPostfix"),
        decimal_places=None if places is None else min(max(int(places), 0), 9),
    )
