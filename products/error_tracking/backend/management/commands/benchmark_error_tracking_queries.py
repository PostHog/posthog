"""Benchmark error tracking query v1 vs v3 across sorting, filtering, and date range combinations.

Runs all combinations of:
- Sorting: users, sessions, occurrences, first_seen, last_seen (ASC and DESC)
- Filtering: none, event property (ip is set), issue property (name icontains "error")
- Date range: 1h, 24h, 7d, 14d, 30d

Queries run concurrently via a thread pool (--concurrency controls parallelism).
Outputs a CSV with per-team and aggregate (average) timings.

Usage:
    # Single team, 1 iteration
    python manage.py benchmark_error_tracking_queries --team-ids 2

    # Multiple teams, 3 iterations, 8 concurrent queries
    python manage.py benchmark_error_tracking_queries --team-ids 2 5 10 --iterations 3 --concurrency 8
"""

from __future__ import annotations

import io
import csv
import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from django.core.management.base import BaseCommand

import structlog

from posthog.schema import (
    DateRange,
    ErrorTrackingIssueFilter,
    ErrorTrackingOrderBy,
    ErrorTrackingQuery,
    EventPropertyFilter,
    FilterLogicalOperator,
    OrderDirection2,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    PropertyOperator,
)

from posthog.models import Team

from products.error_tracking.backend.hogql_queries.error_tracking_query_runner import ErrorTrackingQueryRunner

logger = structlog.get_logger(__name__)

SORT_FIELDS = [
    ErrorTrackingOrderBy.USERS,
    ErrorTrackingOrderBy.SESSIONS,
    ErrorTrackingOrderBy.OCCURRENCES,
    ErrorTrackingOrderBy.FIRST_SEEN,
    ErrorTrackingOrderBy.LAST_SEEN,
]

SORT_DIRECTIONS = [OrderDirection2.ASC, OrderDirection2.DESC]

DATE_RANGES: list[tuple[str, str]] = [
    ("1h", "-1h"),
    ("24h", "-24h"),
    ("7d", "-7d"),
    ("14d", "-14d"),
    ("30d", "-30d"),
]

FILTER_NONE = "none"
FILTER_EVENT_PROPERTY = "event_prop_ip_is_set"
FILTER_ISSUE_PROPERTY = "issue_name_contains_error"


@dataclass
class QueryResult:
    date_range: str
    filter_name: str
    order_by: str
    direction: str
    team_id: int
    version: str  # "v1" or "v3"
    elapsed: float
    total_users: float
    total_sessions: float
    total_occurrences: float


@dataclass
class BenchmarkCollector:
    _lock: threading.Lock = field(default_factory=threading.Lock)
    results: list[QueryResult] = field(default_factory=list)

    def add(self, result: QueryResult) -> None:
        with self._lock:
            self.results.append(result)


def _build_filter_group(filter_name: str) -> PropertyGroupFilter | None:
    if filter_name == FILTER_NONE:
        return None
    if filter_name == FILTER_EVENT_PROPERTY:
        return PropertyGroupFilter(
            type=FilterLogicalOperator.AND_,
            values=[
                PropertyGroupFilterValue(
                    type=FilterLogicalOperator.AND_,
                    values=[
                        EventPropertyFilter(
                            key="$ip",
                            operator=PropertyOperator.IS_SET,
                            type="event",
                        ),
                    ],
                ),
            ],
        )
    if filter_name == FILTER_ISSUE_PROPERTY:
        return PropertyGroupFilter(
            type=FilterLogicalOperator.AND_,
            values=[
                PropertyGroupFilterValue(
                    type=FilterLogicalOperator.AND_,
                    values=[
                        ErrorTrackingIssueFilter(
                            key="name",
                            operator=PropertyOperator.ICONTAINS,
                            value="error",
                        ),
                    ],
                ),
            ],
        )
    return None


@dataclass
class RunResult:
    elapsed: float
    total_users: float
    total_sessions: float
    total_occurrences: float


def _run_query(team: Team, query: ErrorTrackingQuery) -> RunResult:
    runner = ErrorTrackingQueryRunner(team=team, query=query)
    start = time.monotonic()
    response = runner.calculate()
    elapsed = time.monotonic() - start

    total_users = 0.0
    total_sessions = 0.0
    total_occurrences = 0.0
    for issue in response.results:
        if issue.aggregations:
            total_users += issue.aggregations.users
            total_sessions += issue.aggregations.sessions
            total_occurrences += issue.aggregations.occurrences

    return RunResult(
        elapsed=elapsed,
        total_users=total_users,
        total_sessions=total_sessions,
        total_occurrences=total_occurrences,
    )


