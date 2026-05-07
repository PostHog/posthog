"""
Builds HogQL WHERE clauses for trace span queries.

Single source of truth for list, sparkline, heatmap, and BubbleUp queries.
"""

import json
import time
import base64
import decimal
import datetime as dt
from typing import TYPE_CHECKING

from posthog.schema import SpanPropertyFilter, SpanPropertyFilterType, TraceSpansQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr

from posthog.hogql_queries.utils.query_date_range import QueryDateRange

if TYPE_CHECKING:
    from posthog.models import Team


def _normalise_to_base64(value: str) -> str:
    try:
        int(value, 16)
        return base64.b64encode(bytes.fromhex(value)).decode()
    except ValueError:
        return value


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


def _duration_filter_value_to_nano_str(value: object) -> str:
    """Milliseconds (UI) → nanoseconds as decimal integer string for UInt64 `duration_nano`."""
    nano = decimal.Decimal(str(value)) * 1000000
    return str(int(nano.quantize(decimal.Decimal("1"), rounding=decimal.ROUND_HALF_UP)))


_SPAN_KIND_LABEL_TO_INT: dict[str, int] = {
    "Unspecified": 0,
    "Internal": 1,
    "Server": 2,
    "Client": 3,
    "Producer": 4,
    "Consumer": 5,
}

_STATUS_CODE_LABEL_TO_INTS: dict[str, list[int]] = {
    "OK": [0, 1],
    "Error": [2],
}


