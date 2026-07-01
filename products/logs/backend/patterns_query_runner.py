import datetime as dt
from functools import cached_property
from math import ceil
from typing import TYPE_CHECKING

from posthog.schema import CachedLogsQueryResponse, LogsQuery

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner

from products.logs.backend.log_patterns import LogSample, MinedPattern, _env, mine_patterns
from products.logs.backend.logs_query_runner import LogsQueryResponse, LogsQueryRunnerMixin

if TYPE_CHECKING:
    from posthog.models import User


class PatternsQueryRunner(AnalyticsQueryRunner[LogsQueryResponse], LogsQueryRunnerMixin):
    """Mines log templates (Drain3) from an evenly-distributed sample of the matching logs.

    Sampling keeps clustering cheap on large windows: we count the matching rows, then pull
    at most `LOGS_PATTERNS_SAMPLE_LIMIT` of them spread across the window via a random-modulo
    predicate, and feed those bodies to `mine_patterns`. `sampled` is True whenever the
    window held more rows than the sample cap.
    """

    query: LogsQuery
    cached_response: CachedLogsQueryResponse

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        # Bytes are intentionally uncapped: a hard `max_bytes_to_read` + "throw" cap 500s on
        # wide windows (the symbol-stats read-cap cliff), so we bound by wall-clock instead
        # and let the sample query's LIMIT short-circuit the scan.
        return HogQLGlobalSettings(
            max_execution_time=_env("LOGS_PATTERNS_MAX_EXECUTION_TIME", 60, int),
            max_bytes_to_read=None,
            read_overflow_mode=None,
        )

    @cached_property
    def _sample_limit(self) -> int:
        return _env("LOGS_PATTERNS_SAMPLE_LIMIT", 10000, int)

    def validate_query_runner_access(self, user: "User") -> bool:
        # Defensive: this runner is invoked directly via the logs API, never through the generic
        # /api/projects/:id/query/ endpoint. Mirror LogsQueryRunner and refuse user-initiated
        # generic-query access so it can't silently bypass that gate if ever registered.
        from posthog.rbac.user_access_control import UserAccessControlError

        raise UserAccessControlError("logs", "viewer")

    def _calculate(self) -> LogsQueryResponse:
        total = self._count()
        sampled = total > self._sample_limit
        divisor = _sample_divisor(total, self._sample_limit)

        response = self._execute(self._sample_query(divisor))
        samples = [
            LogSample(
                body=row[0],
                severity_text=row[1],
                service_name=row[2],
                timestamp=row[3].replace(tzinfo=dt.UTC),
            )
            for row in response.results
        ]
        patterns = mine_patterns(samples)
        return LogsQueryResponse(
            results={
                "patterns": [_serialize(p) for p in patterns],
                "scanned_count": len(samples),
                "total_count": total,
                "sampled": sampled,
            }
        )

    def run(self, *args, **kwargs) -> LogsQueryResponse | CachedLogsQueryResponse:
        response = super().run(*args, **kwargs)
        assert isinstance(response, LogsQueryResponse | CachedLogsQueryResponse)
        return response

    def to_query(self) -> ast.SelectQuery:
        # Canonical (unsampled) form for the base runner's query contract; _calculate picks
        # the runtime divisor.
        return self._sample_query(divisor=1)

    def _execute(self, query: ast.SelectQuery | ast.SelectSetQuery):
        return execute_hogql_query(
            query_type="LogsQuery",
            query=query,
            modifiers=self.modifiers,
            team=self.team,
            workload=Workload.LOGS,
            timings=self.timings,
            limit_context=self.limit_context,
            settings=self.settings,
        )

    def _count(self) -> int:
        response = self._execute(
            parse_select(
                "SELECT count() FROM logs WHERE {where}",
                placeholders={"where": self._where_with_timestamp()},
            )
        )
        return int(response.results[0][0]) if response.results else 0

    def _where_with_timestamp(self) -> ast.Expr:
        # LogsFilterBuilder.where() filters at day-precision via time_bucket; add explicit
        # per-row timestamp bounds (half-open) so the sample matches the requested window.
        return ast.And(
            exprs=[
                self.where(),
                parse_expr(
                    "timestamp >= {date_from} AND timestamp < {date_to}",
                    placeholders={
                        "date_from": ast.Constant(value=self.query_date_range.date_from()),
                        "date_to": ast.Constant(value=self.query_date_range.date_to()),
                    },
                ),
            ]
        )

    def _sample_query(self, divisor: int) -> ast.SelectQuery:
        # Even-random sampling: rand() is per-row uniform and independent of timestamp, so
        # `rand() % divisor = 0` keeps ~1/divisor of rows spread evenly across the window.
        # divisor == 1 means no sampling, so we skip the modulo predicate entirely.
        where: ast.Expr = self._where_with_timestamp()
        if divisor > 1:
            where = ast.And(
                exprs=[
                    where,
                    parse_expr("rand() % {divisor} = 0", placeholders={"divisor": ast.Constant(value=divisor)}),
                ]
            )
        query = parse_select(
            """
            SELECT body, severity_text, service_name, timestamp
            FROM logs
            WHERE {where}
            LIMIT {limit}
            """,
            placeholders={"where": where, "limit": ast.Constant(value=self._sample_limit)},
        )
        assert isinstance(query, ast.SelectQuery)
        return query


def _sample_divisor(total: int, sample_limit: int) -> int:
    # Round up so total / divisor <= sample_limit: the rand()-modulo predicate alone bounds the
    # sample and LIMIT never truncates the random subset in (biased) read order.
    if total <= sample_limit:
        return 1
    return ceil(total / sample_limit)


def _serialize(pattern: MinedPattern) -> dict:
    return {
        "pattern": pattern.pattern,
        "count": pattern.count,
        "volume_share_pct": pattern.volume_share_pct,
        "error_count": pattern.error_count,
        "first_seen": pattern.first_seen.isoformat(),
        "last_seen": pattern.last_seen.isoformat(),
        "examples": pattern.examples,
        "services": pattern.services,
    }