def _build_query(
    *,
    date_from: str,
    order_by: ErrorTrackingOrderBy,
    direction: OrderDirection2,
    filter_group: PropertyGroupFilter | None,
    use_v3: bool,
) -> ErrorTrackingQuery:
    return ErrorTrackingQuery(
        kind="ErrorTrackingQuery",
        dateRange=DateRange(date_from=date_from),
        orderBy=order_by,
        orderDirection=direction,
        filterGroup=filter_group,
        status="all",
        volumeResolution=1,
        withAggregations=True,
        withFirstEvent=False,
        withLastEvent=False,
        limit=50,
        useQueryV3=use_v3 or None,
    )


class Command(BaseCommand):
    help = "Benchmark error tracking query v1 vs v3 across all sorting/filtering/date range combinations."

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-ids",
            type=str,
            required=True,
            help="Comma-separated team IDs to benchmark against (e.g. 2,5,10).",
        )
        parser.add_argument(
            "--iterations",
            type=int,
            default=1,
            help="Number of iterations to run (results are averaged). Default: 1.",
        )
        parser.add_argument(
            "--concurrency",
            type=int,
            default=4,
            help="Max concurrent queries against ClickHouse. Default: 4.",
        )

    def handle(self, *, team_ids: str, iterations: int, concurrency: int, **options):
        logger.setLevel(logging.INFO)

        parsed_team_ids = [int(t.strip()) for t in team_ids.split(",")]

        teams_by_id: dict[int, Team] = {}
        for tid in parsed_team_ids:
            try:
                teams_by_id[tid] = Team.objects.get(id=tid)
            except Team.DoesNotExist:
                logger.warning("team_not_found", team_id=tid)
                return

        filter_names = [FILTER_NONE, FILTER_EVENT_PROPERTY, FILTER_ISSUE_PROPERTY]

        # Build all tasks upfront: (iteration, date_label, date_from, filter_name, order_by, direction, team_id, version)
        tasks: list[tuple[int, str, str, str, ErrorTrackingOrderBy, OrderDirection2, int, str]] = []
        for iteration in range(iterations):
            for date_label, date_from in DATE_RANGES:
                for filter_name in filter_names:
                    for order_by in SORT_FIELDS:
                        for direction in SORT_DIRECTIONS:
                            for tid in parsed_team_ids:
                                tasks.append(
                                    (iteration, date_label, date_from, filter_name, order_by, direction, tid, "v1")
                                )
                                tasks.append(
                                    (iteration, date_label, date_from, filter_name, order_by, direction, tid, "v3")
                                )

        total_queries = len(tasks)
        logger.info(
            "benchmark_starting",
            teams=parsed_team_ids,
            iterations=iterations,
            total_queries=total_queries,
            concurrency=concurrency,
        )

        collector = BenchmarkCollector()
        completed = 0
        completed_lock = threading.Lock()

        def run_task(task: tuple[int, str, str, str, ErrorTrackingOrderBy, OrderDirection2, int, str]) -> None:
            nonlocal completed
            _iteration, date_label, date_from, filter_name, order_by, direction, tid, version = task
            team = teams_by_id[tid]
            filter_group = _build_filter_group(filter_name)
            query = _build_query(
                date_from=date_from,
                order_by=order_by,
                direction=direction,
                filter_group=filter_group,
                use_v3=(version == "v3"),
            )

            try:
                result = _run_query(team, query)
            except Exception:
                logger.exception(
                    "query_failed",
                    version=version,
                    team_id=tid,
                    date_range=date_label,
                    filter=filter_name,
                    order_by=order_by.value,
                    direction=direction.value,
                )
                result = RunResult(
                    elapsed=float("nan"),
                    total_users=float("nan"),
                    total_sessions=float("nan"),
                    total_occurrences=float("nan"),
                )

            collector.add(
                QueryResult(
                    date_range=date_label,
                    filter_name=filter_name,
                    order_by=order_by.value,
                    direction=direction.value,
                    team_id=tid,
                    version=version,
                    elapsed=result.elapsed,
                    total_users=result.total_users,
                    total_sessions=result.total_sessions,
                    total_occurrences=result.total_occurrences,
                )
            )

            with completed_lock:
                completed += 1
                if completed % 20 == 0 or completed == total_queries:
                    logger.info("benchmark_progress", completed=completed, total=total_queries)

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [pool.submit(run_task, task) for task in tasks]
            for future in as_completed(futures):
                future.result()  # re-raise any unexpected errors

        csv_output = _format_csv(collector, parsed_team_ids, iterations)
        self.stdout.write(csv_output)


