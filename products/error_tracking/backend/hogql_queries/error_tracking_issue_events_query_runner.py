import structlog

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
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents

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

logger = structlog.get_logger(__name__)

LINKED_LOGS_COLUMN = "linked_logs"
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
        # Internal callers skip access validation, which applies to user requests only.
        self._can_read_logs = True
        if "*" not in self.query.source.select:
            raise QueryError("The source query must select `*`")

    @property
    def _required(self) -> list[ErrorTrackingLinkedDataKind]:
        return self.query.requiredLinkedData or []

    def validate_query_runner_access(self, user: User) -> bool:
        super().validate_query_runner_access(user)
        access = UserAccessControl(user=user, team=self.team)
        if ErrorTrackingLinkedDataKind.LOGS in self._required:
            access.assert_access_level_for_resource("logs", "viewer")
        # The list still loads for someone who can't see logs, just without the column's answers.
        self._can_read_logs = access.check_access_level_for_resource("logs", "viewer")
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
        self._set_recording_flags(source, response.results)
        rows = (
            self._with_linked_logs_column(source, response.results) if self.query.withLinkedLogs else response.results
        )
        return self._response(
            source,
            response,
            rows,
            has_more=bool(response.hasMore),
            next_cursor=self._last_row_cursor(source, response),
        )

    def _star_index(self, source: EventsQuery) -> int:
        return source.select.index("*")

    def _set_recording_flags(self, source: EventsQuery, rows: list[list]) -> None:
        """Recheck `$has_recording` the way the Recording tab does, so a deleted or expired recording reads as none."""
        star_index = self._star_index(source)
        properties_by_row = [
            row[star_index]["properties"]
            for row in rows
            if isinstance(row[star_index], dict) and isinstance(row[star_index].get("properties"), dict)
        ]
        session_ids = sorted(
            {
                properties["$session_id"]
                for properties in properties_by_row
                if isinstance(properties.get("$session_id"), str) and properties["$session_id"]
            }
        )
        if not session_ids:
            return
        with self.timings.measure("recording_flags"):
            exists = SessionReplayEvents().batch_exists(session_ids, self.team)
        for properties in properties_by_row:
            session_id = properties.get("$session_id")
            if isinstance(session_id, str) and session_id:
                properties["$has_recording"] = exists.get(session_id, False)

    def _with_linked_logs_column(self, source: EventsQuery, rows: list[list]) -> list[list]:
        if not self._can_read_logs:
            return [[*row, None] for row in rows]
        star_index = self._star_index(source)
        links = [
            exception_links_from_star(row[star_index]) if isinstance(row[star_index], dict) else None for row in rows
        ]
        try:
            with self.timings.measure("linked_logs"):
                linked = log_linked_uuids(self.team, [link for link in links if link is not None])
        except LinkedLogsLookupError:
            # The list still loads without the column. The issue page then treats every row as unknown.
            logger.warning("error_tracking_linked_logs_annotation_failed", team_id=self.team.pk, exc_info=True)
            return [[*row, None] for row in rows]
        return [[*row, link.uuid in linked if link else None] for row, link in zip(rows, links)]

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
        if response:
            self._set_recording_flags(source, response.results)
        return self._response(
            source,
            response,
            [[*row, True] for row in response.results] if response else [],
            has_more=not exhausted,
            next_cursor=None if exhausted else cursor,
            linked_logs_column=True,
        )

    def _last_row_cursor(self, source: EventsQuery, response: EventsQueryResponse) -> str | None:
        if not response.hasMore or not response.results:
            return None
        last_event = response.results[-1][self._star_index(source)]
        link = exception_links_from_star(last_event) if isinstance(last_event, dict) else None
        return link.cursor if link else response.nextCursor

    def _response(
        self,
        source: EventsQuery,
        response: EventsQueryResponse | None,
        rows: list[list],
        *,
        has_more: bool,
        next_cursor: str | None,
        linked_logs_column: bool = False,
    ) -> ErrorTrackingIssueEventsQueryResponse:
        columns = list(response.columns) if response and response.columns else list(source.select)
        types = list(response.types) if response and response.types else []
        if linked_logs_column or self.query.withLinkedLogs:
            columns.append(LINKED_LOGS_COLUMN)
            if types:
                types.append("Nullable(Bool)")
        return ErrorTrackingIssueEventsQueryResponse(
            results=rows,
            columns=columns,
            types=types,
            hasMore=has_more,
            nextCursor=next_cursor,
            timings=self.timings.to_list(),
            modifiers=self.modifiers,
        )
