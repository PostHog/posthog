import datetime
from dataclasses import dataclass
from uuid import UUID

from django.db.models import QuerySet

import structlog

from posthog.schema import (
    CachedErrorTrackingIssueCorrelationQueryResponse,
    DateRange,
    ErrorTrackingIssueCorrelationQuery,
    ErrorTrackingIssueCorrelationQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner

from products.error_tracking.backend.api.issues import ErrorTrackingIssueSerializer
from products.error_tracking.backend.models import ErrorTrackingIssue

logger = structlog.get_logger(__name__)


@dataclass
class VolumeOptions:
    date_range: DateRange
    resolution: int


class ErrorTrackingIssueCorrelationQueryRunner(AnalyticsQueryRunner[ErrorTrackingIssueCorrelationQueryResponse]):
    query: ErrorTrackingIssueCorrelationQuery
    cached_response: CachedErrorTrackingIssueCorrelationQueryResponse
    paginator: HogQLHasMorePaginator
    date_from: datetime.datetime
    date_to: datetime.datetime

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=50,
            offset=0,
        )

    def _calculate(self):
        with self.timings.measure("error_tracking_query_hogql_execute"):
            query_result = self.paginator.execute_hogql_query(
                query=self.to_query(),
                team=self.team,
                query_type="ErrorTrackingIssueCorrelationQuery",
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        results = self.results(query_result.results)

        return ErrorTrackingIssueCorrelationQueryResponse(
            columns=[
                "id",
                "status",
                "name",
                "description",
                "first_seen",
                "assignee",
                "external_issues",
                "last_seen",
                "library",
                "odds_ratio",
                "population",
                "event",
            ],
            results=results,
            timings=query_result.timings,
            hogql=query_result.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )

    def results(
        self, rows: list[tuple[str, list[UUID], list[str], list[str], list[int], list[int], list[int], list[int]]]
    ) -> list[dict]:
        issue_ids: set[str] = set()
        correlations: dict[str, dict[str, dict]] = {}

        for row in rows:
            (
                event,
                issue_uuids,
                issue_last_seen_timestamps,
                issue_libraries,
                issue_both,
                issue_success_only,
                issue_exception_only,
                issue_neither,
            ) = row
            issues = list(
                zip(
                    issue_uuids,
                    issue_last_seen_timestamps,
                    issue_libraries,
                    issue_both,
                    issue_success_only,
                    issue_exception_only,
                    issue_neither,
                )
            )

            for issue in issues:
                uuid, last_seen, library, both, success_only, exception_only, neither = issue

                if not (both > 0 and success_only > 0 and exception_only > 0 and neither > 0):
                    continue

                issue_ids.add(str(uuid))
                odds_ratio = (both * neither) / (success_only * exception_only)

                issue_correlation = correlations.setdefault(str(uuid), {})
                issue_correlation[event] = {
                    "last_seen": last_seen,
                    "library": library,
                    "odds_ratio": odds_ratio,
                    "population": {
                        "both": both,
                        "success_only": success_only,
                        "exception_only": exception_only,
                        "neither": neither,
                    },
                }

        issues = self.fetch_issues(list(issue_ids))

        results = []
        for issue in issues:
            issue_correlations = correlations.get(issue["id"], {})
            for event, correlation in issue_correlations.items():
                results.append({**issue, **correlation, "event": event})

        return sorted(results, key=lambda r: r["odds_ratio"], reverse=True)

    def fetch_issues(self, ids: list[str]):
        queryset: QuerySet[ErrorTrackingIssue] = (
            ErrorTrackingIssue.objects.with_first_seen()
            .select_related("assignment")
            .filter(id__in=ids, team=self.team, status=ErrorTrackingIssue.Status.ACTIVE)
        )
        return ErrorTrackingIssueSerializer(queryset, many=True).data

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return parse_select(
            """WITH issues AS (
    SELECT
        groupArray(issue_id) as ids,
        groupArray(last_seen) as last_seen_timestamps,
        groupArray(library) as libraries
    FROM (
        SELECT issue_id, max(timestamp) as last_seen, argMax(properties.$lib, timestamp) as library
        FROM events
        WHERE timestamp > now() - INTERVAL 6 HOUR AND notEmpty(events.$session_id) AND issue_id IS NOT NULL AND event = '$exception'
        GROUP BY issue_id
    )
)
SELECT
    event,
    (SELECT ids FROM issues) as issue_ids,
    (SELECT last_seen_timestamps FROM issues) as issue_last_seen_timestamps,
    (SELECT libraries FROM issues) as issue_libraries,
    sumForEach(both) as both,
    sumForEach(success_only) as success_only,
    sumForEach(exception_only) as exception_only,
    sumForEach(neither) as neither
FROM (
    SELECT
        event,
        $session_id,
        arrayMap(x -> if(x IS NOT NULL AND earliest_success_event IS NOT NULL AND x < earliest_success_event, 1, 0), earliest_exceptions) AS both,
        arrayMap(x -> if(x IS NULL AND earliest_success_event IS NOT NULL, 1, 0), earliest_exceptions) AS success_only,
        arrayMap(x -> if(x IS NOT NULL AND earliest_success_event IS NULL, 1, 0), earliest_exceptions) AS exception_only,
        arrayMap(x -> if(x IS NULL AND earliest_success_event IS NULL, 1, 0), earliest_exceptions) AS neither
    FROM (
        SELECT
            $session_id,
            {events} as events,
            minForEach(arrayMap(x -> (if(event = x, toNullable(timestamp), NULL)), {events})) as earliest_success_events,
            minForEach(arrayMap(x -> (if(x = issue_id, toNullable(timestamp), NULL)), (SELECT ids FROM issues))) as earliest_exceptions
        FROM events
        WHERE
            (timestamp > now() - INTERVAL 6 HOUR) AND
            notEmpty(events.$session_id)
        GROUP BY $session_id
    )
    ARRAY JOIN
        events AS event,
        earliest_success_events AS earliest_success_event
)
GROUP BY event""",
            placeholders={
                "events": ast.Constant(value=self.query.events),
            },
        )
