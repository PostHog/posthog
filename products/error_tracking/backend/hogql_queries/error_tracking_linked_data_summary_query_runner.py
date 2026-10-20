import structlog

from posthog.schema import (
    CachedErrorTrackingLinkedDataSummaryQueryResponse,
    ErrorTrackingLinkedDataCount,
    ErrorTrackingLinkedDataKind,
    ErrorTrackingLinkedDataSummary,
    ErrorTrackingLinkedDataSummaryQuery,
    ErrorTrackingLinkedDataSummaryQueryResponse,
    EventsQuery,
)

from posthog.hogql import ast

from posthog.hogql_queries.events_query_runner import EventsQueryRunner
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.models import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.error_tracking.backend.hogql_queries.access import ErrorTrackingQueryRunnerAccessMixin
from products.error_tracking.backend.hogql_queries.error_tracking_query_runner_utils import validate_uuid_param
from products.error_tracking.backend.hogql_queries.linked_data import (
    exception_links_from_scan_row,
    log_linked_uuids,
    recording_condition,
    scan_query,
)
from products.logs.backend.facade.linked_logs import LinkedLogsLookupError

logger = structlog.get_logger(__name__)

# Logs counts check at most this many of the most recent exceptions. Past it, the count is a lower bound.
LOGS_COUNT_SCAN_BUDGET = 2_000


class ErrorTrackingLinkedDataSummaryQueryRunner(
    ErrorTrackingQueryRunnerAccessMixin, AnalyticsQueryRunner[ErrorTrackingLinkedDataSummaryQueryResponse]
):
    query: ErrorTrackingLinkedDataSummaryQuery
    cached_response: CachedErrorTrackingLinkedDataSummaryQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.query.issueId = validate_uuid_param(self.query.issueId, "issueId")
        # Internal callers skip access validation, which applies to user requests only.
        self._can_read_logs = True

    def validate_query_runner_access(self, user: User) -> bool:
        super().validate_query_runner_access(user)
        # Someone who can't see logs still gets the recording count, with no logs count.
        self._can_read_logs = UserAccessControl(user=user, team=self.team).check_access_level_for_resource(
            "logs", "viewer"
        )
        return True

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return self._events_runner(self._recording_count_query()).to_query()

    def _events_runner(self, query: EventsQuery) -> EventsQueryRunner:
        return EventsQueryRunner(
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
            user=self.user,
        )

    def _recording_count_query(self) -> EventsQuery:
        source = self.query.source
        return source.model_copy(
            update={
                "select": ["count()"],
                "where": [*(source.where or []), recording_condition(self.query.issueId, source, self.team)],
                "orderBy": None,
                "limit": None,
                "offset": None,
            }
        )

    def _calculate(self) -> ErrorTrackingLinkedDataSummaryQueryResponse:
        recording = None
        if ErrorTrackingLinkedDataKind.RECORDING in self.query.linkedData:
            with self.timings.measure("recording_count"):
                response = self._events_runner(self._recording_count_query()).calculate()
            recording = ErrorTrackingLinkedDataCount(count=int(response.results[0][0]), complete=True)

        logs = (
            self._logs_count()
            if ErrorTrackingLinkedDataKind.LOGS in self.query.linkedData and self._can_read_logs
            else None
        )

        return ErrorTrackingLinkedDataSummaryQueryResponse(
            results=ErrorTrackingLinkedDataSummary(logs=logs, recording=recording),
            timings=self.timings.to_list(),
            modifiers=self.modifiers,
        )

    def _logs_count(self) -> ErrorTrackingLinkedDataCount | None:
        source = self.query.source
        with self.timings.measure("logs_count_scan"):
            scan = self._events_runner(
                scan_query(source, before=source.before, limit=LOGS_COUNT_SCAN_BUDGET)
            ).calculate()
        exceptions = [exception_links_from_scan_row(row) for row in scan.results]
        try:
            with self.timings.measure("linked_logs"):
                linked = log_linked_uuids(self.team, exceptions)
        except LinkedLogsLookupError:
            logger.warning("error_tracking_linked_logs_count_failed", team_id=self.team.pk, exc_info=True)
            return None
        return ErrorTrackingLinkedDataCount(count=len(linked), complete=not scan.hasMore)
