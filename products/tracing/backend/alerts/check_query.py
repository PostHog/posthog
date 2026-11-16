"""The query one traces alert check runs against `trace_spans`.

One query per check reads the whole lookback once and returns one value per rolling window, so the
N-of-M decision costs no more than its oldest window. A grouped check returns one row per group.

A request is an entry span: a trace root, or a server or consumer span. That is the tracing scene's
service health definition, so a person who opens the scene from an alert sees the same numbers.
"""

import time
from collections.abc import Sequence
from typing import Final

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import HogQLQueryExecutor

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser, Workload, get_pool
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.models import Team

from products.alerts_platform.backend.facade.rolling_checks import CheckWindow
from products.tracing.backend.alerts.source_config import TracesPlatformAlertCondition, TracesPlatformAlertConfig
from products.tracing.backend.logic import span_filter_exprs, split_span_filters

# The same ceiling logs alerts use. A check over it fails as too expensive instead of slowing the cluster.
MAX_BYTES_TO_READ: Final = 5 * 1024**3
_ENTRY_SPAN: Final = "(is_root_span = 1 OR kind IN (2, 5))"
_ERROR: Final = "status_code = 2"
_NANOS_PER_MILLISECOND: Final = 1_000_000
# How long past the server's execution limit a socket read may wait, so a stalled connection fails
# rather than holding a worker thread after the evaluation activity has timed out.
_TRANSPORT_MARGIN_SECONDS: Final = 5


@frozen
class GroupValues:
    """One group's measure in each window, oldest first. None where the window holds no request."""

    labels: dict[str, str]
    values: tuple[float | None, ...]


@frozen
class CheckResult:
    groups: tuple[GroupValues, ...]
    query_duration_ms: int
    # More groups than the limit matched, so a group the result leaves out may still have requests.
    truncated: bool


def _in_window(window: CheckWindow) -> ast.Expr:
    return parse_expr(
        "timestamp >= {start} AND timestamp < {end}",
        placeholders={"start": ast.Constant(value=window.start), "end": ast.Constant(value=window.end)},
    )


def _measure(condition: TracesPlatformAlertCondition, window: CheckWindow) -> ast.Expr:
    in_window = _in_window(window)
    requests = parse_expr("countIf({w})", placeholders={"w": in_window})
    if condition.measure == "request_count":
        return requests
    errors = parse_expr(f"countIf({{w}} AND {_ERROR})", placeholders={"w": in_window})
    if condition.measure == "error_count":
        return errors
    if condition.measure == "error_rate":
        # No requests is no data, not a 0% rate.
        return parse_expr(
            "if({requests} = 0, NULL, {errors} / {requests})", placeholders={"requests": requests, "errors": errors}
        )
    return parse_expr(
        "if({requests} = 0, NULL, quantileIf({level})(duration_nano, {w}) / {per_ms})",
        placeholders={
            "requests": requests,
            "level": ast.Constant(value=(condition.percentile or 0) / 100),
            "w": in_window,
            "per_ms": ast.Constant(value=_NANOS_PER_MILLISECOND),
        },
    )


def build_check_query(
    team: Team,
    config: TracesPlatformAlertConfig,
    windows: Sequence[CheckWindow],
    *,
    group_by: Sequence[str],
    open_groups: Sequence[dict[str, str]],
    datapoints_to_alarm: int,
    limit: int,
) -> ast.SelectQuery:
    lookback_start, check_end = windows[0].start, windows[-1].end
    where: list[ast.Expr] = [
        # time_bucket leads the sort key after the team, so this bound is what prunes the read.
        parse_expr(
            "time_bucket >= toStartOfInterval({start}, toIntervalHour(4)) AND time_bucket <= {end}",
            placeholders={"start": ast.Constant(value=lookback_start), "end": ast.Constant(value=check_end)},
        ),
        parse_expr(
            "timestamp >= {start} AND timestamp < {end}",
            placeholders={"start": ast.Constant(value=lookback_start), "end": ast.Constant(value=check_end)},
        ),
        parse_expr(_ENTRY_SPAN),
        *span_filter_exprs(
            team, split_span_filters(config.filters.filterGroup), service_names=config.filters.serviceNames
        ),
    ]
    periods = [
        ast.Alias(alias=f"period_{index}", expr=_measure(config.condition, window))
        for index, window in enumerate(windows)
    ]
    return ast.SelectQuery(
        select=[*(ast.Field(chain=[column]) for column in group_by), *periods],
        select_from=ast.JoinExpr(table=ast.Field(chain=["posthog", "trace_spans"])),
        where=ast.And(exprs=where),
        group_by=[ast.Field(chain=[column]) for column in group_by] or None,
        order_by=_ranking(config.condition, len(windows), group_by, open_groups, datapoints_to_alarm)
        if group_by
        else None,
        limit=ast.Constant(value=limit + 1) if group_by else None,
    )


