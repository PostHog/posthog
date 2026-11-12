from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from posthog.hogql.direct_sql.trino_adapter import bounded_trino_cursor
from posthog.hogql.escape_sql import escape_trino_identifier
from posthog.hogql.transforms.trino.manifest import TrinoManifestColumn, TrinoManifestTable, is_manifest_column_type

from posthog.schema_enums import DatabaseSerializedFieldType

from products.managed_warehouse.backend.logic.sql_editor_trino import MANAGED_TRINO_SCHEMA_DISCOVERY_TIMEOUT_SECONDS
from products.managed_warehouse.backend.trino_compiler import ExternalCatalogTableLookup
from products.managed_warehouse.backend.trino_connection import connect_managed_warehouse_trino
from products.warehouse_sources.backend.facade.models import trino_column_to_dwh_column

if TYPE_CHECKING:
    from trino.dbapi import Cursor

    from posthog.hogql.database.trino_locator import TrinoTableLocator

    from posthog.models import Team, User


def discover_external_catalog_tables(cursor: Cursor, locators: Sequence[TrinoTableLocator]) -> list[TrinoManifestTable]:
    """Read the columns of each table from its catalog's information_schema.

    A table the credential cannot see has no rows there, so it is left out, the same as a missing one.
    """
    from trino.exceptions import TrinoQueryError  # noqa: PLC0415 -- keeps the optional driver off startup paths

    by_catalog: dict[str, list[TrinoTableLocator]] = {}
    for locator in locators:
        by_catalog.setdefault(locator[0], []).append(locator)

    columns: dict[TrinoTableLocator, list[TrinoManifestColumn]] = {}
    for catalog, catalog_locators in by_catalog.items():
        predicate = " OR ".join("(table_schema = ? AND table_name = ?)" for _ in catalog_locators)
        try:
            cursor.execute(
                "SELECT table_schema, table_name, column_name, data_type, is_nullable "
                f"FROM {escape_trino_identifier(catalog)}.information_schema.columns "
                f"WHERE {predicate} ORDER BY table_schema, table_name, ordinal_position",
                [part for locator in catalog_locators for part in locator[1:]],
            )
            rows = cursor.fetchall()
        except TrinoQueryError:
            # An unknown catalog and a catalog the credential may not read fail the same way.
            continue
        for schema, table, column_name, data_type, is_nullable in rows:
            nullable = str(is_nullable).upper() == "YES"
            label = trino_column_to_dwh_column(str(column_name), str(data_type), nullable)["hogql"]
            columns.setdefault((catalog, str(schema), str(table)), []).append(
                TrinoManifestColumn(name=str(column_name), type=_column_type(label), nullable=nullable)
            )
    return [
        TrinoManifestTable(logical_name=".".join(locator), locator=locator, columns=tuple(table_columns))
        for locator, table_columns in columns.items()
    ]


def _column_type(label: str) -> DatabaseSerializedFieldType:
    # The warehouse labels a decimal column "numeric", which is not a serialized field type.
    if label == "numeric":
        return DatabaseSerializedFieldType.DECIMAL
    try:
        column_type = DatabaseSerializedFieldType(label)
    except ValueError:
        return DatabaseSerializedFieldType.UNKNOWN
    return column_type if is_manifest_column_type(column_type) else DatabaseSerializedFieldType.UNKNOWN


def external_catalog_lookup(team: Team, user: User, *, canary: bool) -> ExternalCatalogTableLookup:
    def lookup(locators: Sequence[TrinoTableLocator]) -> list[TrinoManifestTable]:
        with connect_managed_warehouse_trino(
            str(team.organization_id),
            principal=f"posthog:sql-editor:team:{team.pk}:user:{user.pk}",
            canary=canary,
        ) as connection:
            with bounded_trino_cursor(connection, MANAGED_TRINO_SCHEMA_DISCOVERY_TIMEOUT_SECONDS, team_id=team.pk) as (
                cursor,
                watchdog,
            ):
                tables = discover_external_catalog_tables(cursor, locators)
                watchdog.check()
        return tables

    return lookup
