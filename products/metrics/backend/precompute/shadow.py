"""Shadow checks: a sampled tile's precomputed answer compared with the same query run raw, away from the viewer.

The raw run reads the whole window, so a viewer who waited for it waited as long as for a tile with no precomputed
metric at all. A sampled tile queues a Celery task instead. The task rebuilds the query from a JSON payload, runs it
both ways and reports the difference as the `metrics precompute shadow checked` event.
"""

import datetime as dt
from typing import Any

from products.metrics.backend.facade.contracts import (
    MetricFilter,
    MetricGroupBy,
    MetricQueryClause,
    MetricQueryRequest,
    MetricQueryShadowCheck,
    MetricSeries,
)
from products.metrics.backend.facade.enums import (
    AttributeScope,
    FilterOp,
    MetricAggregation,
    MetricRangeFunction,
    MetricType,
)

SHADOW_EVENT = "metrics precompute shadow checked"
# The facade sends the task by name and queue because importing the task module or `CeleryQueue` from there would
# load every task module, and the one that imports the facade would be a cycle. The queue is `CeleryQueue.LONG_RUNNING`.
SHADOW_CHECK_TASK = "products.metrics.backend.tasks.tasks.check_precomputed_shadow"
SHADOW_CHECK_QUEUE = "long_running"
BUILDER = "builder"
PROMQL = "promql"


def builder_payload(request: MetricQueryRequest) -> dict[str, Any]:
    """A JSON-safe copy of a builder request, for `builder_request` to rebuild."""
    return {
        "clauses": [
            {
                "name": clause.name,
                "metric_name": clause.metric_name,
                "aggregation": clause.aggregation.value,
                "filters": [
                    {"key": f.key, "op": f.op.value, "value": f.value, "scope": f.scope.value} for f in clause.filters
                ],
                "group_by": [{"key": g.key, "scope": g.scope.value} for g in clause.group_by],
                "quantile": clause.quantile,
                "metric_type": clause.metric_type.value if clause.metric_type is not None else None,
                "range_function": clause.range_function.value if clause.range_function is not None else None,
                "apdex_threshold_ms": clause.apdex_threshold_ms,
            }
            for clause in request.clauses
        ],
        "date_from": request.date_from.isoformat(),
        "date_to": request.date_to.isoformat(),
        "interval": request.interval,
        "formula": request.formula,
        "zero_fill": request.zero_fill,
        "rank_by_last_bucket": request.rank_by_last_bucket,
    }


def builder_request(payload: dict[str, Any]) -> MetricQueryRequest:
    clauses = tuple(
        MetricQueryClause(
            name=clause["name"],
            metric_name=clause["metric_name"],
            aggregation=MetricAggregation(clause["aggregation"]),
            filters=tuple(
                MetricFilter(key=f["key"], op=FilterOp(f["op"]), value=f["value"], scope=AttributeScope(f["scope"]))
                for f in clause["filters"]
            ),
            group_by=tuple(MetricGroupBy(key=g["key"], scope=AttributeScope(g["scope"])) for g in clause["group_by"]),
            quantile=clause["quantile"],
            metric_type=MetricType(clause["metric_type"]) if clause["metric_type"] else None,
            range_function=MetricRangeFunction(clause["range_function"]) if clause["range_function"] else None,
            apdex_threshold_ms=clause["apdex_threshold_ms"],
        )
        for clause in payload["clauses"]
    )
    return MetricQueryRequest(
        clauses=clauses,
        date_from=dt.datetime.fromisoformat(payload["date_from"]),
        date_to=dt.datetime.fromisoformat(payload["date_to"]),
        interval=payload["interval"],
        formula=payload["formula"],
        zero_fill=payload["zero_fill"],
        rank_by_last_bucket=payload["rank_by_last_bucket"],
    )


def compare(precomputed: list[MetricSeries], raw: list[MetricSeries]) -> MetricQueryShadowCheck:
    def points(result: list[MetricSeries]) -> dict[tuple, float | None]:
        return {(s.clause, tuple(sorted(s.labels.items())), p.time): p.value for s in result for p in s.points}

    precomputed_points, raw_points = points(precomputed), points(raw)
    differences = [
        abs(value - raw_value) / max(abs(raw_value), 1e-12)
        for key, raw_value in raw_points.items()
        if raw_value is not None and (value := precomputed_points.get(key)) is not None
    ]
    return MetricQueryShadowCheck(
        max_relative_difference=max(differences, default=0.0),
        mismatched_points=sum(
            1
            for key in precomputed_points.keys() | raw_points.keys()
            if (precomputed_points.get(key) is None) != (raw_points.get(key) is None)
        ),
    )
