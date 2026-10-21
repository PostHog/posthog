from posthog.schema import (
    CachedErrorTrackingIssueEventsQueryResponse,
    ErrorTrackingIssueEventsQuery,
    ErrorTrackingIssueEventsQueryResponse,
    ErrorTrackingLinkedDataKind,
    EventsQuery,
    EventsQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.errors import QueryError

from posthog.hogql_queries.events_query_runner import EventsQueryRunner
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.models import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.error_tracking.backend.hogql_queries.access import ErrorTrackingQueryRunnerAccessMixin
from products.error_tracking.backend.hogql_queries.error_tracking_query_runner_utils import validate_uuid_param
from products.error_tracking.backend.hogql_queries.linked_data import (
    SCAN_BATCH_SIZE,
    ExceptionLinks,
    exception_links_from_scan_row,
    exception_links_from_star,
    log_linked_uuids,
    recording_condition,
    rows_by_uuid_query,
    scan_query,
)
from products.logs.backend.facade.linked_logs import LinkedLogsLookupError

DEFAULT_PAGE_SIZE = 100
# A logs-filtered page checks at most this many exceptions. A page that runs out returns what it
# found and a cursor, so that loading more continues the scan from there.
PAGE_SCAN_BUDGET = 2_000


class ErrorTrackingIssueEventsQueryRunner(
    ErrorTrackingQueryRunnerAccessMixin, AnalyticsQueryRunner[ErrorTrackingIssueEventsQueryResponse]
):
    query: ErrorTrackingIssueEventsQuery
    cached_response: CachedErrorTrackingIssueEventsQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.query.issueId = validate_uuid_param(self.query.issueId, "issueId")
        if "*" not in self.query.source.select:
            raise QueryError("The source query must select `*`")

    @property
    def _required(self) -> list[ErrorTrackingLinkedDataKind]:
        return self.query.requiredLinkedData or []

    def validate_query_runner_access(self, user: User) -> bool:
        super().validate_query_runner_access(user)
        if ErrorTrackingLinkedDataKind.LOGS in self._required:
            UserAccessControl(user=user, team=self.team).assert_access_level_for_resource("logs", "viewer")
        return True

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return self._events_runner(self._source()).to_query()

    def _source(self) -> EventsQuery:
        source = self.query.source.model_copy(deep=True)
        if ErrorTrackingLinkedDataKind.RECORDING in self._required:
            source.where = [*(source.where or []), recording_condition(self.query.issueId, source, self.team)]
        return source

    def _events_runner(self, query: EventsQuery) -> EventsQueryRunner:
        return EventsQueryRunner(
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
            user=self.user,
        )

    def _calculate(self) -> ErrorTrackingIssueEventsQueryResponse:
        source = self._source()
        if ErrorTrackingLinkedDataKind.LOGS in self._required:
            return self._scan_for_linked_logs(source)

        response = self._events_runner(source).calculate()
        return self._response(
            source,
            response,
            has_more=bool(response.hasMore),
            next_cursor=self._last_row_cursor(source, response),
        )

    def _scan_for_linked_logs(self, source: EventsQuery) -> ErrorTrackingIssueEventsQueryResponse:
        page_size = source.limit or DEFAULT_PAGE_SIZE
        cursor = source.before
        matched: list[ExceptionLinks] = []
        scanned = 0
        exhausted = False

        while len(matched) < page_size and scanned < PAGE_SCAN_BUDGET:
            with self.timings.measure("linked_logs_scan_batch"):
                batch = self._events_runner(
                    scan_query(source, before=cursor, limit=min(SCAN_BATCH_SIZE, PAGE_SCAN_BUDGET - scanned))
                ).calculate()
            exceptions = [exception_links_from_scan_row(row) for row in batch.results]
            if not exceptions:
                exhausted = True
                break
            try:
                with self.timings.measure("linked_logs"):
                    linked = log_linked_uuids(self.team, exceptions)
            except LinkedLogsLookupError as error:
                raise QueryError(
                    "Couldn't check these exceptions for logs in time. Try a shorter date range."
                ) from error

            examined = 0
            for exception in exceptions:
                examined += 1
                cursor = exception.cursor
                if exception.uuid in linked:
                    matched.append(exception)
                    if len(matched) == page_size:
                        break
            scanned += examined
            if examined == len(exceptions) and not batch.hasMore:
                exhausted = True
                break

        response = (
            self._events_runner(rows_by_uuid_query(source, [exception.uuid for exception in matched])).calculate()
            if matched
            else None
        )
        return self._response(
            source,
            response,
            has_more=not exhausted,
            next_cursor=None if exhausted else cursor,
            checked_count=scanned,
        )

    def _last_row_cursor(self, source: EventsQuery, response: EventsQueryResponse) -> str | None:
        if not response.hasMore or not response.results:
            return None
        last_event = response.results[-1][source.select.index("*")]
        link = exception_links_from_star(last_event) if isinstance(last_event, dict) else None
        return link.cursor if link else response.nextCursor

    def _response(
        self,
        source: EventsQuery,
        response: EventsQueryResponse | None,
        *,
        has_more: bool,
        next_cursor: str | None,
        checked_count: int | None = None,
    ) -> ErrorTrackingIssueEventsQueryResponse:
        return ErrorTrackingIssueEventsQueryResponse(
            results=response.results if response else [],
            columns=list(response.columns) if response and response.columns else list(source.select),
            types=list(response.types) if response and response.types else [],
            hasMore=has_more,
            nextCursor=next_cursor,
            checkedCount=checked_count,
            timings=self.timings.to_list(),
            modifiers=self.modifiers,
        )