class TraceSpansFilterBuilder:
    """Builds `ast.Expr` WHERE clauses from TraceSpansQuery + date range placeholders."""

    def __init__(self, team: "Team", query: TraceSpansQuery) -> None:
        self.team = team
        self.query = query

        def get_property_type(value: str | float | bool) -> str:
            try:
                float(value)
                return "float"
            except (ValueError, TypeError):
                pass
            return "str"

        self.span_filters: list[SpanPropertyFilter] = []
        self.span_attribute_filters: list[SpanPropertyFilter] = []
        self.resource_attribute_filters: list[SpanPropertyFilter] = []
        if self.query.filterGroup and self.query.filterGroup.values:
            for property_group in self.query.filterGroup.values:
                for prop in property_group.values:
                    prop_type = getattr(prop, "type", None)
                    if prop_type == SpanPropertyFilterType.SPAN_RESOURCE_ATTRIBUTE:
                        self.resource_attribute_filters.append(prop)
                    if prop_type == SpanPropertyFilterType.SPAN:
                        self.span_filters.append(prop)
                    elif prop_type == SpanPropertyFilterType.SPAN_ATTRIBUTE:
                        if isinstance(prop, SpanPropertyFilter) and prop.value:
                            property_type = "str"
                            if isinstance(prop.value, list):
                                property_types = {get_property_type(v) for v in prop.value}
                                if len(property_types) == 1:
                                    property_type = property_types.pop()
                            else:
                                property_type = get_property_type(prop.value)

                            prop = prop.model_copy(deep=True)
                            prop.key = f"{prop.key}__{property_type}"

                        self.span_attribute_filters.append(prop)

    def build_where(self, query_date_range: QueryDateRange) -> ast.Expr:
        exprs: list[ast.Expr] = []

        exprs.append(
            parse_expr(
                "toStartOfDay(time_bucket) >= toStartOfDay({date_from}) and toStartOfDay(time_bucket) <= toStartOfDay({date_to})",
                placeholders={
                    **query_date_range.to_placeholders(),
                },
            )
        )

        exprs.append(ast.Placeholder(expr=ast.Field(chain=["filters"])))

        # Default root-only (matches list UI); trace detail sets rootSpans=False explicitly.
        root_only = True if self.query.rootSpans is None else self.query.rootSpans
        if root_only:
            exprs.append(parse_expr("is_root_span = true"))

        if self.query.serviceNames:
            exprs.append(
                parse_expr(
                    "service_name IN {serviceNames}",
                    placeholders={
                        "serviceNames": ast.Tuple(exprs=[ast.Constant(value=str(sn)) for sn in self.query.serviceNames])
                    },
                )
            )

        if self.query.statusCodes:
            exprs.append(
                parse_expr(
                    "status_code IN {statusCodes}",
                    placeholders={
                        "statusCodes": ast.Tuple(exprs=[ast.Constant(value=int(sc)) for sc in self.query.statusCodes])
                    },
                )
            )

        if self.span_filters:
            for span_filter in self.span_filters:
                if span_filter.key in ("trace_id", "span_id"):
                    if isinstance(span_filter.value, list):
                        span_filter.value = [_normalise_to_base64(str(v)) for v in span_filter.value]
                    else:
                        span_filter.value = _normalise_to_base64(str(span_filter.value))

                if span_filter.key in ("duration",):
                    span_filter.key = "duration_nano"

                    if isinstance(span_filter.value, list):
                        span_filter.value = [
                            _duration_filter_value_to_nano_str(v) for v in span_filter.value if _is_number(str(v))
                        ]
                    else:
                        if _is_number(str(span_filter.value)):
                            span_filter.value = _duration_filter_value_to_nano_str(span_filter.value)

                    # #region agent log
                    with open("/Users/danielvisca/Development/posthog/.cursor/debug-f7867f.log", "a") as _dbg_f:
                        _dbg_f.write(
                            json.dumps(
                                {
                                    "sessionId": "f7867f",
                                    "hypothesisId": "A",
                                    "location": "filter_builder.py:duration_nano",
                                    "message": "duration filter normalized to nano str",
                                    "data": {"value": span_filter.value},
                                    "timestamp": int(time.time() * 1000),
                                }
                            )
                            + "\n"
                        )
                    # #endregion

                if span_filter.key == "kind":
                    values = span_filter.value if isinstance(span_filter.value, list) else [str(span_filter.value)]
                    span_filter.value = [
                        _SPAN_KIND_LABEL_TO_INT[str(v)] for v in values if str(v) in _SPAN_KIND_LABEL_TO_INT
                    ]

                if span_filter.key == "status_code":
                    values = span_filter.value if isinstance(span_filter.value, list) else [str(span_filter.value)]
                    expanded: list[int] = []
                    for v in values:
                        if str(v) in _STATUS_CODE_LABEL_TO_INTS:
                            expanded.extend(_STATUS_CODE_LABEL_TO_INTS[str(v)])
                    span_filter.value = [str(v) for v in expanded]

                exprs.append(property_to_expr(span_filter, team=self.team))

        if self.span_attribute_filters:
            exprs.append(property_to_expr(self.span_attribute_filters, team=self.team))

        if self.resource_attribute_filters:
            for f in self.resource_attribute_filters:
                exprs.append(property_to_expr(f, team=self.team))

        if self.query.traceId:
            trace_id_b64 = base64.b64encode(bytes.fromhex(self.query.traceId)).decode("ascii")
            exprs.append(
                parse_expr(
                    "trace_id = {traceId}",
                    placeholders={
                        "traceId": ast.Constant(value=trace_id_b64),
                    },
                )
            )

        if self.query.after:
            try:
                cursor = json.loads(base64.b64decode(self.query.after).decode("utf-8"))
                cursor_ts = dt.datetime.fromisoformat(cursor["timestamp"])
                cursor_uuid = cursor["uuid"]
            except (KeyError, ValueError, json.JSONDecodeError) as e:
                raise ValueError(f"Invalid cursor format: {e}") from e

            op = ">" if self.query.orderBy == "earliest" else "<"
            ts_op = ">=" if self.query.orderBy == "earliest" else "<="

            exprs.append(
                parse_expr(
                    f"time_bucket {ts_op} toStartOfDay({{cursor_ts}})",
                    placeholders={"cursor_ts": ast.Constant(value=cursor_ts)},
                )
            )
            exprs.append(
                parse_expr(
                    f"timestamp {ts_op} {{cursor_ts}}",
                    placeholders={"cursor_ts": ast.Constant(value=cursor_ts)},
                )
            )
            exprs.append(
                parse_expr(
                    f"(timestamp, uuid) {op} ({{cursor_ts}}, {{cursor_uuid}})",
                    placeholders={
                        "cursor_ts": ast.Constant(value=cursor_ts),
                        "cursor_uuid": ast.Constant(value=cursor_uuid),
                    },
                )
            )

        return ast.And(exprs=exprs)
