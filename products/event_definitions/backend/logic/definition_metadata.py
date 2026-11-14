"""Copies the ee definition columns to the team-scoped metadata tables.

The ee tables stay the source of truth until reads move to the metadata tables. Until then, every
save of an ee row copies it here once the save commits, and the `backfill_definition_metadata`
command copies the rows that were saved before. The copy reads the definition tables only by primary
key, for the team_id, and never writes or locks them.
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import partial
from typing import Literal
from uuid import UUID

from django.db import connection, transaction

import structlog

from posthog.exceptions_capture import capture_exception

from products.event_definitions.backend.models import EventDefinitionMetadata, PropertyDefinitionMetadata

logger = structlog.get_logger(__name__)

DefinitionKind = Literal["event", "property"]

_SHARED_COLUMNS = (
    "description",
    "updated_at",
    "updated_by_id",
    "verified",
    "verified_at",
    "verified_by_id",
    "hidden",
)


@dataclass(frozen=True)
class _MetadataCopy:
    metadata_table: str
    link_column: str
    enterprise_table: str
    enterprise_link_column: str
    definition_table: str
    columns: tuple[str, ...]

    def copy_sql(self) -> str:
        insert_columns = ", ".join(self.columns)
        select_columns = ", ".join(f"ee.{column}" for column in self.columns)
        written = ("team_id", *self.columns)
        updates = ", ".join(f"{column} = EXCLUDED.{column}" for column in written)
        current = ", ".join(f"metadata.{column}" for column in written)
        incoming = ", ".join(f"EXCLUDED.{column}" for column in written)
        # FOR SHARE makes a save of one of these ee rows wait until this statement commits, so the copy
        # of an older save never lands after the copy of a newer one. It locks the ee rows only, in id
        # order: a bulk edit saves in id order too, so the two never wait on each other in a cycle.
        # The IS DISTINCT FROM check skips unchanged rows, so the row count of a rerun shows the drift.
        return f"""
            INSERT INTO {self.metadata_table} AS metadata ({self.link_column}, team_id, {insert_columns})
            SELECT ee.{self.enterprise_link_column}, definition.team_id, {select_columns}
            FROM {self.enterprise_table} ee
            JOIN {self.definition_table} definition ON definition.id = ee.{self.enterprise_link_column}
            WHERE ee.{self.enterprise_link_column} = ANY(%s::uuid[])
            ORDER BY ee.{self.enterprise_link_column}
            FOR SHARE OF ee
            ON CONFLICT ({self.link_column}) DO UPDATE SET {updates}
            WHERE ({current}) IS DISTINCT FROM ({incoming})
        """

    def next_ids_sql(self) -> str:
        return f"""
            SELECT {self.enterprise_link_column} FROM {self.enterprise_table}
            WHERE %s::uuid IS NULL OR {self.enterprise_link_column} > %s::uuid
            ORDER BY {self.enterprise_link_column}
            LIMIT %s
        """


_COPIES: dict[DefinitionKind, _MetadataCopy] = {
    "event": _MetadataCopy(
        metadata_table=EventDefinitionMetadata._meta.db_table,
        link_column="event_definition_id",
        enterprise_table="ee_enterpriseeventdefinition",
        enterprise_link_column="eventdefinition_ptr_id",
        definition_table="posthog_eventdefinition",
        columns=(*_SHARED_COLUMNS, "owner_id", "default_columns"),
    ),
    "property": _MetadataCopy(
        metadata_table=PropertyDefinitionMetadata._meta.db_table,
        link_column="property_definition_id",
        enterprise_table="ee_enterprisepropertydefinition",
        enterprise_link_column="propertydefinition_ptr_id",
        definition_table="posthog_propertydefinition",
        columns=_SHARED_COLUMNS,
    ),
}


def copy_definition_metadata(kind: DefinitionKind, definition_ids: Sequence[UUID | str]) -> int:
    """Copy the ee rows of these definitions to the metadata table. Returns the number of rows that changed."""
    if not definition_ids:
        return 0
    with connection.cursor() as cursor:
        cursor.execute(_COPIES[kind].copy_sql(), [[str(definition_id) for definition_id in definition_ids]])
        return cursor.rowcount


# The ids that saves collect inside `batch_definition_metadata_copies`, by kind
_batched_copies: ContextVar[dict[DefinitionKind, list[str]] | None] = ContextVar(
    "definition_metadata_batched_copies", default=None
)


def copy_definition_metadata_on_commit(kind: DefinitionKind, definition_id: UUID | str) -> None:
    """Copy one ee row once its save commits.

    After the commit, the save no longer holds its lock on the definition row, so ingestion never
    waits for the copy. A failed copy must not fail the edit, because the ee row is still the source
    of truth and the backfill repairs the copy.
    """
    batch = _batched_copies.get()
    if batch is not None:
        batch.setdefault(kind, []).append(str(definition_id))
        return
    transaction.on_commit(partial(_copy_and_log_failure, kind, [definition_id]))


@contextmanager
def batch_definition_metadata_copies() -> Iterator[None]:
    """Copy the definitions saved in this block in one statement per kind, not one per save.

    Use it inside the transaction of a bulk edit: the copy runs when that transaction commits. A save
    that rolls back to a savepoint leaves its id in the batch, which is safe, because the copy reads
    the committed ee row.
    """
    batch: dict[DefinitionKind, list[str]] = {}
    token = _batched_copies.set(batch)
    try:
        yield
    finally:
        _batched_copies.reset(token)
    for kind, definition_ids in batch.items():
        transaction.on_commit(partial(_copy_and_log_failure, kind, definition_ids))


def _copy_and_log_failure(kind: DefinitionKind, definition_ids: Sequence[UUID | str]) -> None:
    try:
        # The atomic block keeps a failed statement out of an enclosing transaction, as in tests
        with transaction.atomic():
            copy_definition_metadata(kind, definition_ids)
    except Exception as error:
        logger.exception(
            "definition_metadata_copy_failed",
            kind=kind,
            definition_count=len(definition_ids),
            first_definition_id=str(definition_ids[0]),
        )
        capture_exception(error)


def next_enterprise_definition_ids(kind: DefinitionKind, *, after: str | None, limit: int) -> list[str]:
    """The ids of the ee rows after `after`, in id order, for a resumable backfill."""
    with connection.cursor() as cursor:
        cursor.execute(_COPIES[kind].next_ids_sql(), [after, after, limit])
        return [str(row[0]) for row in cursor.fetchall()]
