"""Copies the ee definition columns to the team-scoped metadata tables.

The ee tables stay the source of truth until reads move to the metadata tables. Until then, every
save of an ee row copies it here once the save commits, and the `backfill_definition_metadata`
command copies the rows that were saved before. The copy reads the definition tables only by primary
key, for the team_id, and never writes or locks them.
"""

from collections.abc import Sequence
from dataclasses import dataclass
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
        # of an older save never lands after the copy of a newer one. It locks the ee rows only.
        # The IS DISTINCT FROM check skips unchanged rows, so the row count of a rerun shows the drift.
        return f"""
            INSERT INTO {self.metadata_table} AS metadata ({self.link_column}, team_id, {insert_columns})
            SELECT ee.{self.enterprise_link_column}, definition.team_id, {select_columns}
            FROM {self.enterprise_table} ee
            JOIN {self.definition_table} definition ON definition.id = ee.{self.enterprise_link_column}
            WHERE ee.{self.enterprise_link_column} = ANY(%s::uuid[])
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


def copy_definition_metadata_on_commit(kind: DefinitionKind, definition_id: UUID | str) -> None:
    """Copy one ee row once its save commits.

    After the commit, the save no longer holds its lock on the definition row, so ingestion never
    waits for the copy. A failed copy must not fail the edit, because the ee row is still the source
    of truth and the backfill repairs the copy.
    """
    transaction.on_commit(lambda: _copy_and_log_failure(kind, definition_id))


def _copy_and_log_failure(kind: DefinitionKind, definition_id: UUID | str) -> None:
    try:
        # The atomic block keeps a failed statement out of an enclosing transaction, as in tests
        with transaction.atomic():
            copy_definition_metadata(kind, [definition_id])
    except Exception as error:
        logger.exception("definition_metadata_copy_failed", kind=kind, definition_id=str(definition_id))
        capture_exception(error)


def next_enterprise_definition_ids(kind: DefinitionKind, *, after: str | None, limit: int) -> list[str]:
    """The ids of the ee rows after `after`, in id order, for a resumable backfill."""
    with connection.cursor() as cursor:
        cursor.execute(_COPIES[kind].next_ids_sql(), [after, after, limit])
        return [str(row[0]) for row in cursor.fetchall()]