def _ranking(
    condition: TracesPlatformAlertCondition,
    window_count: int,
    group_by: Sequence[str],
    open_groups: Sequence[dict[str, str]],
    datapoints_to_alarm: int,
) -> list[ast.OrderExpr]:
    """Open groups first, then groups that breach N of M, then the worst newest value.

    An open group has to come back whatever its value, or the check could not resolve it. Ranking by
    the N-of-M verdict before the newest value keeps a steady breach that the limit would otherwise
    cut behind groups that spiked once and do not breach.
    """
    above = condition.threshold_operator == "above"
    breached_windows = ast.Call(
        name="arraySum",
        args=[
            ast.Array(
                exprs=[
                    # A window with no data never breaches, as in `derive_breaches`.
                    ast.Call(
                        name="ifNull",
                        args=[
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.Gt if above else ast.CompareOperationOp.Lt,
                                left=ast.Field(chain=[f"period_{index}"]),
                                right=ast.Constant(value=condition.threshold),
                            ),
                            ast.Constant(value=0),
                        ],
                    )
                    for index in range(window_count)
                ]
            )
        ],
    )
    order_by = [
        ast.OrderExpr(
            expr=ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq, left=breached_windows, right=ast.Constant(value=datapoints_to_alarm)
            ),
            order="DESC",
        ),
        ast.OrderExpr(expr=ast.Field(chain=[f"period_{window_count - 1}"]), order="DESC" if above else "ASC"),
    ]
    if open_groups:
        group = ast.Tuple(exprs=[ast.Field(chain=[column]) for column in group_by])
        known = ast.Tuple(
            exprs=[
                ast.Tuple(exprs=[ast.Constant(value=labels.get(column, "")) for column in group_by])
                for labels in open_groups
            ]
        )
        order_by.insert(
            0,
            ast.OrderExpr(
                expr=ast.CompareOperation(op=ast.CompareOperationOp.In, left=group, right=known), order="DESC"
            ),
        )
    return order_by


def run_check_query(
    team: Team,
    config: TracesPlatformAlertConfig,
    windows: Sequence[CheckWindow],
    *,
    group_by: Sequence[str],
    open_groups: Sequence[dict[str, str]],
    datapoints_to_alarm: int,
    limit: int,
    configuration_id: str,
    max_execution_time: int,
) -> CheckResult:
    tag_queries(
        product=Product.TRACING,
        feature=Feature.ALERTING,
        source="traces_alert",
        alert_config_id=configuration_id,
        team_id=str(team.id),
    )
    sql, context = HogQLQueryExecutor(
        query_type="traces_alert_check",
        query=build_check_query(
            team,
            config,
            windows,
            group_by=group_by,
            open_groups=open_groups,
            datapoints_to_alarm=datapoints_to_alarm,
            limit=limit,
        ),
        team=team,
        workload=Workload.LOGS,
        # Throw rather than break: a partial read could resolve an alert that is breaching.
        settings=HogQLGlobalSettings(
            max_execution_time=max_execution_time,
            timeout_overflow_mode="throw",
            max_bytes_to_read=MAX_BYTES_TO_READ,
            read_overflow_mode="throw",
        ),
        limit_context=LimitContext.QUERY,
        modifiers=HogQLQueryModifiers(convertToProjectTimezone=False),
    ).generate_clickhouse_sql()
    pool = get_pool(
        workload=Workload.LOGS,
        ch_user=ClickHouseUser.ALERTS_PLATFORM_TRACES,
        send_receive_timeout=max_execution_time + _TRANSPORT_MARGIN_SECONDS,
    )
    started = time.monotonic()
    with pool.get_client() as client:
        results = sync_execute(
            sql, context.values, workload=Workload.LOGS, team_id=team.id, readonly=True, sync_client=client
        )
    duration_ms = int((time.monotonic() - started) * 1000)
    width = len(group_by)
    # An ungrouped query aggregates without GROUP BY, so it returns exactly one row. A grouped one
    # keeps its row past `limit`, so admission sees that group and reports it as overflow when it breaches.
    rows = (results or [])[: None if group_by else 1]
    groups = tuple(
        GroupValues(
            labels={column: str(value) for column, value in zip(group_by, row[:width])},
            values=tuple(None if value is None else float(value) for value in row[width:]),
        )
        for row in rows
    )
    truncated = bool(group_by) and len(results or []) > limit
    return CheckResult(groups=groups, query_duration_ms=duration_ms, truncated=truncated)


def window_values_with_no_requests(condition: TracesPlatformAlertCondition, count: int) -> tuple[float | None, ...]:
    """What a window with no request measures: zero for a count, no data for a share or a latency."""
    return tuple(0.0 if condition.measure in ("request_count", "error_count") else None for _ in range(count))
