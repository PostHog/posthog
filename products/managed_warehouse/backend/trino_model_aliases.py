from __future__ import annotations

import os
import re
import json
import hashlib
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING, cast
from uuid import UUID

from posthog.hogql.escape_sql import escape_trino_identifier

from posthog.dataclasses import frozen

from products.managed_warehouse.backend.common import ducklake_data_modeling_schema, is_dev_mode
from products.managed_warehouse.backend.table_binding import get_data_modeling_table_names
from products.managed_warehouse.backend.trino_connection import connect_managed_warehouse_trino

if TYPE_CHECKING:
    from trino.dbapi import Cursor

    from products.managed_warehouse.backend.trino_execution import TrinoQueryControl


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
    active: bool = True


def _load_models(team_id: int, saved_query_ids: tuple[str, ...] | None = None) -> list[ModelAlias]:
    from django.db.models.functions import Lower

    from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

    queryset = DataWarehouseSavedQuery.objects.filter(team_id=team_id, is_materialized=True).exclude(deleted=True)
    if saved_query_ids is not None:
        names = list(
            queryset.filter(id__in=saved_query_ids)
            .annotate(alias_name=Lower("name"))
            .values_list("alias_name", flat=True)
        )
        queryset = queryset.annotate(alias_name=Lower("name")).filter(alias_name__in=names)
    models = list(queryset.values_list("id", "name"))
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

    def _owned_views(self, names: set[str] | None) -> dict[str, str]:
        owned: dict[str, str] = {}
        if names is None:
            return {
                name: comment
                for name, comment in self._execute(
                    "SELECT table_name, comment FROM system.metadata.table_comments WHERE catalog_name = ? AND schema_name = ?",
                    [self.catalog, self.schema_name],
                )
                if comment and comment.startswith(self.owner_prefix)
            }
        # Exact table predicates use Trino's point lookup; a schema-wide comments query loads every table's metadata.
        for name in sorted(names):
            for view_name, comment in self._execute(
                "SELECT table_name, comment FROM system.metadata.table_comments "
                "WHERE catalog_name = ? AND schema_name = ? AND table_name = ?",
                [self.catalog, self.schema_name, name],
            ):
                if comment and comment.startswith(self.owner_prefix):
                    owned[view_name] = comment
        return owned

    def reconcile(
        self, models: list[ModelAlias], saved_query_ids: tuple[str, ...] | None = None
    ) -> ModelAliasReconciliation:
        selected = (
            models
            if saved_query_ids is None
            else [model for model in models if str(model.saved_query_id) in saved_query_ids]
        )
        target_names = {name for model in selected for name in (model.name, model.table_name)}
        name_filter = (
            "" if saved_query_ids is None else " AND table_name IN (" + ",".join("?" for _ in target_names) + ")"
        )
        if saved_query_ids is not None and not target_names:
            return ModelAliasReconciliation()
        relations = {
            row[0]: row[1]
            for row in self._execute(
                f"SELECT table_name, table_type FROM {escape_trino_identifier(self.catalog)}.information_schema.tables "
                f"WHERE table_schema = ?{name_filter}",
                [self.schema_name, *sorted(target_names)] if saved_query_ids is not None else [self.schema_name],
            )
        }
        if not relations:
            return ModelAliasReconciliation()

        owned = {
            name: comment
            for name, comment in self._owned_views(
                None if saved_query_ids is None else {name for name, kind in relations.items() if kind == "VIEW"}
            ).items()
            if relations.get(name) == "VIEW"
        }
        columns: dict[str, list[tuple[str, str]]] = {}
        if saved_query_ids is None:
            for table, column, data_type in self._execute(
                f"SELECT table_name, column_name, data_type FROM {escape_trino_identifier(self.catalog)}.information_schema.columns "
                "WHERE table_schema = ? ORDER BY table_name, ordinal_position",
                [self.schema_name],
            ):
                columns.setdefault(table, []).append((column, data_type))
        else:
            for model in selected:
                if relations.get(model.table_name) != "BASE TABLE":
                    continue
                columns[model.table_name] = [
                    (row[0], row[1])
                    for row in self._execute(
                        f"SHOW COLUMNS FROM {self.schema}.{escape_trino_identifier(model.table_name)}"
                    )
                ]

        counts = Counter(model.name for model in models)
        physical_counts = Counter(model.table_name for model in models)
        desired: dict[str, tuple[ModelAlias, str]] = {}
        errors: list[str] = []
        for model in selected:
            if counts[model.name] > 1 or physical_counts[model.table_name] > 1:
                errors.append(f"{model.saved_query_id}: model names collide; rename the conflicting model")
                continue
            if relations.get(model.table_name) != "BASE TABLE":
                continue
            if model.name == model.table_name:
                continue
            if (
                re.fullmatch(r"model_[0-9a-f]{32}", model.name)
                or model.name in physical_counts
                or (model.name in relations and model.name not in owned)
            ):
                errors.append(f"{model.saved_query_id}: alias conflicts with an existing relation; choose another name")
                continue
            fingerprint = hashlib.sha256(
                json.dumps([model.table_name, columns.get(model.table_name, [])]).encode()
            ).hexdigest()
            desired[model.name] = (model, f"{self.owner_prefix}{model.saved_query_id}:{fingerprint}")

        removed = 0
        stale = owned.keys() - desired.keys() if saved_query_ids is None else set()
        for name in stale:
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


def reconcile_trino_model_aliases(
    team_id: int,
    checkpoint: Callable[[], None],
    saved_query_ids: tuple[str, ...] | None = None,
    control: TrinoQueryControl | None = None,
) -> ModelAliasReconciliation:
    from posthog.models import Team
    from posthog.ph_client import feature_enabled_or_false

    from products.managed_warehouse.backend.facade.feature_flags import DATA_MODELING_SHADOW_FLAG

    organization_id = Team.objects.filter(pk=team_id).values_list("organization_id", flat=True).first()
    if organization_id is None:
        return ModelAliasReconciliation(active=False)
    enabled = (
        (os.environ.get("MANAGED_WAREHOUSE_SHADOW_ENABLED", "").lower() in ("1", "true"))
        if is_dev_mode()
        else feature_enabled_or_false(
            DATA_MODELING_SHADOW_FLAG,
            str(team_id),
            groups={"organization": str(organization_id), "project": str(team_id)},
            group_properties={"organization": {"id": str(organization_id)}, "project": {"id": str(team_id)}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    )
    if not enabled:
        return ModelAliasReconciliation(active=False)
    models = _load_models(team_id, saved_query_ids)
    with connect_managed_warehouse_trino(str(organization_id)) as connection:
        cursor = connection.cursor()
        if control:
            control.attach(cursor)
        try:
            checkpoint()
            cursor.execute("SET SESSION query_max_run_time = '30s'")
            cursor.fetchall()
            publisher = ModelAliasPublisher(cursor, connection.catalog, team_id, checkpoint)
            result = publisher.reconcile(models, saved_query_ids)
            if saved_query_ids is None and not models:
                return replace(result, active=False)
            return result
        finally:
            cursor.close()
