"""Grouped ClickHouse queries for pattern-trigger alert checks.

Pattern triggers group the check window by the ingest-stamped `pattern` column
(deterministic per-row masking, see nodejs/src/logs/log-pattern-mask.ts), so a
(service_name, pattern) group is a stable per-callsite error fingerprint. This
module only runs the queries; the seen-set diff and trigger semantics live in
`pattern_alert_evaluator.py`.

Unlike the count checks, these queries return rows (one per group), so they
cannot join `BatchedAlertCheckQuery`'s countIf-column batching. The cohort
orchestrator runs them per alert.
"""

import time
import datetime as dt
from dataclasses import dataclass

from posthog.schema import HogQLQueryModifiers, HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team

from products.logs.backend.alert_check_query import AlertCheckQuery, _tag_alert_query, build_alert_where_expr
from products.logs.backend.models import LogsAlertConfiguration

# Per-check cap on distinct (service_name, pattern) groups. Past this, the alert's
# filters are too broad for per-fingerprint semantics and the check errors with an
# actionable message instead of silently dropping groups.
MAX_PATTERN_GROUPS = 1_000


@dataclass(frozen=True)
class PatternGroupCount:
    service_name: str
    pattern: str
    pattern_version: int
    occurrences: int


@dataclass(frozen=True)
class PatternGroupsResult:
    groups: list[PatternGroupCount]
    # True when the query hit `limit` and dropped groups. The caller decides how to surface it.
    truncated: bool
    query_duration_ms: int


@dataclass(frozen=True)
class StampingProbeResult:
    total: int
    stamped: int
    query_duration_ms: int


class GroupedPatternCheckQuery:
    """Per-alert grouped query over `logs`, reusing the count check's WHERE builder,
    settings (timeout, byte budget), and query tagging."""

    SETTINGS = AlertCheckQuery.SETTINGS

    def __init__(
        self,
        *,
        team: Team,
        alert: LogsAlertConfiguration,
        date_from: dt.datetime,
        date_to: dt.datetime,
    ) -> None:
        if alert.team_id != team.id:
            raise ValueError(f"Alert {alert.id} belongs to team {alert.team_id}, not {team.id}")
        self.team = team
        self.alert = alert
        self.where_expr = build_alert_where_expr(team=team, alert=alert, date_from=date_from, date_to=date_to)

    def execute_groups(self, *, limit: int = MAX_PATTERN_GROUPS) -> PatternGroupsResult:
        """Occurrence counts per (service_name, pattern) in the window, largest first.

        Unstamped rows (`pattern = ''`) are excluded because they have no fingerprint
        identity. `max(pattern_version)` per group: the pattern string is a pure
        function of the body within a version, so rows sharing (service, pattern)
        across a version bump collapse into the newest version's group.
        """
        self._tag()
        query = parse_select(
            """
            SELECT
                service_name,
                pattern,
                max(pattern_version) AS pattern_version,
                count() AS occurrences
            FROM logs
            WHERE {where} AND pattern != ''
            GROUP BY service_name, pattern
            ORDER BY occurrences DESC
            LIMIT {row_limit}
            """,
            placeholders={
                "where": self.where_expr,
                # +1 so the caller can tell "exactly limit groups" from "truncated".
                "row_limit": ast.Constant(value=limit + 1),
            },
        )

        start_ms = time.monotonic_ns() // 1_000_000
        response = self._run_query(query)
        duration_ms = time.monotonic_ns() // 1_000_000 - start_ms

        rows = response.results or []
        truncated = len(rows) > limit
        groups = [
            PatternGroupCount(service_name=row[0], pattern=row[1], pattern_version=row[2], occurrences=row[3])
            for row in rows[:limit]
        ]
        return PatternGroupsResult(groups=groups, truncated=truncated, query_duration_ms=duration_ms)

    def execute_stamping_probe(self) -> StampingProbeResult:
        """Total vs pattern-stamped row counts for the window.

        Run only when `execute_groups` returns nothing, to distinguish "no logs
        matched" (fine) from "logs matched but none carry a stamped pattern"
        (stamping disabled, so the alert can never fire and must error instead).
        """
        self._tag()
        query = parse_select(
            """
            SELECT count() AS total, countIf(pattern != '') AS stamped
            FROM logs
            WHERE {where}
            """,
            placeholders={"where": self.where_expr},
        )

        start_ms = time.monotonic_ns() // 1_000_000
        response = self._run_query(query)
        duration_ms = time.monotonic_ns() // 1_000_000 - start_ms

        row = response.results[0] if response.results else (0, 0)
        return StampingProbeResult(total=row[0], stamped=row[1], query_duration_ms=duration_ms)

    def _run_query(self, query: ast.SelectQuery | ast.SelectSetQuery) -> HogQLQueryResponse:
        if not isinstance(query, ast.SelectQuery):
            raise ValueError("Failed to build pattern alert check query")
        return execute_hogql_query(
            query_type="pattern_alert_check",
            query=query,
            team=self.team,
            workload=Workload.LOGS,
            settings=self.SETTINGS,
            limit_context=LimitContext.QUERY,
            modifiers=HogQLQueryModifiers(convertToProjectTimezone=False),
        )

    def _tag(self) -> None:
        _tag_alert_query(team=self.team, alert_config_id=str(self.alert.id), source="logs_pattern_alert")
