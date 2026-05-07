"""
BubbleUp: compare attribute distributions in a brushed region vs the full filtered baseline.
"""

import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from posthog.schema import DateRange, HogQLFilters, PropertyGroupFilter, TraceSpansQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload

from products.tracing.backend.constants import TRACE_SPANS_HEATMAP_SETTINGS
from products.tracing.backend.filter_builder import TraceSpansFilterBuilder
from products.tracing.backend.query_date_range import tracing_qdr_baseline, tracing_qdr_minutely

if TYPE_CHECKING:
    from posthog.models import Team


@dataclass(frozen=True)
class BubbleUpRegion:
    time_from: dt.datetime
    time_to: dt.datetime
    duration_min_nano: int
    duration_max_nano: int


def _merge_counts(rows: list[Any]) -> dict[tuple[str, str, str], int]:
    out: dict[tuple[str, str, str], int] = {}
    for row in rows or []:
        k, v, t, c = str(row[0]), str(row[1]), str(row[2]), int(row[3])
        key = (k, v, t)
        out[key] = out.get(key, 0) + c
    return out


def _inset_attribute_counts(
    team: "Team",
    *,
    where_inset: ast.Expr,
    date_range: DateRange,
    map_field: str,
    attribute_type_label: str,
) -> dict[tuple[str, str, str], int]:
    query = parse_select(
        f"""
        SELECT
            attribute_key,
            trace_spans.{map_field}[attribute_key] AS attribute_value,
            {{attr_type}} AS attribute_type,
            count() AS cnt
        FROM posthog.trace_spans AS trace_spans
        ARRAY JOIN mapKeys(trace_spans.{map_field}) AS attribute_key
        WHERE {{where_inset}}
        GROUP BY attribute_key, attribute_value, attribute_type
        """,
        placeholders={
            "where_inset": where_inset,
            "attr_type": ast.Constant(value=attribute_type_label),
        },
    )

    resp = execute_hogql_query(
        query_type="TracingBubbleUpInsetQuery",
        query=query,
        team=team,
        workload=Workload.LOGS,
        filters=HogQLFilters(dateRange=date_range),
        settings=TRACE_SPANS_HEATMAP_SETTINGS,
    )
    return _merge_counts(resp.results)


def run_bubble_up(
    team: "Team",
    *,
    date_range: DateRange,
    filter_group: PropertyGroupFilter | None,
    service_names: list[str] | None,
    status_codes: list[int] | None,
    root_spans: bool | None,
    region: BubbleUpRegion,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return ranked attribute key/value pairs enriched in the brushed region vs baseline."""
    base_query = TraceSpansQuery(
        dateRange=date_range,
        filterGroup=filter_group,
        serviceNames=service_names,
        statusCodes=status_codes,
        rootSpans=root_spans,
    )
    fb = TraceSpansFilterBuilder(team, base_query)
    qdr = tracing_qdr_minutely(team, date_range)

    where_base = fb.build_where(qdr)

    region_exprs = [
        parse_expr(
            "timestamp >= {t_from} AND timestamp < {t_to}",
            placeholders={
                "t_from": ast.Constant(value=region.time_from),
                "t_to": ast.Constant(value=region.time_to),
            },
        ),
        parse_expr(
            "duration_nano >= {d_min} AND duration_nano < {d_max}",
            placeholders={
                "d_min": ast.Constant(value=region.duration_min_nano),
                "d_max": ast.Constant(value=region.duration_max_nano),
            },
        ),
    ]
    where_inset = ast.And(exprs=[where_base, *region_exprs])

    inset_map = _inset_attribute_counts(
        team, where_inset=where_inset, date_range=date_range, map_field="attributes", attribute_type_label="span"
    )
    for k, v in _inset_attribute_counts(
        team,
        where_inset=where_inset,
        date_range=date_range,
        map_field="resource_attributes",
        attribute_type_label="resource",
    ).items():
        inset_map[k] = inset_map.get(k, 0) + v

    inset_total = sum(inset_map.values())

    baseline_qdr = tracing_qdr_baseline(team, date_range)

    baseline_query = parse_select(
        """
        SELECT
            attribute_key,
            attribute_value,
            attribute_type,
            sum(attribute_count) AS cnt
        FROM posthog.trace_attributes
        WHERE team_id = {team_id}
          AND time_bucket >= {date_from_start_of_interval}
          AND time_bucket <= {date_to_start_of_interval} + {one_interval_period}
        GROUP BY team_id, attribute_key, attribute_value, attribute_type
        """,
        placeholders={
            **baseline_qdr.to_placeholders(),
            "team_id": ast.Constant(value=team.pk),
        },
    )

    baseline_resp = execute_hogql_query(
        query_type="TracingBubbleUpBaselineQuery",
        query=baseline_query,
        team=team,
        workload=Workload.LOGS,
        filters=HogQLFilters(dateRange=date_range),
        settings=TRACE_SPANS_HEATMAP_SETTINGS,
    )

    baseline_map = _merge_counts(baseline_resp.results)
    baseline_total = sum(baseline_map.values())

    if inset_total <= 0 or baseline_total <= 0:
        return []

    scored: list[dict[str, Any]] = []
    for key, inset_c in inset_map.items():
        if inset_c < 5:
            continue
        base_c = baseline_map.get(key, 1)
        p_in = inset_c / inset_total
        p_base = max(base_c / baseline_total, 1e-9)
        lift = p_in / p_base
        scored.append(
            {
                "attribute_key": key[0],
                "attribute_value": key[1],
                "attribute_type": key[2],
                "inset_count": inset_c,
                "baseline_count": base_c,
                "lift": round(lift, 4),
            }
        )

    scored.sort(key=lambda x: (-x["lift"], -x["inset_count"]))
    return scored[:limit]
