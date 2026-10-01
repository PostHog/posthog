"""Where a table's query folder pointer has been, recorded on the schema's `sync_type_config`.

A leaf module (no deltalake, no pipeline imports): table registration writes the record after every
pointer flip, the publish step reads it to pick a standby slot, and the DuckLake registration reads
it to tell one generation on a fixed slot name from the next.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from posthog.dataclasses import frozen

# `sync_type_config` key: {<table prefix>: {"active": str, "active_since": iso, "active_job_id": str,
# "history_since": iso, "inactive_since": {<folder>: iso}}}, one entry per table under the schema
# (the snapshot table and a CDC companion have different prefixes).
QUERY_FOLDER_STATE_KEY = "query_folder_state"

# The fixed slots a table rotates through under the double-buffer flag. Three rather than two, so the
# slot being reconciled stopped being read one whole sync interval before the current slot took over,
# and a table synced more often than S3_DELETE_TIME_BUFFER still takes the incremental path. None of
# the names ends in digits, so the age-based cleanup of `__query_<digits>` folders never selects them.
QUERY_FOLDER_SLOTS = ("a", "b", "c")


def query_folder_table_prefix(queryable_folder: str) -> str:
    """`<table>__query`, shared by every query folder of one table: the slots, the timestamped
    folders and the legacy fixed folder."""
    return queryable_folder.rsplit("__query", 1)[0] + "__query"


def query_folder_slot_names(table_prefix: str) -> tuple[str, ...]:
    return tuple(f"{table_prefix}_{slot}" for slot in QUERY_FOLDER_SLOTS)


def _parse_instant(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@frozen
class QueryFolderPointerHistory:
    """The recorded pointer moves of one table's query folders."""

    active: str | None
    active_since: datetime | None
    active_job_id: str | None
    # Every pointer move since this instant was recorded, so a folder with no record was not the
    # pointer at any time after it.
    history_since: datetime | None
    # When each folder last stopped being the pointer.
    inactive_since: dict[str, datetime]

    @classmethod
    def from_config(cls, sync_type_config: Any, table_prefix: str) -> QueryFolderPointerHistory | None:
        if not isinstance(sync_type_config, dict):
            return None
        states = sync_type_config.get(QUERY_FOLDER_STATE_KEY)
        state = states.get(table_prefix) if isinstance(states, dict) else None
        if not isinstance(state, dict):
            return None
        raw_inactive = state.get("inactive_since")
        inactive_since: dict[str, datetime] = {}
        if isinstance(raw_inactive, dict):
            for folder, raw in raw_inactive.items():
                instant = _parse_instant(raw)
                if instant is not None:
                    inactive_since[str(folder)] = instant
        active = state.get("active")
        active_job_id = state.get("active_job_id")
        return cls(
            active=active if isinstance(active, str) else None,
            active_since=_parse_instant(state.get("active_since")),
            active_job_id=active_job_id if isinstance(active_job_id, str) else None,
            history_since=_parse_instant(state.get("history_since")),
            inactive_since=inactive_since,
        )

    def stopped_being_active(self, folder: str) -> datetime | None:
        """When `folder` last stopped being the pointer, or None when that is not known.

        A folder with no record has not been the pointer since `history_since`, so any read of it
        started before then.
        """
        if folder == self.active:
            return None
        recorded = self.inactive_since.get(folder)
        if recorded is not None:
            return recorded
        return self.history_since


def advance_query_folder_pointer(
    sync_type_config: dict[str, Any],
    *,
    previous_folder: str | None,
    queryable_folder: str,
    job_id: str,
    now: datetime | None = None,
) -> None:
    """Record, in place, that the pointer moved from `previous_folder` to `queryable_folder`.

    A `previous_folder` that is not the recorded active folder means a move this record missed (a
    crash between the pointer write and the record, or a reset that cleared the config), so
    `history_since` restarts: a slot with no record can then only be trusted as unread since now.
    Only the slots keep an `inactive_since` entry, because they are the only folders that get reused.
    """
    at = now or datetime.now(UTC)
    table_prefix = query_folder_table_prefix(queryable_folder)
    previous = QueryFolderPointerHistory.from_config(sync_type_config, table_prefix)

    contiguous = previous is not None and previous.active == previous_folder
    history_since = previous.history_since if contiguous and previous is not None else None
    inactive_since = dict(previous.inactive_since) if previous is not None else {}
    if previous_folder is not None and previous_folder != queryable_folder:
        inactive_since[previous_folder] = at
    inactive_since.pop(queryable_folder, None)
    slot_names = query_folder_slot_names(table_prefix)

    states = sync_type_config.get(QUERY_FOLDER_STATE_KEY)
    if not isinstance(states, dict):
        states = {}
    states[table_prefix] = {
        "active": queryable_folder,
        "active_since": at.isoformat(),
        "active_job_id": job_id,
        "history_since": (history_since or at).isoformat(),
        "inactive_since": {
            folder: instant.isoformat() for folder, instant in inactive_since.items() if folder in slot_names
        },
    }
    sync_type_config[QUERY_FOLDER_STATE_KEY] = states
