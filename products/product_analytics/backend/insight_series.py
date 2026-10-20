import json
from copy import deepcopy
from datetime import date
from typing import Any

from pydantic import BaseModel

from posthog.hogql_queries.apply_dashboard_filters import resolve_effective_dashboard_filters
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.hogql_queries.utils.result_series import (
    get_action_names,
    get_result_series,
    get_result_series_index,
    get_series_custom_name,
    get_series_key,
)
from posthog.models import Team, User
from posthog.schema_migrations.upgrade import upgrade
from posthog.week_start_day import WeekStartDay

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
CHARTED_SQL_DISPLAYS = {"ActionsLineGraph", "ActionsBar", "ActionsStackedBar", "ActionsAreaGraph"}
NO_BREAKDOWN_VALUE = "[No value]"
LOOKBACK = {"day": "-56d", "week": "-16w", "month": "-24m"}
DATE_FILTERS = ("date_from", "date_to", "explicitDate", "interval", "compareFilter")
EXECUTION_MODE = ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE
BLOCKING_EXECUTION_MODE = ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE


def _run(
    team: Team,
    user: User,
    source: dict[str, Any],
    filters: dict[str, Any] | None,
    variables: dict[str, Any] | None,
    blocking: bool = False,
) -> dict[str, Any]:
    from posthog.api.services.query import process_query_dict  # noqa: PLC0415

    response = process_query_dict(
        team,
        source,
        dashboard_filters_json=filters,
        variables_override_json=variables,
        execution_mode=BLOCKING_EXECUTION_MODE if blocking else EXECUTION_MODE,
        user=user,
    )
    return response.model_dump() if isinstance(response, BaseModel) else response


