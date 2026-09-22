from __future__ import annotations

import json
import hashlib
from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING, cast
from uuid import UUID

from posthog.hogql.escape_sql import escape_trino_identifier

from posthog.dataclasses import frozen

from products.managed_warehouse.backend.common import ducklake_data_modeling_schema
from products.managed_warehouse.backend.table_binding import get_data_modeling_table_names
from products.managed_warehouse.backend.trino_connection import connect_managed_warehouse_trino

if TYPE_CHECKING:
    from trino.dbapi import Cursor


@frozen
class ModelAlias:
    saved_query_id: UUID
    name: str
    table_name: str


@frozen
class ModelAliasReconciliation:
    published: int = 0
    removed: int = 0
    unchanged: int = 0
    errors: tuple[str, ...] = ()


def _load_models(team_id: int) -> list[ModelAlias]:
    from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

    models = list(
        DataWarehouseSavedQuery.objects.filter(team_id=team_id, is_materialized=True)
        .exclude(deleted=True)
        .values_list("id", "name")
    )
    tables = get_data_modeling_table_names(team_id, [query_id for query_id, _ in models])
    return [
        ModelAlias(saved_query_id=query_id, name=name.lower(), table_name=tables[query_id]) for query_id, name in models
    ]


class ModelAliasPublisher:
    def __init__(self, cursor: Cursor, catalog: str, team_id: int, checkpoint: Callable[[], None]) -> None:
        self.cursor = cursor
        self.catalog = catalog
        self.team_id = team_id
        self.schema_name = ducklake_data_modeling_schema(team_id)
        self.schema = f"{escape_trino_identifier(catalog)}.{escape_trino_identifier(self.schema_name)}"
        self.owner_prefix = f"posthog:model-alias:{team_id}:"
        self.checkpoint = checkpoint

    def _execute(self, sql: str, parameters: list[str] | None = None) -> list[tuple[str, ...]]:
        self.checkpoint()
        self.cursor.execute(sql, parameters)
        return cast(list[tuple[str, ...]], self.cursor.fetchall())

    def _owned_views(self) -> dict[str, str]:
        rows = self._execute(
            "SELECT table_name, comment FROM system.metadata.table_comments WHERE catalog_name = ? AND schema_name = ?",
            [self.catalog, self.schema_name],
        )
        return {name: comment for name, comment in rows if comment and comment.startswith(self.owner_prefix)}

    def reconcile(self, models: list[ModelAlias]) -> ModelAliasReconciliation:
        relations = {
            row[0]: row[1]
            for row in self._execute(
                f"SELECT table_name, table_type FROM {escape_trino_identifier(self.catalog)}.information_schema.tables "
                "WHERE table_schema = ?",
                [self.schema_name],
            )
        }
        if not relations:
            return ModelAliasReconciliation()

        owned = {name: comment for name, comment in self._owned_views().items() if relations.get(name) == "VIEW"}
        columns: dict[str, list[tuple[str, str]]] = {}
        for table, column, data_type in self._execute(
            f"SELECT table_name, column_name, data_type FROM {escape_trino_identifier(self.catalog)}.information_schema.columns "
            "WHERE table_schema = ? ORDER BY table_name, ordinal_position",
            [self.schema_name],
        ):
            columns.setdefault(table, []).append((column, data_type))

        counts = Counter(model.name for model in models)
        physical_counts = Counter(model.table_name for model in models)
        desired: dict[str, tuple[ModelAlias, str]] = {}
        errors: list[str] = []
        for model in models:
            if counts[model.name] > 1 or physical_counts[model.table_name] > 1:
                errors.append(f"{model.saved_query_id}: model names collide; rename the conflicting model")
                continue
            if relations.get(model.table_name) != "BASE TABLE":
                continue
            if model.name == model.table_name:
                continue
            if model.name in physical_counts or (model.name in relations and model.name not in owned):
                errors.append(f"{model.saved_query_id}: alias conflicts with an existing relation; choose another name")
                continue
            fingerprint = hashlib.sha256(
                json.dumps([model.table_name, columns.get(model.table_name, [])]).encode()
            ).hexdigest()
            desired[model.name] = (model, f"{self.owner_prefix}{model.saved_query_id}:{fingerprint}")

        removed = 0
        for name in owned.keys() - desired.keys():
            self._execute(f"DROP VIEW IF EXISTS {self.schema}.{escape_trino_identifier(name)}")
            removed += 1

        published = unchanged = 0
        for name, (model, comment) in desired.items():
            if owned.get(name) == comment:
                unchanged += 1
                continue
            # The comment contains only generated IDs/hash; names are quoted as single identifiers.
            replace = "OR REPLACE " if name in owned else ""
            self._execute(
                f"CREATE {replace}VIEW {self.schema}.{escape_trino_identifier(name)} "
                f"COMMENT '{comment}' SECURITY INVOKER AS "
                f"SELECT * FROM {self.schema}.{escape_trino_identifier(model.table_name)}"
            )
            published += 1

        return ModelAliasReconciliation(
            published=published, removed=removed, unchanged=unchanged, errors=tuple(errors[:50])
        )


def reconcile_trino_model_aliases(team_id: int, checkpoint: Callable[[], None]) -> ModelAliasReconciliation:
    from posthog.models import Team

    organization_id = Team.objects.values_list("organization_id", flat=True).get(pk=team_id)
    with connect_managed_warehouse_trino(str(organization_id)) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute("SET SESSION query_max_run_time = '30s'")
            cursor.fetchall()
            publisher = ModelAliasPublisher(cursor, connection.catalog, team_id, checkpoint)
            return publisher.reconcile(_load_models(team_id))
        finally:
            cursor.close()
