"""The status of one transactional email, read from the email_status table that the email path writes.

The send API writes `queued` or `scheduled`, a cancel `canceled`, the email worker `sent` or `failed`, and the SES webhook `delivered`, `bounced` or
`complained`. A row's version only grows as an email moves forward, so the row with the highest version is the status.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries

from products.messaging.backend.facade.contracts import EmailSendStatus, EmailStatus, ScheduledEmail, ScheduledEmailPage
from products.messaging.backend.models.email_status_sql import (
    EMAIL_STATUS_EVENTS_TABLE,
    EMAIL_STATUS_READ_DAYS,
    EMAIL_STATUS_TABLE,
)

# The Node API stamps the send's ID with its own clock, which can run ahead of this one.
_CLOCK_SKEW = timedelta(minutes=5)
_RETENTION = timedelta(days=EMAIL_STATUS_READ_DAYS)
# Every row of a message carries the message's own created_at, so the window prunes to its partition.
_EMAIL_STATUS_QUERY = f"""
SELECT argMax(status, version), argMax(status_at, version), argMax(reason, version)
FROM {EMAIL_STATUS_TABLE}
WHERE team_id = %(team_id)s
  AND message_id = %(message_id)s
  AND created_at >= %(start)s
  AND created_at < %(end)s
GROUP BY message_id
"""


def queued_at(message_id: UUID) -> datetime | None:
    """When the send was queued, or None when no send the table still keeps can have this ID."""
    # The first 6 bytes of a UUIDT are the Unix time in milliseconds. They are compared as a number first, because a
    # made-up ID can name a time far past the last year a datetime holds.
    queued_ms = int.from_bytes(message_id.bytes[:6], "big")
    now = datetime.now(UTC)
    if not (now - _RETENTION).timestamp() * 1000 <= queued_ms <= (now + _CLOCK_SKEW).timestamp() * 1000:
        return None
    return datetime.fromtimestamp(queued_ms / 1000, tz=UTC)


def get_email_status(team_id: int, message_id: UUID) -> EmailStatus | None:
    """The send's status, or None when no send of this team has this ID or its first status has not arrived."""
    created_at = queued_at(message_id)
    if created_at is None:
        return None
    tag_queries(product=Product.MESSAGING, feature=Feature.QUERY)
    rows = cast(
        list,
        sync_execute(
            _EMAIL_STATUS_QUERY,
            {
                "team_id": team_id,
                "message_id": str(message_id),
                "start": created_at - _CLOCK_SKEW,
                "end": created_at + _CLOCK_SKEW,
            },
            # A server holding a project secret API key polls this. No person waits on screen.
            workload=Workload.OFFLINE,
            team_id=team_id,
        ),
    )
    if not rows:
        return None
    status, status_at, reason = rows[0]
    if status not in EmailSendStatus.values:
        return None
    return EmailStatus(
        message_id=str(message_id),
        status=EmailSendStatus(status),
        created_at=created_at,
        status_at=status_at,
        reason=reason or None,
    )


# A send waits at most 30 days after it was queued, so an email that still waits was queued within that time.
_LONGEST_WAIT = timedelta(days=30)
# Only scheduled rows carry `scheduled_at`, and a reschedule writes a new one. The latest row of a message says
# whether it still waits: a cancel or a send outranks every scheduled row.
_SCHEDULED_EMAILS_QUERY = f"""
SELECT toString(message_id) AS id, argMax(recipient, version), argMax(scheduled_at, version) AS due, any(created_at)
FROM {EMAIL_STATUS_EVENTS_TABLE}
WHERE team_id = %(team_id)s
  AND created_at >= %(start)s
  AND (created_at, message_id) IN (
      SELECT created_at, message_id FROM {EMAIL_STATUS_EVENTS_TABLE}
      WHERE team_id = %(team_id)s AND created_at >= %(start)s AND status = 'scheduled'
  )
GROUP BY message_id
HAVING argMax(status, version) = 'scheduled' AND due > %(now)s {{after}}
ORDER BY due, id
LIMIT %(limit)s
"""


def list_scheduled_emails(team_id: int, *, after: tuple[datetime, str] | None, limit: int) -> ScheduledEmailPage:
    """The team's emails that wait for their time, soonest first, starting after the `after` email."""
    now = datetime.now(UTC)
    params: dict[str, Any] = {
        "team_id": team_id,
        "start": now - _LONGEST_WAIT - _CLOCK_SKEW,
        "now": now,
        "limit": limit + 1,
    }
    if after is not None:
        params["after_at"], params["after_id"] = after
    tag_queries(product=Product.MESSAGING, feature=Feature.QUERY)
    rows = cast(
        list,
        sync_execute(
            _SCHEDULED_EMAILS_QUERY.format(after="AND (due, id) > (%(after_at)s, %(after_id)s)" if after else ""),
            params,
            workload=Workload.OFFLINE,
            team_id=team_id,
        ),
    )
    emails = tuple(
        ScheduledEmail(message_id=message_id, to=to, scheduled_at=due, created_at=created_at)
        for message_id, to, due, created_at in rows[:limit]
    )
    has_more = len(rows) > limit
    return ScheduledEmailPage(
        results=emails,
        next_after=(emails[-1].scheduled_at, emails[-1].message_id) if has_more else None,
    )
