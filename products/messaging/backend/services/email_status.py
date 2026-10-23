import hmac
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from django.conf import settings

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context

from products.messaging.backend.facade.contracts import EmailStatus, EmailStatusRecord
from products.messaging.backend.models.email_status_sql import EMAIL_STATUS_RETENTION_DAYS

RECIPIENT_HASH_CONTEXT = b"email-recipient-hash-v1"
EMAIL_STATUS_RETENTION = timedelta(days=EMAIL_STATUS_RETENTION_DAYS)
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
  AND recipient_hash IN %(recipient_hashes)s
  AND created_at >= fromUnixTimestamp64Milli(%(since_ms)s, 'UTC')
  {cursor_clause}
GROUP BY message_id, created_at
ORDER BY created_at DESC, message_id DESC
LIMIT %(limit)s
"""


def _recipient_hashes(recipient: str) -> list[str]:
    # The pipeline hashes with the first salt key. An email recorded before a key rotation holds an older key's hash.
    salt_keys = [salt_key.strip() for salt_key in settings.ENCRYPTION_SALT_KEYS]
    if not salt_keys or not salt_keys[0]:
        return []
    address = recipient.strip().lower().encode()
    return [_keyed_hash(salt_key, address) for salt_key in salt_keys if salt_key]


def _keyed_hash(salt_key: str, address: bytes) -> str:
    key = hmac.new(salt_key.encode(), RECIPIENT_HASH_CONTEXT, hashlib.sha256).digest()
    return hmac.new(key, address, hashlib.sha256).hexdigest()


def get_email_status(team_id: int, message_id: UUID) -> EmailStatusRecord | None:
    """None for an unknown id, another team's id, and an email whose first status has not arrived yet."""
    created_at = message_created_at(message_id)
    if created_at is None:
        return None
    rows = _execute(
        team_id,
        "email_status_by_id",
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
    team_id: int, recipient: str, *, since: datetime, limit: int, cursor: UUID | None = None
) -> list[EmailStatusRecord]:
    """The latest status of each email sent to the address since `since`, newest first, after `cursor`."""
    recipient_hashes = _recipient_hashes(recipient)
    if not recipient_hashes:
        return []
    params: dict[str, Any] = {
        "team_id": team_id,
        "recipient_hashes": tuple(recipient_hashes),
        "since_ms": int(since.timestamp() * 1000),
        "limit": limit,
    }
    cursor_clause = ""
    if cursor is not None:
        cursor_clause = (
            "AND (created_at, message_id) < (fromUnixTimestamp64Milli(%(cursor_created_ms)s, 'UTC'), "
            "%(cursor_message_id)s)"
        )
        params |= {"cursor_created_ms": _created_ms(cursor), "cursor_message_id": cursor}
    query = _STATUSES_BY_RECIPIENT_QUERY.format(latest_status=_LATEST_STATUS, cursor_clause=cursor_clause)
    return [_record(row) for row in _execute(team_id, "email_statuses_by_recipient", query, params)]


def _execute(team_id: int, query_type: str, query: str, params: dict[str, Any]) -> list[tuple[Any, ...]]:
    with tags_context(team_id=team_id, product=Product.MESSAGING, feature=Feature.QUERY, query_type=query_type):
        return sync_execute(query, params)


def _created_ms(message_id: UUID) -> int:
    # A message id is a UUIDT, whose first 48 bits are its creation time in milliseconds.
    return int(message_id.hex[:12], 16)


def message_created_at(message_id: UUID) -> datetime | None:
    """When PostHog accepted the email, or None for an id that no email can have."""
    created_ms = _created_ms(message_id)
    # Another UUID can decode to a time past what datetime holds. No email was created after now.
    if created_ms > (datetime.now(UTC) + CREATED_AT_MARGIN).timestamp() * 1000:
        return None
    return datetime.fromtimestamp(created_ms / 1000, UTC)


def _record(row: tuple[Any, ...]) -> EmailStatusRecord:
    message_id, status, created_at, status_at, reason = row
    return EmailStatusRecord(
        message_id=message_id,
        status=EmailStatus(status),
        created_at=created_at.replace(tzinfo=UTC),
        status_at=status_at.replace(tzinfo=UTC),
        reason=reason or None,
    )
