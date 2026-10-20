from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from posthog.schema import EventsQuery

from posthog.hogql.escape_sql import escape_hogql_string

from posthog.dataclasses import frozen
from posthog.hogql_queries.events_query_runner import CURSOR_DELIMITER, split_pagination_cursor
from posthog.models import Team
from posthog.utils import relative_date_parse

from products.logs.backend.facade.linked_logs import LogLinkCandidate, find_log_linked_keys

# The light columns a scan reads to decide whether an exception links to logs.
SCAN_SELECT = ["uuid", "timestamp", "$session_id", "properties.$trace_id"]
# One logs query checks this many exceptions, which keeps its ID lists and time windows small.
SCAN_BATCH_SIZE = 500


@frozen
class ExceptionLinks:
    uuid: str
    timestamp: datetime
    session_id: str | None
    trace_id: str | None

    @property
    def cursor(self) -> str:
        """The `before` cursor that continues a `timestamp DESC, uuid DESC` list after this exception."""
        return f"{self.timestamp.isoformat()}{CURSOR_DELIMITER}{self.uuid}"

    def as_log_link_candidate(self) -> LogLinkCandidate:
        return LogLinkCandidate(
            key=self.uuid, timestamp=self.timestamp, trace_id=self.trace_id, session_id=self.session_id
        )


def _non_empty_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def exception_links_from_scan_row(row: Sequence[object]) -> ExceptionLinks:
    uuid, timestamp, session_id, trace_id = row
    if not isinstance(timestamp, datetime):
        raise ValueError("A scan row must carry the exception's timestamp as a datetime")
    return ExceptionLinks(
        uuid=str(uuid),
        timestamp=timestamp,
        session_id=_non_empty_string(session_id),
        trace_id=_non_empty_string(trace_id),
    )


def exception_links_from_star(event: dict) -> ExceptionLinks | None:
    """Read the links from the `*` column of an events list row."""
    timestamp = event.get("timestamp")
    properties = event.get("properties")
    if not isinstance(timestamp, datetime) or not isinstance(properties, dict):
        return None
    return ExceptionLinks(
        uuid=str(event["uuid"]),
        timestamp=timestamp,
        session_id=_non_empty_string(properties.get("$session_id")),
        trace_id=_non_empty_string(properties.get("$trace_id")),
    )


def _datetime_literal(value: datetime) -> str:
    return f"toDateTime({escape_hogql_string(value.astimezone(UTC).strftime('%Y-%m-%d %H:%M:%S'))}, 'UTC')"


def recording_condition(issue_id: str, source: EventsQuery, team: Team) -> str:
    """A HogQL condition that keeps the exceptions whose session has a recording the player can open.

    It applies the checks of `SessionReplayEvents.batch_exists`, which the Recording tab uses: a deleted
    recording or one past its retention does not count. The subquery reads only the sessions of the
    issue's exceptions in the list's time range, so its set stays small for large teams.
    """
    # The same defaults EventsQueryRunner applies to an unset range. `before` can be a page cursor.
    after = source.after or "-24h"
    before = split_pagination_cursor(source.before)[0] if source.before else None
    date_to = relative_date_parse(before, team.timezone_info) if before else datetime.now(UTC) + timedelta(seconds=5)
    date_from = None if after == "all" else relative_date_parse(split_pagination_cursor(after)[0], team.timezone_info)
    recording_from = f"AND min_first_timestamp >= {_datetime_literal(date_from)} - INTERVAL 1 DAY" if date_from else ""
    events_from = f"AND timestamp >= {_datetime_literal(date_from)}" if date_from else ""
    # A recording can start up to a day before the exception it contains.
    return f"""$session_id IN (
        SELECT session_id FROM raw_session_replay_events
        WHERE min_first_timestamp <= {_datetime_literal(date_to)} {recording_from}
            AND session_id IN (
                SELECT $session_id FROM events
                WHERE event = '$exception'
                    AND issue_id = toUUID({escape_hogql_string(issue_id)})
                    AND notEmpty($session_id)
                    AND timestamp <= {_datetime_literal(date_to)} {events_from}
            )
        GROUP BY session_id
        HAVING max(is_deleted) = 0
            AND dateTrunc('day', min(min_first_timestamp)) + toIntervalDay(coalesce(max(retention_period_days), 30)) >= now()
    )"""


def scan_query(source: EventsQuery, *, before: str | None, limit: int) -> EventsQuery:
    """The source list query, reduced to the columns a scan needs, from `before` onwards."""
    return source.model_copy(
        update={
            "select": SCAN_SELECT,
            "before": before,
            "limit": limit,
            "offset": None,
            "orderBy": ["timestamp DESC"],
        }
    )


def rows_by_uuid_query(source: EventsQuery, uuids: Sequence[str]) -> EventsQuery:
    """The source list query, restricted to the exceptions given."""
    uuid_list = ", ".join(f"toUUID({escape_hogql_string(uuid)})" for uuid in uuids)
    return source.model_copy(
        update={
            "where": [*(source.where or []), f"uuid IN ({uuid_list})"],
            "limit": len(uuids),
            "offset": None,
            "orderBy": ["timestamp DESC"],
        }
    )


def log_linked_uuids(team: Team, exceptions: Sequence[ExceptionLinks]) -> frozenset[str]:
    """The exceptions with a log that the issue page's Logs tab shows for them. Raises `LinkedLogsLookupError`."""
    linked: set[str] = set()
    for start in range(0, len(exceptions), SCAN_BATCH_SIZE):
        batch = exceptions[start : start + SCAN_BATCH_SIZE]
        linked |= find_log_linked_keys(team=team, candidates=[exception.as_log_link_candidate() for exception in batch])
    return frozenset(linked)
