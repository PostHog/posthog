"""Webhook rows as events, for a table that keeps history: one row per event, with the event columns.

A source declares how to read its staged rows in `WebhookSource.webhook_events`. With history off, the
source's own transformer keeps the newest row per key, as before.
"""

import hashlib
import datetime
from collections.abc import Callable, Sequence
from typing import Any

import orjson
import pyarrow as pa

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_event_columns import (
    ARRIVAL_COLUMN,
    EVENT_ID_COLUMN,
    EVENT_RANK_COLUMN,
    EVENT_TIME_COLUMN,
    WEBHOOK_EVENT_COLUMNS,
    WEBHOOK_EVENT_ORDER,
)

# A hash of each staged payload as delivered. Arrow later adds null fields that other rows of the batch carry,
# so a hash of the row would differ between two batches that hold the same delivery.
PAYLOAD_HASH_COLUMN = "_ph_payload_hash"
_STAGING_COLUMNS = frozenset((*WEBHOOK_EVENT_COLUMNS, PAYLOAD_HASH_COLUMN))


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(orjson.dumps(payload, option=orjson.OPT_SORT_KEYS | orjson.OPT_NON_STR_KEYS)).hexdigest()


@frozen
class WebhookEvent:
    row: dict[str, Any]
    time: datetime.datetime | None
    event_id: str | None = None
    rank: int = 0


@frozen
class WebhookEvents:
    """How one table's staged webhook rows become events."""

    read: Callable[[dict[str, Any]], WebhookEvent | None]
    # Adds back what the event payloads leave out, for the kept rows in order.
    complete: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None


def _order(time: Any, rank: Any, arrival: Any) -> tuple[Any, ...]:
    # An event without a time sorts first, and the flag keeps None from being compared with a time.
    return (time is not None, time, rank or 0, arrival or "")


def _utc(time: datetime.datetime | None) -> datetime.datetime | None:
    if time is None:
        return None
    return time.replace(tzinfo=datetime.UTC) if time.tzinfo is None else time.astimezone(datetime.UTC)


def event_rows(table: pa.Table, events: WebhookEvents) -> list[dict[str, Any]]:
    """Every event of a staged batch as a row with the event columns, oldest first, without redeliveries."""
    rows: dict[str, dict[str, Any]] = {}
    for staged in table.to_pylist():
        event = events.read(staged)
        if event is None:
            continue
        row = {name: value for name, value in event.row.items() if name not in _STAGING_COLUMNS}
        time = _utc(event.time)
        # A redelivery of an event without an id has the same payload, which holds its key and change time.
        event_id = event.event_id or f"sha256:{staged[PAYLOAD_HASH_COLUMN]}"
        if event_id in rows:
            continue
        rows[event_id] = {
            **row,
            EVENT_ID_COLUMN: event_id,
            EVENT_TIME_COLUMN: time,
            EVENT_RANK_COLUMN: event.rank,
            ARRIVAL_COLUMN: staged.get(ARRIVAL_COLUMN),
        }

    ordered = sorted(rows.values(), key=lambda row: _order(*(row[name] for name in WEBHOOK_EVENT_ORDER)))
    if events.complete is None or not ordered:
        return ordered
    # `complete` can return objects it read again, so the event columns are put back on each one.
    return [
        {**completed, **{name: row[name] for name in WEBHOOK_EVENT_COLUMNS}}
        for row, completed in zip(ordered, events.complete(ordered), strict=True)
    ]


def every_event_transformer(events: WebhookEvents) -> Callable[[pa.Table], pa.Table]:
    return lambda table: table_from_py_list(event_rows(table, events))


def latest_event_per_key(table: pa.Table, primary_keys: Sequence[str]) -> pa.Table:
    """The newest event of each key by `WEBHOOK_EVENT_ORDER`, which a table with history keeps as its current row."""
    if table.num_rows == 0:
        return table
    keys = list(zip(*(table.column(key).to_pylist() for key in primary_keys)))
    orders = [_order(*values) for values in zip(*(table.column(name).to_pylist() for name in WEBHOOK_EVENT_ORDER))]
    newest: dict[tuple[Any, ...], int] = {}
    for index, key in enumerate(keys):
        best = newest.get(key)
        if best is None or orders[index] > orders[best]:
            newest[key] = index
    return table.take(pa.array(sorted(newest.values()), type=pa.int64()))
