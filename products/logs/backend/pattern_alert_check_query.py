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

from products.logs.backend.alert_check_query import (
    AlertCheckQuery,
    _tag_alert_query,
    build_alert_where_expr,
    is_projection_eligible,
)
from products.logs.backend.models import LogsAlertConfiguration

# Per-check cap on distinct (service_name, pattern) groups. Past this, the alert's
# filters are too broad for per-fingerprint semantics and the check errors with an
# actionable message instead of silently dropping groups.
MAX_PATTERN_GROUPS = 1_000

# Per-simulation cap on total (bucket, group) rows. A simulate preview covers up to
# MAX_SIMULATE_LOOKBACK_DAYS of history, so this bounds query cost independently of
# the per-bucket MAX_PATTERN_GROUPS cap.
MAX_SIMULATE_PATTERN_ROWS = 50_000


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


@dataclass(frozen=True)
class BucketedPatternGroups:
    timestamp: dt.datetime
    groups: list[PatternGroupCount]


@dataclass(frozen=True)
class BucketedPatternGroupsResult:
    buckets: list[BucketedPatternGroups]
    # True when the query hit its row cap and dropped groups. The caller decides how
    # to surface it (the simulate preview reports this as a warning, not an error).
    truncated: bool
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

    def execute_bucketed_groups(
        self, *, interval_minutes: int, limit: int = MAX_SIMULATE_PATTERN_ROWS
    ) -> BucketedPatternGroupsResult:
        """Occurrence counts per (bucket, service_name, pattern) across the window, for
        the simulate preview. Buckets with no stamped rows are omitted; the caller fills
        gaps the same way `AlertCheckQuery.execute_bucketed` does for count triggers.

        Buckets are ASC (oldest-first), matching `execute_bucketed`'s contract.
        """
        self._tag()
        time_field = (
            ast.Call(name="toStartOfMinute", args=[ast.Field(chain=["timestamp"])])
            if is_projection_eligible(self.alert.filters)
            else ast.Field(chain=["timestamp"])
        )
        query = parse_select(
            """
            SELECT
                toStartOfInterval({time_field}, toIntervalMinute({bucket_minutes})) AS bucket,
                service_name,
                pattern,
                max(pattern_version) AS pattern_version,
                count() AS occurrences
            FROM logs
            WHERE {where} AND pattern != ''
            GROUP BY bucket, service_name, pattern
            ORDER BY bucket ASC
            LIMIT {row_limit}
            """,
            placeholders={
                "time_field": time_field,
                "bucket_minutes": ast.Constant(value=interval_minutes),
                "where": self.where_expr,
                # +1 so the caller can tell "exactly limit rows" from "truncated".
                "row_limit": ast.Constant(value=limit + 1),
            },
        )

        start_ms = time.monotonic_ns() // 1_000_000
        response = self._run_query(query)
        duration_ms = time.monotonic_ns() // 1_000_000 - start_ms

        rows = response.results or []
        truncated = len(rows) > limit
        rows = rows[:limit]

        buckets: list[BucketedPatternGroups] = []
        current_bucket: dt.datetime | None = None
        current_groups: list[PatternGroupCount] = []
        for bucket, service_name, pattern, pattern_version, occurrences in rows:
            if bucket != current_bucket:
                if current_bucket is not None:
                    buckets.append(BucketedPatternGroups(timestamp=current_bucket, groups=current_groups))
                current_bucket = bucket
                current_groups = []
            current_groups.append(
                PatternGroupCount(
                    service_name=service_name, pattern=pattern, pattern_version=pattern_version, occurrences=occurrences
                )
            )
        if current_bucket is not None:
            buckets.append(BucketedPatternGroups(timestamp=current_bucket, groups=current_groups))

        return BucketedPatternGroupsResult(buckets=buckets, truncated=truncated, query_duration_ms=duration_ms)

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
