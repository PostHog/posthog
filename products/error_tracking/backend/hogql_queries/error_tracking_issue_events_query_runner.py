from datetime import UTC, datetime, timedelta

from posthog.schema import (
    CachedErrorTrackingIssueEventsQueryResponse,
    ErrorTrackingIssueEventsQuery,
    ErrorTrackingIssueEventsQueryResponse,
    EventsQuery,
)

from posthog.hogql import ast
from posthog.hogql.escape_sql import escape_hogql_string

from posthog.hogql_queries.events_query_runner import EventsQueryRunner, split_pagination_cursor
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.models import Team
from posthog.utils import relative_date_parse

from products.error_tracking.backend.hogql_queries.access import ErrorTrackingQueryRunnerAccessMixin
from products.error_tracking.backend.hogql_queries.error_tracking_query_runner_utils import validate_uuid_param


def _datetime_literal(value: datetime) -> str:
    # Microseconds matter: a page cursor can fall between two exceptions in the same second.
    return f"toDateTime64({escape_hogql_string(value.astimezone(UTC).strftime('%Y-%m-%d %H:%M:%S.%f'))}, 6, 'UTC')"


def recording_condition(issue_id: str, source: EventsQuery, team: Team) -> str:
    """A HogQL condition that keeps the exceptions whose session has a recording the player can open.

    It applies the checks of `SessionReplayEvents.batch_exists`, which the Recording tab uses: a deleted
    recording or one past its retention does not count. It also needs snapshot data, which rows such as
    deletion markers do not carry. The subquery reads only the sessions of the issue's exceptions in the
    list's time range, so its set stays small for large teams.
    """
    now = datetime.now(UTC)
    # The same defaults EventsQueryRunner applies to an unset range. `before` can be a page cursor.
    after = source.after or "-24h"
    before = split_pagination_cursor(source.before)[0] if source.before else None
    date_to = relative_date_parse(before, team.timezone_info) if before else now + timedelta(seconds=5)
    date_from = None if after == "all" else relative_date_parse(split_pagination_cursor(after)[0], team.timezone_info)
    # A recording can start up to a day before the exception it contains.
    recording_from = f"AND min_first_timestamp >= {_datetime_literal(date_from)} - INTERVAL 1 DAY" if date_from else ""
    events_from = f"AND timestamp >= {_datetime_literal(date_from)}" if date_from else ""
    # Recording rows are read up to now, not up to the end of the page. A deletion writes its own row, stamped
    # with the time of the deletion, and a recording can start after the exception in the same session.
    return f"""$session_id IN (
        SELECT session_id FROM raw_session_replay_events
        WHERE min_first_timestamp <= {_datetime_literal(now)} {recording_from}
            AND session_id IN (
                SELECT DISTINCT $session_id FROM events
                WHERE event = '$exception'
                    AND issue_id = toUUID({escape_hogql_string(issue_id)})
                    AND notEmpty($session_id)
                    AND timestamp <= {_datetime_literal(date_to)} {events_from}
            )
        GROUP BY session_id
        HAVING max(is_deleted) = 0
            AND sum(size) > 0
            AND dateTrunc('day', min(min_first_timestamp)) + toIntervalDay(coalesce(max(retention_period_days), 30)) >= {_datetime_literal(now)}
    )"""


class ErrorTrackingIssueEventsQueryRunner(
    ErrorTrackingQueryRunnerAccessMixin, AnalyticsQueryRunner[ErrorTrackingIssueEventsQueryResponse]
):
    query: ErrorTrackingIssueEventsQuery
    cached_response: CachedErrorTrackingIssueEventsQueryResponse

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return self._events_runner().to_query()

    def _events_runner(self) -> EventsQueryRunner:
        issue_id = validate_uuid_param(self.query.issueId, "issueId")
        source = self.query.source.model_copy(deep=True)
        if self.query.onlyWithRecording:
            source.where = [*(source.where or []), recording_condition(issue_id, source, self.team)]
        return EventsQueryRunner(
            query=source,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
            user=self.user,
        )

    def _calculate(self) -> ErrorTrackingIssueEventsQueryResponse:
        response = self._events_runner().calculate()
        if self.query.onlyWithRecording and "*" in self.query.source.select:
            self._mark_recordings(response.results, self.query.source.select.index("*"))
        return ErrorTrackingIssueEventsQueryResponse(
            results=response.results,
            columns=response.columns or [],
            types=response.types or [],
            hasMore=response.hasMore,
            nextCursor=response.nextCursor,
            hogql=response.hogql,
            timings=self.timings.to_list(),
            modifiers=response.modifiers or self.modifiers,
        )

    @staticmethod
    def _mark_recordings(results: list[list], star_index: int) -> None:
        # Every row passed the recording condition. The events runner's own `$has_recording` check reads replay
        # rows only up to the page's cursor, so it misses a recording that starts later in the session.
        for row in results:
            event = row[star_index]
            if isinstance(event, dict) and isinstance(event.get("properties"), dict):
                event["properties"]["$has_recording"] = True
