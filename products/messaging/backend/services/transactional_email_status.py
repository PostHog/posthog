"""The status of one transactional email, read from the email_status table that the email path writes.

The send API writes `queued`, the email worker `sent` or `failed`, and the SES webhook `delivered`, `bounced` or
`complained`. A row's version only grows as an email moves forward, so the row with the highest version is the status.
"""

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries

from products.messaging.backend.facade.contracts import EmailDeliveryStatus, EmailStatus
from products.messaging.backend.models.email_status_sql import EMAIL_STATUS_RETENTION_DAYS, EMAIL_STATUS_TABLE

# The Node API stamps the send's ID with its own clock, which can run ahead of this one.
_CLOCK_SKEW = timedelta(minutes=5)
_RETENTION = timedelta(days=EMAIL_STATUS_RETENTION_DAYS)
_CONSUMER_LAG = timedelta(hours=2)
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


# A keyed send's ID holds no time, so its own rows say when it was queued. email_status's sort key starts with the
# team and the message, so this reads one message's rows in each partition the retention keeps.
_KEYED_CREATED_AT_QUERY = """
SELECT created_at
FROM {table}
WHERE team_id = %(team_id)s
  AND message_id = %(message_id)s
  AND created_at >= %(start)s
LIMIT 1
"""


def is_keyed_message_id(message_id: UUID) -> bool:
    """A keyed send's ID is uuid5(team, scope, key), so every retry of the key gets the same ID.

    A UUIDT reads as version 5 only once its per-millisecond series passes 0x5000, which takes one process
    minting 20,480 IDs within a single millisecond.
    """
    return message_id.version == 5


def message_created_at(
    team_id: int, message_id: UUID, workload: Workload, lag_fallback_table: str | None = None
) -> datetime | None:
    """When the send was queued, or None when no send the tables still keep can have this ID.

    A keyed ID is looked up in email_status. A reader that reads another table can name it as `lag_fallback_table`,
    so a recent send the email_status consumer has not reached yet is still found there.
    """
    if not is_keyed_message_id(message_id):
        return queued_at(message_id)
    now = datetime.now(UTC)
    found = _keyed_created_at(team_id, message_id, workload, EMAIL_STATUS_TABLE, since=now - _RETENTION)
    if found is None and lag_fallback_table is not None:
        # The fallback table's sort key leads with created_at, so a miss scans every row it reads. Consumer lag is
        # minutes, so a short window keeps a missing ID cheap.
        found = _keyed_created_at(team_id, message_id, workload, lag_fallback_table, since=now - _CONSUMER_LAG)
    return found


def _keyed_created_at(
    team_id: int, message_id: UUID, workload: Workload, table: str, since: datetime
) -> datetime | None:
    tag_queries(product=Product.MESSAGING, feature=Feature.QUERY)
    rows = cast(
        list,
        sync_execute(
            _KEYED_CREATED_AT_QUERY.format(table=table),
            {"team_id": team_id, "message_id": str(message_id), "start": since},
            workload=workload,
            team_id=team_id,
        ),
    )
    return rows[0][0].replace(tzinfo=UTC) if rows else None


def queued_at(message_id: UUID) -> datetime | None:
    """When the send with this UUIDT was queued, or None when no send the table still keeps can have this ID."""
    # The first 6 bytes of a UUIDT are the Unix time in milliseconds. They are compared as a number first, because a
    # made-up ID can name a time far past the last year a datetime holds.
    queued_ms = int.from_bytes(message_id.bytes[:6], "big")
    now = datetime.now(UTC)
    if not (now - _RETENTION).timestamp() * 1000 <= queued_ms <= (now + _CLOCK_SKEW).timestamp() * 1000:
        return None
    return datetime.fromtimestamp(queued_ms / 1000, tz=UTC)


def get_email_status(team_id: int, message_id: UUID) -> EmailStatus | None:
    """The send's status, or None when no send of this team has this ID or its first status has not arrived."""
    created_at = message_created_at(team_id, message_id, Workload.OFFLINE)
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
    if status not in EmailDeliveryStatus.values:
        return None
    return EmailStatus(
        message_id=str(message_id),
        status=EmailDeliveryStatus(status),
        created_at=created_at,
        status_at=status_at,
        reason=reason or None,
    )
