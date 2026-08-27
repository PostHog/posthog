import re
import datetime
from collections.abc import Callable
from zoneinfo import ZoneInfo

from posthog.schema import (
    CachedErrorTrackingReleasesQueryResponse,
    ErrorTrackingIssueRelease,
    ErrorTrackingReleaseSeries,
    ErrorTrackingReleasesOrderBy,
    ErrorTrackingReleasesQuery,
    ErrorTrackingReleasesQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.utils import relative_date_parse

from products.error_tracking.backend.hogql_queries.access import ErrorTrackingQueryRunnerAccessMixin
from products.error_tracking.backend.hogql_queries.error_tracking_query_runner_utils import validate_uuid_param

DEFAULT_RESOLUTION = 40
# Caps the `counts` lists in the response, whatever date range the request spans.
MAX_RESOLUTION = 1000
DEFAULT_MAX_RELEASES = 5
# Matches the stacked chart's request. With MAX_RESOLUTION, it bounds a response at a million counts.
MAX_RELEASES = 1000
MIN_BUCKET_SECONDS = 60
# Rows the query hands back for folding. Past this, the lowest-volume releases are dropped, so the
# fold undercounts `other` but every returned series stays exact. A capped response says so, so the
# panel can show its release count as a lower bound.
MAX_QUERY_RELEASES = 5000

# Bounded digit runs keep `int()` from raising on absurdly long client-set version strings. Only the
# numeric prefix counts, so a hash or a prerelease tag still yields a usable tiebreaker.
NUMERIC_VERSION = re.compile(r"^\d{1,18}(\.\d{1,18})*")

ReleaseKey = tuple[str | None, str | None, str | None]


class _Accumulator:
    """Per-release occurrence counts while the query rows are folded into the response."""

    def __init__(self, key: ReleaseKey) -> None:
        self.key = key
        # Sparse, so the thousands of releases that fold into `other` never allocate a full bucket grid.
        self.counts: dict[int, int] = {}
        self.total = 0
        self.first_index = -1
        self.last_index = -1

    def add(self, index: int, count: int) -> None:
        self.counts[index] = self.counts.get(index, 0) + count
        self.total += count
        if self.first_index == -1 or index < self.first_index:
            self.first_index = index
        if index > self.last_index:
            self.last_index = index


class ErrorTrackingReleasesQueryRunner(
    ErrorTrackingQueryRunnerAccessMixin, AnalyticsQueryRunner[ErrorTrackingReleasesQueryResponse]
):
    query: ErrorTrackingReleasesQuery
    cached_response: CachedErrorTrackingReleasesQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.query.issueId = validate_uuid_param(self.query.issueId, "issueId")
        self.date_from = self.parse_relative_date_from(self.query.dateRange.date_from if self.query.dateRange else None)
        self.date_to = self.parse_relative_date_to(self.query.dateRange.date_to if self.query.dateRange else None)
        resolution = min(MAX_RESOLUTION, max(1, self.query.resolution or DEFAULT_RESOLUTION))
        total_seconds = max(1, int((self.date_to - self.date_from).total_seconds()))
        self.bucket_seconds = max(MIN_BUCKET_SECONDS, -(-total_seconds // resolution))
        aligned_from = int(self.date_from.timestamp()) // self.bucket_seconds * self.bucket_seconds
        self.bucket_starts = list(range(aligned_from, int(self.date_to.timestamp()), self.bucket_seconds))
        if not self.bucket_starts:
            self.bucket_starts = [aligned_from]

    @classmethod
    def parse_relative_date_from(cls, date: str | None) -> datetime.datetime:
        if date == "all" or date is None:
            return datetime.datetime.now(tz=ZoneInfo("UTC")) - datetime.timedelta(days=7)
        return relative_date_parse(date, now=datetime.datetime.now(tz=ZoneInfo("UTC")), timezone_info=ZoneInfo("UTC"))

    @classmethod
    def parse_relative_date_to(cls, date: str | None) -> datetime.datetime:
        if not date:
            return datetime.datetime.now(tz=ZoneInfo("UTC"))
        if date == "all":
            raise ValueError("Invalid date range")
        return relative_date_parse(date, ZoneInfo("UTC"), increase=True)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return parse_select(
            """
            SELECT
                namespace,
                version,
                build,
                groupArray(tuple(bucket, occurrences)) AS series,
                sum(occurrences) AS total
            FROM (
                SELECT
                    toUnixTimestamp(toStartOfInterval(timestamp, toIntervalSecond({bucket_seconds}))) AS bucket,
                    properties.$app_namespace AS namespace,
                    properties.$app_version AS version,
                    toString(properties.$app_build) AS build,
                    count() AS occurrences
                FROM events
                WHERE {where}
                GROUP BY bucket, namespace, version, build
            )
            GROUP BY namespace, version, build
            ORDER BY total DESC
            LIMIT {limit}
            """,
            placeholders={
                "bucket_seconds": ast.Constant(value=self.bucket_seconds),
                "where": self.events_where(),
                "limit": ast.Constant(value=MAX_QUERY_RELEASES),
            },
        )

    def events_where(self) -> ast.Expr:
        conditions: list[ast.Expr] = [
            ast.CompareOperation(
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=self.date_from),
                op=ast.CompareOperationOp.GtEq,
            ),
            ast.CompareOperation(
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=self.date_to),
                op=ast.CompareOperationOp.LtEq,
            ),
            ast.CompareOperation(
                left=ast.Field(chain=["event"]), right=ast.Constant(value="$exception"), op=ast.CompareOperationOp.Eq
            ),
            # Resolve the issue's fingerprints once, inside ClickHouse, instead of joining the
            # fingerprint state onto every event row. Merged issues can own hundreds of fingerprints.
            ast.CompareOperation(
                left=ast.Field(chain=["properties", "$exception_fingerprint"]),
                op=ast.CompareOperationOp.In,
                right=self.issue_fingerprints_query(),
            ),
        ]

        if self.query.filterTestAccounts:
            for prop in self.team.test_account_filters or []:
                conditions.append(property_to_expr(prop, self.team))

        if self.query.filterGroup:
            conditions.append(property_to_expr(self.query.filterGroup, self.team))

        return ast.And(exprs=conditions)

    def issue_fingerprints_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        # The tuple wrap keeps `argMax` from skipping a NULL issue_id at the latest version, so a
        # fingerprint unassigned after a split does not resolve to its previous issue.
        latest_state = parse_select(
            """
            SELECT
                fingerprint,
                tupleElement(argMax(tuple(issue_id), version), 1) AS issue_id,
                argMax(is_deleted, version) AS is_deleted
            FROM raw_error_tracking_fingerprint_issue_state
            GROUP BY fingerprint
            """
        )
        # Aggregate in the table's (team_id, fingerprint) sort order so the per-team latest-state
        # GROUP BY streams instead of building a full-team hash table, which has no disk fallback and
        # can hit MEMORY_LIMIT_EXCEEDED. Matches the shared issue-state helper on the same table.
        assert isinstance(latest_state, ast.SelectQuery)
        latest_state.settings = HogQLQuerySettings(optimize_aggregation_in_order=True)
        return parse_select(
            """
            SELECT fingerprint
            FROM {latest_state}
            WHERE issue_id = {issue_id} AND is_deleted = 0
            """,
            placeholders={
                "latest_state": latest_state,
                "issue_id": ast.Constant(value=self.query.issueId),
            },
        )

    def _calculate(self) -> ErrorTrackingReleasesQueryResponse:
        with self.timings.measure("error_tracking_releases_hogql_execute"):
            query_result = execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                user=self.user,
                query_type="ErrorTrackingReleasesQuery",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        response = self.fold(query_result.results)
        response.timings = query_result.timings
        response.hogql = query_result.hogql
        response.modifiers = self.modifiers
        return response

    def fold(self, rows: list) -> ErrorTrackingReleasesQueryResponse:
        bucket_count = len(self.bucket_starts)
        aligned_from = self.bucket_starts[0]
        selected_namespace = self.query.appNamespace or None
        releases: dict[ReleaseKey, _Accumulator] = {}
        unattributed: _Accumulator | None = None
        namespaces: set[str] = set()

        for namespace, version, build, series, _total in rows:
            # The WHERE bounds rows to [date_from, date_to] and the grid starts at or before date_from, so
            # only a bucket that starts exactly at an aligned date_to falls outside the grid. That instant
            # folds into the last bucket, which keeps the inclusive range the events list uses.
            in_range = [
                (max(0, min((int(bucket) - aligned_from) // self.bucket_seconds, bucket_count - 1)), int(count))
                for bucket, count in series
            ]
            if namespace:
                namespaces.add(namespace)
            if selected_namespace is not None and namespace != selected_namespace:
                continue
            if not namespace and not version:
                unattributed = unattributed or _Accumulator((None, None, None))
                target = unattributed
            else:
                key: ReleaseKey = (namespace, version, build)
                target = releases.setdefault(key, _Accumulator(key))
            for index, count in in_range:
                target.add(index, count)

        ordered = sorted(releases.values(), key=self.sort_key(), reverse=True)
        requested = self.query.maxReleases if self.query.maxReleases is not None else DEFAULT_MAX_RELEASES
        max_releases = min(MAX_RELEASES, max(0, requested))
        visible, hidden = ordered[:max_releases], ordered[max_releases:]

        other: _Accumulator | None = None
        if hidden:
            other = _Accumulator((None, None, None))
            for release in hidden:
                for index, count in release.counts.items():
                    other.add(index, count)

        total = sum(release.total for release in ordered) + (unattributed.total if unattributed else 0)
        return ErrorTrackingReleasesQueryResponse(
            date_from=self.date_from.isoformat(),
            date_to=self.date_to.isoformat(),
            buckets=[self.bucket_iso(index) for index in range(bucket_count)],
            bucket_seconds=self.bucket_seconds,
            results=[
                ErrorTrackingIssueRelease(
                    namespace=release.key[0],
                    version=release.key[1],
                    build=release.key[2],
                    **self.series(release).model_dump(),
                )
                for release in visible
            ],
            other=self.series(other) if other else None,
            other_release_count=len(hidden),
            unattributed=self.series(unattributed) if unattributed else None,
            release_count=len(ordered),
            release_count_truncated=len(rows) >= MAX_QUERY_RELEASES,
            namespaces=sorted(namespaces),
            total=total,
        )

    def sort_key(self) -> Callable[[_Accumulator], tuple]:
        order_by = self.query.orderBy or ErrorTrackingReleasesOrderBy.LATEST
        if order_by == ErrorTrackingReleasesOrderBy.OCCURRENCES:
            return lambda release: (release.total, release.first_index)
        # When a release first appeared in the range is the only signal that works for every version
        # format (semver, commit hashes, dates). Version numbers break ties, which are common because
        # releases active before the range all start in the first bucket. Unversioned releases sort last.
        return lambda release: (
            release.key[1] is not None,
            release.first_index,
            version_tuple(release.key[1]),
            version_tuple(release.key[2]),
            release.total,
        )

    def bucket_iso(self, index: int) -> str:
        return datetime.datetime.fromtimestamp(self.bucket_starts[index], tz=ZoneInfo("UTC")).isoformat()

    def series(self, release: _Accumulator) -> ErrorTrackingReleaseSeries:
        return ErrorTrackingReleaseSeries(
            counts=[release.counts.get(index, 0) for index in range(len(self.bucket_starts))],
            total=release.total,
            first_seen=self.bucket_iso(release.first_index) if release.first_index >= 0 else None,
            last_seen=self.bucket_iso(release.last_index) if release.last_index >= 0 else None,
        )


def version_tuple(value: str | None) -> tuple[int, ...]:
    match = NUMERIC_VERSION.match(value or "")
    return tuple(int(part) for part in match.group(0).split(".")) if match else ()
