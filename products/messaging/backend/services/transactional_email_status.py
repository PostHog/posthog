"""The status of one transactional email, read from the email_status table that the email path writes.

The send API writes `queued`, or `scheduled` for a send that waits for its time, the email worker `sent` or `failed`, and the SES webhook `delivered`, `bounced` or
`complained`. A row's version only grows as an email moves forward, so the row with the highest version is the status.
"""

import re
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid5

from posthog.schema import HogQLQueryModifiers

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.event.new_events_schema import events_route_scope

from products.messaging.backend.facade.contracts import EmailSendStatus, EmailStatus, SentMessageMatch
from products.messaging.backend.models.email_status_sql import (
    EMAIL_STATUS_EVENTS_TABLE,
    EMAIL_STATUS_RETENTION_DAYS,
    EMAIL_STATUS_SHOWN_REASON,
    EMAIL_STATUS_TABLE,
)

# The Node API stamps the send's ID with its own clock, which can run ahead of this one.
_CLOCK_SKEW = timedelta(minutes=5)
_RETENTION = timedelta(days=EMAIL_STATUS_RETENTION_DAYS)
_CONSUMER_LAG = timedelta(hours=2)
_KEYED_RUN_ID_NAMESPACE = UUID("c2b7f0a4-4c3e-4b8e-9d4f-6a1f3e5d2b90")
_TRANSACTIONAL_EMAIL_RUN_SCOPE = "transactional-email"
# Every row of a message carries the message's own created_at, so the window prunes to its partition.
_EMAIL_STATUS_QUERY = f"""
SELECT argMax(status, version), argMax(status_at, version), argMax({EMAIL_STATUS_SHOWN_REASON}, version)
FROM {EMAIL_STATUS_TABLE}
WHERE team_id = %(team_id)s
  AND message_id = %(message_id)s
  AND created_at >= %(start)s
  AND created_at < %(end)s
GROUP BY message_id
"""


# A keyed send's ID holds no time, so its own rows say when it was queued. email_status's sort key starts with the
# team and the message, so this reads one message's rows in each partition the retention keeps. A refused send claims
# no key, so a later retry under the same key is a newer attempt with the same ID, and the newest one is the send.
_KEYED_CREATED_AT_QUERY = """
SELECT created_at
FROM {table}
WHERE team_id = %(team_id)s
  AND message_id = %(message_id)s
  AND created_at >= %(start)s
ORDER BY created_at DESC
LIMIT 1
"""


def is_keyed_message_id(message_id: UUID) -> bool:
    """A keyed send's ID is uuid5(team, scope, key), so every retry of the key gets the same ID.

    A UUIDT reads as version 5 only once its per-millisecond series passes 0x5000, which takes one process
    minting 20,480 IDs within a single millisecond.
    """
    return message_id.version == 5


def keyed_message_id(team_id: int, idempotency_key: str) -> UUID:
    name = json.dumps([team_id, _TRANSACTIONAL_EMAIL_RUN_SCOPE, idempotency_key], separators=(",", ":"))
    return uuid5(_KEYED_RUN_ID_NAMESPACE, name)


# The events cluster has no email_status table, so a project that reads events_json still looks a send up here.
@events_route_scope(HogQLQueryModifiers(useNewEventsSchema=False))
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


@events_route_scope(HogQLQueryModifiers(useNewEventsSchema=False))
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
    if status not in EmailSendStatus.values:
        return None
    return EmailStatus(
        message_id=str(message_id),
        status=EmailSendStatus(status),
        created_at=created_at,
        status_at=status_at,
        reason=reason or None,
    )


# Anyone can send these headers, and each extra id weakens the bloom index. References lists the newest ids last, and
# those name the reply's parent, so only the last few of each header are read.
_MAX_WIRE_IDS_PER_HEADER = 10
# A reply needs In-Reply-To and References, and References keeps its newest ids at the end.
_MAX_HEADERS = 2
_MAX_HEADER_CHARS = 10_000

# SES writes `<MessageId@email.amazonses.com>` or `@<region>.amazonses.com`, and the sent row keeps only the MessageId.
_SES_WIRE_MESSAGE_ID = re.compile(r"<([^<>@\s]+)@[a-z0-9-]+\.amazonses\.com>", re.IGNORECASE)
_SENT_MESSAGE_QUERY = f"""
SELECT provider_message_id, any(message_id)
FROM {EMAIL_STATUS_EVENTS_TABLE}
WHERE team_id = %(team_id)s
  AND provider_message_id IN %(provider_message_ids)s
GROUP BY provider_message_id
"""


def _without_comments(header: str) -> str:
    """An RFC 5322 comment can quote another Message-ID, which names no parent of the reply. One pass, so nesting
    in a header anyone can send costs no more than its length."""
    depth = 0
    escaped = False
    kept = []
    for char in header:
        if escaped:
            escaped = False
        elif depth and char == "\\":
            escaped = True
        elif char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
        elif not depth:
            kept.append(char)
    return "".join(kept)


@events_route_scope(HogQLQueryModifiers(useNewEventsSchema=False))
def match_sent_message_ids(team_id: int, headers: Sequence[str]) -> tuple[SentMessageMatch, ...]:
    """The sends of this team named in these header values, such as a reply's raw In-Reply-To and References."""
    wire_ids: dict[str, str] = {}
    for header in headers[:_MAX_HEADERS]:
        newest: dict[str, str] = {}
        for match in _SES_WIRE_MESSAGE_ID.finditer(_without_comments(header[-_MAX_HEADER_CHARS:])):
            newest.pop(match[1], None)
            newest[match[1]] = match[0]
            if len(newest) > _MAX_WIRE_IDS_PER_HEADER:
                del newest[next(iter(newest))]
        for provider_id, wire_id in newest.items():
            wire_ids.setdefault(provider_id, wire_id)
    if not wire_ids:
        return ()
    tag_queries(product=Product.MESSAGING, feature=Feature.QUERY)
    rows = cast(
        list,
        sync_execute(
            _SENT_MESSAGE_QUERY,
            {"team_id": team_id, "provider_message_ids": list(wire_ids)},
            # Without the index this reads every row the team sent in 31 days, so refuse to run rather than scan.
            settings={"force_data_skipping_indices": "provider_message_id_idx"},
            workload=Workload.OFFLINE,
            team_id=team_id,
        ),
    )
    return tuple(
        SentMessageMatch(wire_message_id=wire_ids[provider_id], send_id=str(send_id)) for provider_id, send_id in rows
    )
