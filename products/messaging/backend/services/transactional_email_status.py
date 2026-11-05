"""The status of one transactional email, read from the email_status table that the email path writes.

The send API writes `queued`, the email worker `sent` or `failed`, and the SES webhook `delivered`, `bounced` or
`complained`. A row's version only grows as an email moves forward, so the row with the highest version is the status.

The rows reach the table through Kafka, a few seconds after the send. Until the first row arrives, the record of the
accepted send answers `queued`.
"""

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import redis
import structlog

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.redis import get_client

from products.messaging.backend.facade.contracts import EmailDeliveryStatus, EmailStatus
from products.messaging.backend.models.email_status_sql import EMAIL_STATUS_RETENTION_DAYS, EMAIL_STATUS_TABLE

logger = structlog.get_logger(__name__)

# Long past the time the first status row takes to reach the table, so a slow consumer still reads as queued.
_ACCEPTED_SEND_TTL = timedelta(minutes=10)
# The record is optional, so the connect and the command each time out after 0.25 s, and a stalled Redis adds at
# most 0.5 s to the send's reply or a status read. The DNS lookup of a new connection is outside both timeouts.
_ACCEPTED_SEND_REDIS_TIMEOUT_SECONDS = 0.25
# The Node API stamps the send's ID with its own clock, which can run ahead of this one.
_CLOCK_SKEW = timedelta(minutes=5)
_RETENTION = timedelta(days=EMAIL_STATUS_RETENTION_DAYS)
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


def _accepted_send_redis() -> redis.Redis:
    return get_client(
        socket_timeout=_ACCEPTED_SEND_REDIS_TIMEOUT_SECONDS,
        socket_connect_timeout=_ACCEPTED_SEND_REDIS_TIMEOUT_SECONDS,
    )


def _accepted_send_key(team_id: int, message_id: str) -> str:
    return f"messaging:transactional_email:accepted:{team_id}:{message_id}"


def record_accepted_send(team_id: int, message_id: str) -> None:
    """Remember that the pipeline queued this send, so its status reads as queued before the first row arrives."""
    try:
        _accepted_send_redis().set(_accepted_send_key(team_id, message_id), 1, ex=_ACCEPTED_SEND_TTL)
    except Exception:
        # The email is already queued, so a lost record only brings back the short 404 window.
        logger.warning("transactional_email_accepted_send_not_recorded", team_id=team_id, exc_info=True)


def _was_accepted(team_id: int, message_id: UUID) -> bool:
    try:
        return bool(_accepted_send_redis().exists(_accepted_send_key(team_id, str(message_id))))
    except Exception:
        logger.warning("transactional_email_accepted_send_not_read", team_id=team_id, exc_info=True)
        return False


def get_email_status(team_id: int, message_id: UUID) -> EmailStatus | None:
    """The send's status, or None when no send of this team has this ID."""
    created_at = queued_at(message_id)
    if created_at is None:
        return None
    return _stored_status(team_id, message_id, created_at) or _accepted_status(team_id, message_id, created_at)


def _accepted_status(team_id: int, message_id: UUID, created_at: datetime) -> EmailStatus | None:
    if not _was_accepted(team_id, message_id):
        return None
    return EmailStatus(
        message_id=str(message_id),
        status=EmailDeliveryStatus.QUEUED,
        created_at=created_at,
        status_at=created_at,
    )


def _stored_status(team_id: int, message_id: UUID, created_at: datetime) -> EmailStatus | None:
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