def _value_key(query: dict[str, Any], result: dict[str, Any], position: int) -> str:
    index = get_result_series_index(query, result)
    payload: dict[str, Any] = {
        "series": index if index is not None else f"formula{position + 1}" if position else "formula"
    }
    if "breakdown_value" in result:
        breakdown = result["breakdown_value"]
        payload["breakdown_value"] = breakdown if isinstance(breakdown, list) else [breakdown]
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _visible(query: dict[str, Any], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trends = query.get("trendsFilter") or {}
    customizations = trends.get("resultCustomizations") or {}
    if not customizations:
        return results
    by_position = trends.get("resultCustomizationBy") == "position"
    ranked = sorted(range(len(results)), key=lambda i: get_result_series_index(query, results[i]) or 0)
    positions = {index: rank for rank, index in enumerate(ranked)}
    return [
        result
        for index, result in enumerate(results)
        if not (
            customizations.get(str(positions[index]) if by_position else _value_key(query, result, positions[index]))
            or {}
        ).get("hidden")
    ]


def _decimal_places(places: Any) -> int | None:
    return None if places is None else min(max(int(places), 0), 9)


def _axis_settings(axis: dict[str, Any], key: str) -> dict[str, Any]:
    return (axis.get("settings") or {}).get(key) or {}


def _sql_period(days: list[date], week_start_day: int | None) -> str | None:
    gaps = {(later - earlier).days for earlier, later in zip(days, days[1:])}
    if not gaps:
        return None
    if min(gaps) == 1:
        return "day"
    first_weekday = 0 if week_start_day == WeekStartDay.MONDAY else 6
    if gaps == {7} and all(day.weekday() == first_weekday for day in days):
        return "week"
    months = [day.year * 12 + day.month for day in days]
    if all(day.day == 1 for day in days) and all(later - earlier == 1 for earlier, later in zip(months, months[1:])):
        return "month"
    return None


def _sql_series(
    team: Team,
    user: User,
    *,
    short_id: str,
    name: str | None,
    query: dict[str, Any],
    filters: dict[str, Any],
    variables: dict[str, Any] | None,
    blocking: bool = False,
) -> InsightSeries | None:
    settings = query.get("chartSettings") or {}
    x_column = (settings.get("xAxis") or {}).get("column")
    y_axes = [axis for axis in settings.get("yAxis") or [] if axis.get("column")]
    if query.get("display") not in CHARTED_SQL_DISPLAYS or not x_column or not y_axes:
        return None
    response = _run(team, user, query["source"], filters, variables, blocking)
    if response.get("hasMore"):
        return None
    position = {column: index for index, column in enumerate(response.get("columns") or [])}
    breakdown_column = settings.get("seriesBreakdownColumn")
    zero_fill = bool(settings.get("showNullsAsZero"))
    series: dict[tuple[int, tuple[bool, str] | None], dict[date, float]] = {}
    with_gaps: set[tuple[int, tuple[bool, str] | None]] = set()
    try:
        for row in response.get("results") or []:
            stamp = str(row[position[x_column]])
            if stamp[11:19] not in ("", "00:00:00"):
                return None
            day = date.fromisoformat(stamp[:10])
            breakdown = None
            if breakdown_column:
                raw = row[position[breakdown_column]]
                breakdown = (raw is None, NO_BREAKDOWN_VALUE if raw is None else str(raw))
            for index, axis in enumerate(y_axes):
                key = (index, breakdown)
                points = series.setdefault(key, {})
                if day in points:
                    return None
                value = row[position[axis["column"]]]
                if value is None and not zero_fill:
                    with_gaps.add(key)
                points[day] = float(value or 0)
    except (KeyError, TypeError, ValueError):
        return None
    series = {key: points for key, points in series.items() if key not in with_gaps}
    period = _sql_period(sorted({day for points in series.values() for day in points}), team.week_start_day)
    if period is None:
        return None
    named: dict[str, list[tuple[date, float]]] = {}
    copies: dict[str, int] = {}
    for (index, breakdown), points in series.items():
        base = str(_axis_settings(y_axes[index], "display").get("label") or y_axes[index]["column"])
        if breakdown is not None:
            base = f"{base} · {breakdown[1]}" if len(y_axes) > 1 else breakdown[1]
        label, copy = base, copies.get(base, 1)
        while label in named:
            copy += 1
            label = f"{base} ({copy})"
        copies[base] = copy
        named[label] = sorted(points.items())
    formatting = _axis_settings(y_axes[0], "formatting") if len(y_axes) == 1 else {}
    return InsightSeries(
        short_id=short_id,
        name=name,
        series=named,
        period=period,
        averaged_series=list(named),
        event_name="",
        value_format="percentage_scaled" if formatting.get("style") == "percent" else None,
        value_prefix=formatting.get("prefix") or None,
        value_postfix=formatting.get("suffix") or None,
        decimal_places=_decimal_places(formatting.get("decimalPlaces")),
    )


def insight_series(
    team: Team,
    user: User,
    *,
    short_id: str,
    name: str | None,
    query: dict[str, Any],
    dashboard: InsightDashboardContext | None,
    blocking: bool = False,
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
    if query.get("kind") == "DataVisualizationNode" and source.get("kind") == "HogQLQuery":
        return _sql_series(
            team,
            user,
            short_id=short_id,
            name=name,
            query=query,
            filters=filters,
            variables=variables,
            blocking=blocking,
        )
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
    response = _run(team, user, bounded, filters, variables, blocking)
    formula = bool(trends.get("formula") or trends.get("formulas") or trends.get("formulaNodes"))
    several = len(source.get("series") or []) > 1
    # `_run` executes the upgraded query, which stamps `kind` on series saved without one.
    series_source = upgrade(deepcopy(source))
    action_names = get_action_names(team, series_source)
    series: dict[str, list[tuple[date, float]]] = {}
    averaged: list[str] = []
    for result in _visible(series_source, response.get("results") or []):
        if not result.get("days"):
            continue
        node = get_result_series(series_source, result)
        shown = str(result.get("label") or "Series")
        series_label = (get_series_key(node, action_names) or "All events") if node is not None else None
        custom_name = get_series_custom_name(node, action_names) if node is not None else None
        label = str(custom_name or series_label or shown)
        breakdown = result.get("breakdown_value")
        if breakdown not in (None, ""):
            if series_label is not None:
                value = shown.removeprefix(f"{series_label} - ") if several else shown
            else:
                value = ", ".join(str(b) for b in breakdown) if isinstance(breakdown, list) else str(breakdown)
            label = f"{label} · {value}" if several else value
        while label in series:
            label += " (2)"
        series[label] = [
            (date.fromisoformat(str(d)[:10]), float(v or 0)) for d, v in zip(result["days"], result["data"])
        ]
        if formula or ((node or {}).get("math") or "total") not in ADDITIVE_MATH:
            averaged.append(label)
    if not series:
        return None
    nodes = source.get("series") or []
    node = nodes[0] if len(nodes) == 1 else {}
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
        decimal_places=_decimal_places(trends.get("decimalPlaces")),
    )
