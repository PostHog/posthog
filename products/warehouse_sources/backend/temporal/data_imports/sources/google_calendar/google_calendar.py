from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen
from posthog.egress.google_workspace import google_workspace_request

from products.warehouse_sources.backend.temporal.data_imports.sources.common.member_accounts import (
    ALL_ACCOUNTS_UNREADABLE,
    MemberAccount,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.google_calendar.settings import (
    ACCOUNTS,
    EVENTS,
    PRIMARY_KEYS,
)

EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
EVENTS_ENDPOINT = "/calendar/v3/calendars/primary/events"
EGRESS_SOURCE = "warehouse_google_calendar_source"
PAGE_SIZE = 250
REQUEST_TIMEOUT_SECONDS = 30
BACKFILL = timedelta(days=365)

# Google answers a quota error with 403 and one of these reasons. Any other 403 is a refused account.
RATE_LIMIT_REASONS = ("rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded")


@frozen
class GoogleCalendarCursor:
    """Where the next run starts for each account, keyed by Google account id.

    `updated_at` is the newest `updated` value synced, which finds edits to events already synced.
    `synced_until` is the end of the time range already read, which finds events that started since.
    """

    cursor_kind: ClassVar[str] = "google_calendar_events"

    updated_at: dict[str, str]
    synced_until: dict[str, str]


def _rfc3339(value: datetime) -> str:
    # The same shape as Google's own `updated` values, so the two compare as strings.
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class _AccountRefused(Exception):
    pass


class _UpdatedMinTooOld(Exception):
    pass


def _parse_when(when: dict[str, Any] | None) -> datetime | None:
    raw = (when or {}).get("dateTime") or (when or {}).get("date")
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _event_row(account_id: str, event: dict[str, Any]) -> dict[str, Any]:
    start = _parse_when(event.get("start"))
    end = _parse_when(event.get("end"))
    attendees = event.get("attendees") or []
    own_attendance: dict[str, Any] = next((attendee for attendee in attendees if attendee.get("self")), {})
    # Titles, descriptions and attendee addresses are left out on purpose: every project member
    # who can query the warehouse reads this table.
    return {
        "account_id": account_id,
        "id": event["id"],
        "status": event.get("status"),
        "event_type": event.get("eventType"),
        "visibility": event.get("visibility"),
        "start_at": start,
        "end_at": end,
        "is_all_day": "date" in (event.get("start") or {}),
        "duration_minutes": int((end - start).total_seconds() // 60) if start and end else None,
        "attendee_count": len(attendees),
        "response_status": own_attendance.get("responseStatus"),
        "is_organizer": bool((event.get("organizer") or {}).get("self")),
        "is_recurring": "recurringEventId" in event,
        "has_video_call": bool(event.get("hangoutLink") or event.get("conferenceData")),
        "created_at": event.get("created"),
        "updated_at": event.get("updated"),
    }


def _list_events(account: MemberAccount, params: dict[str, Any]) -> Iterator[list[dict[str, Any]]]:
    page_token: str | None = None
    while True:
        response = google_workspace_request(
            "GET",
            EVENTS_URL,
            access_token=account.access_token,
            account_id=account.account_id,
            source=EGRESS_SOURCE,
            endpoint=EVENTS_ENDPOINT,
            params={**params, **({"pageToken": page_token} if page_token else {})},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code == 410:
            raise _UpdatedMinTooOld
        if response.status_code == 401 or (
            response.status_code == 403 and not any(reason in response.text for reason in RATE_LIMIT_REASONS)
        ):
            raise _AccountRefused
        response.raise_for_status()
        body = response.json()
        yield body.get("items") or []
        page_token = body.get("nextPageToken")
        if not page_token:
            return


def _account_events(
    account: MemberAccount, cursor: GoogleCalendarCursor | None, now: datetime
) -> Iterator[list[dict[str, Any]]]:
    """Every event of the account that the table does not hold in its current state."""
    base = {"singleEvents": "true", "showDeleted": "true", "maxResults": PAGE_SIZE, "orderBy": "updated"}
    updated_at = cursor.updated_at.get(account.account_id) if cursor else None
    synced_until = cursor.synced_until.get(account.account_id) if cursor else None
    backfill_window = {"timeMin": _rfc3339(now - BACKFILL), "timeMax": _rfc3339(now)}

    if not updated_at or not synced_until:
        yield from _list_events(account, {**base, **backfill_window})
        return

    try:
        # A recurring meeting that started since the last run was not edited, so it needs its own pass.
        yield from _list_events(account, {**base, "timeMin": synced_until, "timeMax": _rfc3339(now)})
        yield from _list_events(account, {**base, **backfill_window, "updatedMin": updated_at})
    except _UpdatedMinTooOld:
        yield from _list_events(account, {**base, **backfill_window})


def events_source(
    accounts: Sequence[MemberAccount],
    cursor: GoogleCalendarCursor | None,
    stage_cursor: Callable[[GoogleCalendarCursor], None],
    logger: FilteringBoundLogger,
) -> SourceResponse:
    now = datetime.now(UTC)
    newest_updated_at: dict[str, str] = {}
    synced_until: dict[str, str] = {}

    def get_rows() -> Iterator[list[dict[str, Any]]]:
        refused = 0
        for account in accounts:
            try:
                for events in _account_events(account, cursor, now):
                    rows = [_event_row(account.account_id, event) for event in events]
                    if not rows:
                        continue
                    newest = max((row["updated_at"] for row in rows if row["updated_at"]), default=None)
                    if newest:
                        newest_updated_at[account.account_id] = max(
                            newest, newest_updated_at.get(account.account_id, newest)
                        )
                    yield rows
            except _AccountRefused:
                refused += 1
                logger.warning(
                    "Skipping a Google account that refused the request. Its owner needs to reconnect it.",
                    account_id=account.account_id,
                )
                continue
            synced_until[account.account_id] = _rfc3339(now)

        if accounts and refused == len(accounts):
            raise ValueError(ALL_ACCOUNTS_UNREADABLE)

    def on_complete() -> None:
        if not synced_until:
            return
        previous = cursor.updated_at if cursor else {}
        stage_cursor(
            GoogleCalendarCursor(
                # An account with no events yet still needs a position, or every run backfills it again.
                updated_at={
                    account_id: newest_updated_at.get(account_id) or previous.get(account_id) or _rfc3339(now)
                    for account_id in synced_until
                },
                synced_until=synced_until,
            )
        )

    return SourceResponse(
        name=EVENTS,
        items=get_rows,
        primary_keys=PRIMARY_KEYS[EVENTS],
        partition_mode="datetime",
        partition_format="month",
        partition_keys=["created_at"],
        # Accounts are read one after another, so rows are not in one global order.
        sort_mode="desc",
        on_complete=on_complete,
    )


def accounts_source(rows: list[dict[str, Any]]) -> SourceResponse:
    def get_rows() -> Iterator[list[dict[str, Any]]]:
        if rows:
            yield rows

    return SourceResponse(name=ACCOUNTS, items=get_rows, primary_keys=PRIMARY_KEYS[ACCOUNTS])