@dataclass
class _AveragedResult:
    elapsed: float
    total_users: float
    total_sessions: float
    total_occurrences: float


def _format_csv(collector: BenchmarkCollector, team_ids: list[int], iterations: int) -> str:
    output = io.StringIO()
    writer = csv.writer(output)

    # Group results by (date_range, filter_name, order_by, direction, team_id, version) and average across iterations
    elapsed_totals: dict[tuple[str, str, str, str, int, str], list[float]] = {}
    for r in collector.results:
        key = (r.date_range, r.filter_name, r.order_by, r.direction, r.team_id, r.version)
        if key not in elapsed_totals:
            elapsed_totals[key] = [0.0, 0.0, 0.0, 0.0]
        elapsed_totals[key][0] += r.elapsed
        elapsed_totals[key][1] += r.total_users
        elapsed_totals[key][2] += r.total_sessions
        elapsed_totals[key][3] += r.total_occurrences

    averaged: dict[tuple[str, str, str, str, int, str], _AveragedResult] = {}
    for k, v in elapsed_totals.items():
        averaged[k] = _AveragedResult(
            elapsed=v[0] / iterations,
            total_users=v[1] / iterations,
            total_sessions=v[2] / iterations,
            total_occurrences=v[3] / iterations,
        )

    writer.writerow(
        [
            "date_range",
            "filter",
            "order_by",
            "direction",
            "team_id",
            "v1_avg_s",
            "v3_avg_s",
            "v1_users",
            "v1_sessions",
            "v1_occurrences",
            "v3_users",
            "v3_sessions",
            "v3_occurrences",
        ]
    )

    nan = float("nan")
    empty = _AveragedResult(elapsed=nan, total_users=nan, total_sessions=nan, total_occurrences=nan)

    filter_names = [FILTER_NONE, FILTER_EVENT_PROPERTY, FILTER_ISSUE_PROPERTY]
    for date_label, _ in DATE_RANGES:
        for filter_name in filter_names:
            for order_by in SORT_FIELDS:
                for direction in SORT_DIRECTIONS:
                    v1_results: list[_AveragedResult] = []
                    v3_results: list[_AveragedResult] = []

                    for tid in team_ids:
                        v1 = averaged.get((date_label, filter_name, order_by.value, direction.value, tid, "v1"), empty)
                        v3 = averaged.get((date_label, filter_name, order_by.value, direction.value, tid, "v3"), empty)
                        writer.writerow(
                            [
                                date_label,
                                filter_name,
                                order_by.value,
                                direction.value,
                                str(tid),
                                f"{v1.elapsed:.3f}",
                                f"{v3.elapsed:.3f}",
                                f"{v1.total_users:.0f}",
                                f"{v1.total_sessions:.0f}",
                                f"{v1.total_occurrences:.0f}",
                                f"{v3.total_users:.0f}",
                                f"{v3.total_sessions:.0f}",
                                f"{v3.total_occurrences:.0f}",
                            ]
                        )
                        v1_results.append(v1)
                        v3_results.append(v3)

                    if len(team_ids) > 1:
                        n = len(team_ids)
                        writer.writerow(
                            [
                                date_label,
                                filter_name,
                                order_by.value,
                                direction.value,
                                "AVERAGE",
                                f"{sum(r.elapsed for r in v1_results) / n:.3f}",
                                f"{sum(r.elapsed for r in v3_results) / n:.3f}",
                                f"{sum(r.total_users for r in v1_results) / n:.0f}",
                                f"{sum(r.total_sessions for r in v1_results) / n:.0f}",
                                f"{sum(r.total_occurrences for r in v1_results) / n:.0f}",
                                f"{sum(r.total_users for r in v3_results) / n:.0f}",
                                f"{sum(r.total_sessions for r in v3_results) / n:.0f}",
                                f"{sum(r.total_occurrences for r in v3_results) / n:.0f}",
                            ]
                        )

    return output.getvalue()
