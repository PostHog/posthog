import hmac
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from django.conf import settings

from posthog.clickhouse.client.execute import sync_execute

from products.messaging.backend.facade.contracts import EmailStatus, EmailStatusCursor, EmailStatusRecord

RECIPIENT_HASH_CONTEXT = b"email-recipient-hash-v1"
# The pipeline stamps `created_at` from the message id's time; a margin keeps the read on the right days.
CREATED_AT_MARGIN = timedelta(minutes=1)

_LATEST_STATUS = """
    message_id,
    argMax(status, version) AS latest_status,
    created_at,
    argMax(status_at, version) AS latest_status_at,
    argMax(reason, version) AS latest_reason
"""

_STATUS_BY_ID_QUERY = f"""
SELECT {_LATEST_STATUS}
FROM email_status
WHERE team_id = %(team_id)s
  AND message_id = %(message_id)s
  AND created_at >= %(created_from)s
  AND created_at < %(created_to)s
GROUP BY message_id, created_at
"""

_STATUSES_BY_RECIPIENT_QUERY = """
SELECT {latest_status}
FROM email_status
WHERE team_id = %(team_id)s
  AND recipient_hash = %(recipient_hash)s
  AND created_at >= %(since)s
  {cursor_clause}
GROUP BY message_id, created_at
ORDER BY created_at DESC, message_id DESC
LIMIT %(limit)s
"""


def email_recipient_hash(recipient: str) -> str | None:
    """The address as the email pipeline hashes it, so a lookup finds its emails without storing the address."""
    salt_key = next(iter(settings.ENCRYPTION_SALT_KEYS), "").strip()
    if not salt_key:
        return None
    key = hmac.new(salt_key.encode(), RECIPIENT_HASH_CONTEXT, hashlib.sha256).digest()
    return hmac.new(key, recipient.strip().lower().encode(), hashlib.sha256).hexdigest()


def get_email_status(team_id: int, message_id: UUID) -> EmailStatusRecord | None:
    """None for an unknown id, another team's id, and an email whose first status has not arrived yet."""
    created_at = _created_at(message_id)
    rows = sync_execute(
        _STATUS_BY_ID_QUERY,
        {
            "team_id": team_id,
            "message_id": message_id,
            "created_from": created_at - CREATED_AT_MARGIN,
            "created_to": created_at + CREATED_AT_MARGIN,
        },
    )
    return _record(rows[0]) if rows else None


def list_email_statuses_by_recipient(
    team_id: int, recipient: str, *, since: datetime, limit: int, cursor: EmailStatusCursor | None = None
) -> list[EmailStatusRecord]:
    """The latest status of each email sent to the address since `since`, newest first, after `cursor`."""
    recipient_hash = email_recipient_hash(recipient)
    if recipient_hash is None:
        return []
    params: dict[str, Any] = {"team_id": team_id, "recipient_hash": recipient_hash, "since": since, "limit": limit}
    cursor_clause = ""
    if cursor is not None:
        cursor_clause = "AND (created_at, message_id) < (%(cursor_created_at)s, %(cursor_message_id)s)"
        params |= {"cursor_created_at": cursor.created_at, "cursor_message_id": cursor.message_id}
    query = _STATUSES_BY_RECIPIENT_QUERY.format(latest_status=_LATEST_STATUS, cursor_clause=cursor_clause)
    return [_record(row) for row in sync_execute(query, params)]


def _created_at(message_id: UUID) -> datetime:
    # A message id is a UUIDT, whose first 48 bits are its creation time in milliseconds.
    return datetime.fromtimestamp(int(message_id.hex[:12], 16) / 1000, UTC)


def _record(row: tuple[Any, ...]) -> EmailStatusRecord:
    message_id, status, created_at, status_at, reason = row
    return EmailStatusRecord(
        message_id=message_id,
        status=EmailStatus(status),
        created_at=created_at.replace(tzinfo=UTC),
        status_at=status_at.replace(tzinfo=UTC),
        reason=reason or None,
    )
