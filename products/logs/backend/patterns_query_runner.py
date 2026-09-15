import datetime as dt
from dataclasses import replace
from functools import cached_property
from math import ceil
from time import monotonic
from typing import TYPE_CHECKING

import posthoganalytics

from posthog.schema import CachedLogsQueryResponse, LogsQuery

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.exceptions import ClickHouseQueryTimeOut
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.utils import get_instance_region

from products.logs.backend.log_patterns import (
    ERROR_SEVERITIES,
    LogSample,
    MinedPattern,
    _env,
    encoded_pattern_member_size,
    group_stored_patterns,
    mine_patterns,
)
from products.logs.backend.logs_query_runner import LogsQueryResponse, LogsQueryRunnerMixin

if TYPE_CHECKING:
    from posthog.models import User

_TimeSlice = tuple[dt.datetime, dt.datetime]
STORED_PATTERN_HEAD_MAX_BYTES = 65536


class PatternsQueryRunner(AnalyticsQueryRunner[LogsQueryResponse], LogsQueryRunnerMixin):
    """Mines log templates (Drain3) from a bounded, deterministic sample of the matching logs.

    The sampling has to respect two constraints at once:

    * A uniform per-row sampling predicate cannot be short-circuited by LIMIT — ClickHouse
      has to scan (and decompress `body` for) the whole eligible range to find the matches.
      On high-volume windows that blows the wall-clock budget, and a timed-out scan that
      returns partially is worse than an error: it silently mines patterns from whatever
      handful of rows the scan reached. So the rows eligible for sampling are capped at
      `LOGS_PATTERNS_MAX_SCAN_ROWS` via stratified time slices — evenly spaced sub-windows
      (`LOGS_PATTERNS_SLICE_COUNT` of them, the last aligned to the window end) that keep
      the sample spread across the window while bounding what the query may read. As a
      backstop, `timeout_overflow_mode="throw"` turns any remaining timeout into an error
      instead of a truncated sample.

    * Results should be reproducible: the same filters over the same window must mine the
      same patterns. The sampling predicate hashes the row's immutable `uuid`
      (`cityHash64(uuid) % divisor = 0`) rather than using `rand()`, so the sample — and
      therefore the mined patterns — is a pure function of the data and the divisor.

    `sampled` is True whenever fewer rows were scanned than the window held — i.e. whenever
    the reported per-pattern counts are extrapolated estimates rather than exact tallies,
    whether the scan was narrowed by hash-mod sampling or by the time slices (or both).
    """

    query: LogsQuery
    cached_response: CachedLogsQueryResponse
    use_stored_patterns: bool = True
    _query_deadline: float | None = None

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        # Bytes are intentionally uncapped: a hard `max_bytes_to_read` + "throw" cap 500s on
        # wide windows (the symbol-stats read-cap cliff). The scan is bounded by the time
        # slices instead; timeout_overflow_mode="throw" guarantees a slow scan surfaces as
        # an error rather than silently mining from a partial sample.
        return HogQLGlobalSettings(
            max_execution_time=_env("LOGS_PATTERNS_MAX_EXECUTION_TIME", 60, int),
            max_bytes_to_read=None,
            read_overflow_mode=None,
            timeout_overflow_mode="throw",
        )

    @cached_property
    def _sample_limit(self) -> int:
        return _env("LOGS_PATTERNS_SAMPLE_LIMIT", 10000, int)

    @cached_property
    def _scan_budget(self) -> int:
        return _env("LOGS_PATTERNS_MAX_SCAN_ROWS", 2_000_000, int)

    @cached_property
    def _slice_count(self) -> int:
        return _env("LOGS_PATTERNS_SLICE_COUNT", 12, int)

    @cached_property
    def _sparkline_bucket_count(self) -> int:
        return _env("LOGS_PATTERNS_SPARKLINE_BUCKETS", 24, int)

    def validate_query_runner_access(self, user: "User") -> bool:
        # Defensive: this runner is invoked directly via the logs API, never through the generic
        # /api/projects/:id/query/ endpoint. Mirror LogsQueryRunner and refuse user-initiated
        # generic-query access so it can't silently bypass that gate if ever registered.
        from products.access_control.backend.facade.user_access_control import UserAccessControlError

        raise UserAccessControlError("logs", "viewer")

    def _calculate(self) -> LogsQueryResponse:
        reason = "comparison" if not self.use_stored_patterns else "flag_disabled"
        if self.use_stored_patterns and self._stored_patterns_enabled:
            self._query_deadline = monotonic() + max(1, self.settings.max_execution_time or 60)
            versions = self._execute(
                parse_select(
                    "SELECT pattern_version, count(), countIf(trim(pattern) != '') FROM logs WHERE {where} GROUP BY pattern_version",
                    placeholders={"where": self._where_with_timestamp()},
                )
            ).results
            total = sum(int(row[1]) for row in versions)
            candidates = [(int(row[2]), int(row[0])) for row in versions if int(row[0]) > 0]
            covered, version = max(candidates, default=(0, 0))
            if total and covered * 100 >= total * 99:
                return self._calculate_stored_patterns(total, version, covered)
            reason = "insufficient_version_coverage" if total else "empty_window"
        else:
            total = self._count()
        return self._calculate_body_patterns(total, reason)

    @cached_property
    def _stored_patterns_enabled(self) -> bool:
        # only_evaluate_locally keeps this check off the network: it gates an interactive query, so
        # a flags-service round trip (plus its retry) would delay every patterns request. An
        # inconclusive local evaluation therefore means "off", which is body mining as before.
        # `group_properties` carries the organization id so an org-level rollout still resolves locally.
        team_id = str(self.team.pk)
        person_properties = {"team_id": team_id, "region": get_instance_region() or "DEV"}
        if self.user:
            person_properties["email"] = self.user.email
        return bool(
            posthoganalytics.feature_enabled(
                "logs_patterns_query_v2",
                str(self.user.distinct_id) if self.user else team_id,
                person_properties=person_properties,
                groups={"organization": str(self.team.organization_id)},
                group_properties={"organization": {"id": str(self.team.organization_id)}},
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        )

    def _calculate_body_patterns(self, total: int, reason: str) -> LogsQueryResponse:
        slices = _time_slices(
            self.query_date_range.date_from(),
            self.query_date_range.date_to(),
            total=total,
            scan_budget=self._scan_budget,
            slice_count=self._slice_count,
        )
        # The slice row count is exact (counts don't read `body`, so a second count is cheap),
        # which keeps the divisor honest even when log volume is bursty across the window.
        pool = self._count(slices) if slices is not None else total
        divisor = _sample_divisor(pool, self._sample_limit)

        response = self._execute(self._sample_query(divisor, slices))
        samples = [
            LogSample(
                body=row[0],
                severity_text=row[1],
                service_name=row[2],
                timestamp=row[3].replace(tzinfo=dt.UTC),
            )
            for row in response.results
        ]
        # Sparkline buckets: when the scan is slice-bounded the slices ARE the buckets — they're
        # evenly spaced by construction and rows between them were never eligible, so uniform
        # buckets would render misleading zeros in the gaps. Unsliced windows bucket uniformly.
        buckets = (
            slices
            if slices is not None
            else _uniform_buckets(
                self.query_date_range.date_from(), self.query_date_range.date_to(), self._sparkline_bucket_count
            )
        )
        patterns = mine_patterns(samples, buckets=buckets)
        # `sampled` mirrors the exact condition `_serialize` uses to extrapolate: it's True
        # whenever fewer rows were scanned than the window held (hash-mod sampling OR time-slice
        # bounding), so the flag can never diverge from whether the reported counts are estimates.
        scanned = len(samples)
        return LogsQueryResponse(
            results={
                "patterns": [_serialize(p, total_count=total, scanned_count=scanned) for p in patterns],
                "scanned_count": scanned,
                "total_count": total,
                "sampled": scanned < total,
                "sample_coverage_pct": round(pool / total * 100, 2) if total else 100.0,
                "sparkline_buckets": [{"start": start.isoformat(), "end": end.isoformat()} for start, end in buckets],
                "source": "body_mining",
                "pattern_version": None,
                "fallback_reason": reason,
                "pattern_coverage_pct": None,
                "represented_count": None,
                "remainder_count": None,
            }
        )

    def _stored_where(self, version: int) -> ast.Expr:
        return parse_expr(
            "{where} AND pattern_version = {version} AND trim(pattern) != ''",
            placeholders={"where": self._where_with_timestamp(), "version": ast.Constant(value=version)},
        )

    def _calculate_stored_patterns(self, total: int, version: int, covered: int) -> LogsQueryResponse:
        head_limit = min(10000, max(1, _env("LOGS_PATTERNS_HEAD_LIMIT", 10000, int)))
        head = self._execute(
            parse_select(
                "SELECT topK({head_limit})(pattern) FROM logs WHERE {where}",
                placeholders={"head_limit": ast.Constant(value=head_limit), "where": self._stored_where(version)},
            )
        ).results[0][0]
        bounded_head = []
        head_bytes = 3
        for member in head:
            member_bytes = encoded_pattern_member_size(member)
            if head_bytes + member_bytes <= STORED_PATTERN_HEAD_MAX_BYTES:
                bounded_head.append(member)
                head_bytes += member_bytes
        buckets = _uniform_buckets(
            self.query_date_range.date_from(), self.query_date_range.date_to(), self._sparkline_bucket_count
        )
        placeholders: dict[str, ast.Expr] = {
            "where": self._stored_where(version),
            "head": ast.Constant(value=bounded_head),
            "services_limit": ast.Constant(value=_env("LOGS_PATTERNS_MAX_SERVICES", 4, int)),
            "head_limit": ast.Constant(value=head_limit),
        }
        bucket_sql = []
        for index, (start, end) in enumerate(buckets):
            placeholders[f"start_{index}"] = ast.Constant(value=start)
            placeholders[f"end_{index}"] = ast.Constant(value=end)
            bucket_sql.append(f"countIf(timestamp >= {{start_{index}}} AND timestamp < {{end_{index}}})")
        rows = self._execute(
            parse_select(
                "SELECT pattern, count(), min(timestamp), max(timestamp), "
                "sumMap([lower(severity_text)], [1]), "
                "groupUniqArrayArray({services_limit})([service_name]), "
                f"[{', '.join(bucket_sql)}] "
                "FROM logs WHERE {where} AND pattern IN {head} GROUP BY pattern "
                "ORDER BY count() DESC, pattern LIMIT {head_limit}",
                placeholders=placeholders,
            )
        ).results
        patterns = group_stored_patterns([_stamped_pattern(row, version) for row in rows], total_count=total)
        patterns = self._stored_examples(patterns, version)
        represented = sum(pattern.count for pattern in patterns)
        return LogsQueryResponse(
            results={
                "patterns": [_serialize(pattern, total_count=total, scanned_count=total) for pattern in patterns],
                "total_count": total,
                "scanned_count": total,
                "sampled": False,
                "sample_coverage_pct": 100.0,
                "sparkline_buckets": [{"start": start.isoformat(), "end": end.isoformat()} for start, end in buckets],
                "source": "stored_patterns",
                "pattern_version": version,
                "fallback_reason": None,
                "pattern_coverage_pct": round(covered / total * 100, 2),
                "represented_count": represented,
                "remainder_count": max(0, total - represented),
            }
        )

    def _stored_examples(self, patterns: list[MinedPattern], version: int) -> list[MinedPattern]:
        if not patterns:
            return []
        max_examples = _env("LOGS_PATTERNS_MAX_EXAMPLES", 10, int)
        if max_examples <= 0:
            return patterns
        member_groups = {
            member: group_id for group_id, pattern in enumerate(patterns, start=1) for member in pattern.match_patterns
        }
        # `LIMIT n BY` caps rows, not distinct bodies, and the table's sort order puts the rows of a
        # repeated line next to each other, so one body can fill a group's whole quota. Read a
        # bounded multiple of the quota and keep the distinct bodies here. Grouping on `body` in the
        # query would decompress it for every matching row instead of stopping at the rows read
        # first, which is the cost this query is shaped to avoid.
        fetch_per_group = max_examples * 4
        rows = self._execute(
            parse_select(
                "SELECT transform(pattern, {patterns}, {group_ids}, 0) AS pattern_group, "
                "substringUTF8(body, 1, 4096), severity_text, service_name, timestamp "
                "FROM logs WHERE {where} AND pattern IN {patterns} "
                "LIMIT {fetch_per_group} BY pattern_group LIMIT {limit}",
                placeholders={
                    "where": self._stored_where(version),
                    "patterns": ast.Constant(value=list(member_groups)),
                    "group_ids": ast.Constant(value=list(member_groups.values())),
                    "fetch_per_group": ast.Constant(value=fetch_per_group),
                    "limit": ast.Constant(value=len(patterns) * fetch_per_group),
                },
            )
        ).results
        examples: dict[int, list[LogSample]] = {}
        for row in rows:
            group = examples.setdefault(row[0], [])
            if len(group) >= max_examples or any(example.body == row[1] for example in group):
                continue
            group.append(
                LogSample(
                    body=row[1], severity_text=row[2], service_name=row[3], timestamp=row[4].replace(tzinfo=dt.UTC)
                )
            )
        return [
            replace(pattern, examples=examples.get(group_id, [])) for group_id, pattern in enumerate(patterns, start=1)
        ]

    def run(self, *args, **kwargs) -> LogsQueryResponse | CachedLogsQueryResponse:
        response = super().run(*args, **kwargs)
        assert isinstance(response, LogsQueryResponse | CachedLogsQueryResponse)
        return response

    def to_query(self) -> ast.SelectQuery:
        # Canonical (unsampled) form for the base runner's query contract; _calculate picks
        # the runtime divisor and slices.
        return self._sample_query(divisor=1, slices=None)

    def _execute(self, query: ast.SelectQuery | ast.SelectSetQuery):
        settings = self.settings.model_copy()
        if self._query_deadline is not None:
            remaining = int(self._query_deadline - monotonic())
            if remaining < 1:
                raise ClickHouseQueryTimeOut()
            settings.max_execution_time = remaining
        response = execute_hogql_query(
            query_type="LogsQuery",
            query=query,
            modifiers=self.modifiers,
            team=self.team,
            workload=Workload.LOGS,
            timings=self.timings,
            limit_context=self.limit_context,
            settings=settings,
        )
        if self._query_deadline is not None and monotonic() >= self._query_deadline:
            raise ClickHouseQueryTimeOut()
        return response

    def _count(self, slices: list[_TimeSlice] | None = None) -> int:
        response = self._execute(
            parse_select(
                "SELECT count() FROM logs WHERE {where}",
                placeholders={"where": self._where_with_timestamp(slices)},
            )
        )
        return int(response.results[0][0]) if response.results else 0

    def _where_with_timestamp(self, slices: list[_TimeSlice] | None = None) -> ast.Expr:
        # LogsFilterBuilder.where() filters at day-precision via time_bucket; add explicit
        # per-row timestamp bounds (half-open) so the sample matches the requested window.
        exprs: list[ast.Expr] = [
            self.where(),
            parse_expr(
                "timestamp >= {date_from} AND timestamp < {date_to}",
                placeholders={
                    "date_from": ast.Constant(value=self.query_date_range.date_from()),
                    "date_to": ast.Constant(value=self.query_date_range.date_to()),
                },
            ),
        ]
        if slices is not None:
            # Slice bounds are on `timestamp` (in the sort key), so ClickHouse prunes the
            # granules outside the slices instead of scanning the whole window.
            exprs.append(
                ast.Or(
                    exprs=[
                        parse_expr(
                            "timestamp >= {slice_from} AND timestamp < {slice_to}",
                            placeholders={
                                "slice_from": ast.Constant(value=slice_from),
                                "slice_to": ast.Constant(value=slice_to),
                            },
                        )
                        for slice_from, slice_to in slices
                    ]
                )
            )
        return ast.And(exprs=exprs)

    def _sample_query(self, divisor: int, slices: list[_TimeSlice] | None = None) -> ast.SelectQuery:
        # Deterministic even-random sampling: cityHash64(uuid) is uniform and fixed per row,
        # so `% divisor = 0` keeps ~1/divisor of rows spread evenly across the slices AND the
        # same rows on every run. divisor == 1 means no sampling, so we skip the predicate.
        where: ast.Expr = self._where_with_timestamp(slices)
        if divisor > 1:
            where = ast.And(
                exprs=[
                    where,
                    parse_expr(
                        "cityHash64(uuid) % {divisor} = 0",
                        placeholders={"divisor": ast.Constant(value=divisor)},
                    ),
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


def _time_slices(
    date_from: dt.datetime,
    date_to: dt.datetime,
    *,
    total: int,
    scan_budget: int,
    slice_count: int,
) -> list[_TimeSlice] | None:
    """Evenly spaced sub-windows covering ~scan_budget/total of [date_from, date_to).

    Returns None when the whole window fits the budget. The last slice is aligned to end at
    date_to so the freshest logs are always eligible for the sample.
    """
    if total <= scan_budget:
        return None
    window = date_to - date_from
    if window <= dt.timedelta(0):
        return None
    slice_count = max(1, slice_count)
    step = window / slice_count
    width = window * (scan_budget / total) / slice_count
    slices = []
    for i in range(slice_count):
        end = date_from + step * (i + 1)
        slices.append((end - width, end))
    return slices


def _uniform_buckets(date_from: dt.datetime, date_to: dt.datetime, count: int) -> list[_TimeSlice]:
    count = max(1, count)
    step = (date_to - date_from) / count
    return [(date_from + step * i, date_from + step * (i + 1)) for i in range(count)]


def _sample_divisor(total: int, sample_limit: int) -> int:
    # Round up so total / divisor <= sample_limit: the hash-modulo predicate alone bounds the
    # sample and LIMIT never truncates the subset in (biased) read order.
    if total <= sample_limit:
        return 1
    return ceil(total / sample_limit)


def _serialize(pattern: MinedPattern, *, total_count: int, scanned_count: int) -> dict:
    # Extrapolate sample counts to the full window so consumers don't have to; when the
    # window wasn't sampled the estimates are the exact counts.
    def estimate(sample_count: int) -> int:
        if scanned_count >= total_count:
            return sample_count
        return round(sample_count / scanned_count * total_count)

    return {
        "pattern": pattern.pattern,
        "count": pattern.count,
        "estimated_count": estimate(pattern.count),
        "volume_share_pct": pattern.volume_share_pct,
        "error_count": pattern.error_count,
        "estimated_error_count": estimate(pattern.error_count),
        "first_seen": pattern.first_seen.isoformat(),
        "last_seen": pattern.last_seen.isoformat(),
        "examples": [
            {
                "body": example.body,
                "severity_text": example.severity_text,
                "service_name": example.service_name,
                "timestamp": example.timestamp.isoformat(),
            }
            for example in pattern.examples
        ],
        "services": pattern.services,
        "sparkline": [estimate(c) for c in pattern.bucket_counts],
        # Raw sample counts: severity dominance is a proportion, which is scale-invariant,
        # so extrapolating the map would add payload without changing what it says.
        "severity_counts": pattern.severity_counts,
        "match_regex": pattern.match_regex,
        "match_literal": pattern.match_literal,
        "match_patterns": pattern.match_patterns,
        "pattern_version": pattern.pattern_version,
    }


def _stamped_pattern(row: list, version: int) -> MinedPattern:
    severities = dict(zip(row[4][0], row[4][1]))
    return MinedPattern(
        pattern=row[0],
        count=int(row[1]),
        volume_share_pct=0,
        error_count=sum(count for severity, count in severities.items() if severity in ERROR_SEVERITIES),
        first_seen=row[2].replace(tzinfo=dt.UTC),
        last_seen=row[3].replace(tzinfo=dt.UTC),
        examples=[],
        services=sorted(service for service in row[5] if service),
        bucket_counts=row[6],
        severity_counts=severities,
        match_regex=None,
        match_literal=None,
        match_patterns=[row[0]],
        pattern_version=version,
    )
