import re
from uuid import UUID

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.models import Team

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.managed_warehouse.backend.trino_model_aliases import (
    ModelAlias,
    ModelAliasPublisher,
    ModelAliasReconciliation,
    reconcile_trino_model_aliases,
)

MODEL_ID = UUID("12345678-1234-5678-1234-567812345678")
OTHER_ID = UUID("abcdefab-1234-5678-1234-567812345678")
TABLE = f"model_{MODEL_ID.hex}"
SCHEMA = '"catalog"."posthog_data_modeling_team_42"'


def reconcile(
    models: list[ModelAlias],
    *,
    relations: list[tuple[str, str]] | None = None,
    comments: list[tuple[str, str]] | None = None,
    columns: list[tuple[str, str, str]] | None = None,
) -> tuple[MagicMock, ModelAliasReconciliation]:
    cursor = MagicMock()
    cursor.fetchall.side_effect = [
        relations if relations is not None else [(TABLE, "BASE TABLE")],
        comments or [],
        columns if columns is not None else [(TABLE, "amount", "bigint")],
        *([[]] * 10),
    ]
    result = ModelAliasPublisher(cursor, "catalog", 42, lambda: None).reconcile(models)
    return cursor, result


def alias(name: str = "daily_revenue") -> ModelAlias:
    return ModelAlias(saved_query_id=MODEL_ID, name=name, table_name=TABLE)


def published_comment() -> str:
    cursor, _ = reconcile([alias()])
    match = re.search("COMMENT '([^']+)'", cursor.execute.call_args_list[-1].args[0])
    assert match
    return match.group(1)


@pytest.mark.parametrize("name", ["daily_revenue", 'reporting.daily_"revenue', "select"])
def test_publishes_quoted_invoker_view_without_rewriting_physical_tables(name: str) -> None:
    cursor, result = reconcile([alias(name)])
    sql = cursor.execute.call_args_list[-1].args[0]
    escaped = name.replace('"', '""')
    assert sql.startswith(f'CREATE VIEW {SCHEMA}."{escaped}" COMMENT ')
    assert sql.endswith(f'SECURITY INVOKER AS SELECT * FROM {SCHEMA}."{TABLE}"')
    assert result.published == 1
    assert result.errors == ()


@pytest.mark.parametrize("change", ["none", "columns", "rename", "delete", "missing_table"])
def test_reconciles_published_alias_lifecycle(change: str) -> None:
    models = [] if change == "delete" else [alias("daily_sales" if change == "rename" else "daily_revenue")]
    relations = [(TABLE, "BASE TABLE"), ("daily_revenue", "VIEW")]
    if change == "missing_table":
        relations = [("daily_revenue", "VIEW")]
    cursor, result = reconcile(
        models,
        relations=relations,
        comments=[("daily_revenue", published_comment())],
        columns=[(TABLE, "amount", "double" if change == "columns" else "bigint")],
    )
    statements = [call.args[0] for call in cursor.execute.call_args_list[3:]]
    if change == "none":
        assert statements == []
        assert result.unchanged == 1
    elif change == "columns":
        assert len(statements) == 1
        assert statements[0].startswith(f'CREATE OR REPLACE VIEW {SCHEMA}."daily_revenue" ')
    else:
        assert statements[0] == f'DROP VIEW IF EXISTS {SCHEMA}."daily_revenue"'
        assert result.removed == 1
        if change == "rename":
            assert statements[1].startswith(f'CREATE VIEW {SCHEMA}."daily_sales" ')
        else:
            assert len(statements) == 1


@pytest.mark.parametrize("conflict", ["table", "view", "other_team", "duplicate", "reserved_physical"])
def test_does_not_overwrite_conflicting_relations(conflict: str) -> None:
    models = [alias()]
    relations = [(TABLE, "BASE TABLE")]
    comments = []
    if conflict in {"table", "view", "other_team"}:
        relations.append(("daily_revenue", "BASE TABLE" if conflict == "table" else "VIEW"))
        comments = [("daily_revenue", "posthog:model-alias:99:unrelated")]
    else:
        models.append(
            ModelAlias(
                saved_query_id=OTHER_ID,
                name="daily_revenue" if conflict == "duplicate" else "other_model",
                table_name="other_table" if conflict == "duplicate" else "daily_revenue",
            )
        )
    cursor, result = reconcile(models, relations=relations, comments=comments)
    assert len(cursor.execute.call_args_list) == 3
    assert result.errors
    assert result.published == 0


def test_legacy_physical_name_already_serves_as_logical_name() -> None:
    cursor, result = reconcile([alias(TABLE)])
    assert len(cursor.execute.call_args_list) == 3
    assert result.errors == ()


class TestModelAliasScoping(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(
            patch("products.managed_warehouse.backend.trino_model_aliases.is_dev_mode", return_value=False)
        )

    def test_reconciles_only_live_materialized_models_for_the_requested_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        DataWarehouseSavedQuery.objects.create(
            team=other_team, name="Reporting.Orders", query={"query": "SELECT 1"}, is_materialized=True
        )
        DataWarehouseSavedQuery.objects.create(
            id=MODEL_ID, team=self.team, name="Reporting.Orders", query={"query": "SELECT 1"}, is_materialized=True
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team, name="deleted", query={"query": "SELECT 1"}, is_materialized=True, deleted=True
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team, name="ephemeral", query={"query": "SELECT 1"}, is_materialized=False
        )
        with (
            patch("products.managed_warehouse.backend.trino_model_aliases.connect_managed_warehouse_trino") as connect,
            patch.object(ModelAliasPublisher, "reconcile") as publish,
            patch("posthog.ph_client.feature_enabled_or_false", return_value=True),
        ):
            reconcile_trino_model_aliases(self.team.pk, lambda: None)
        connect.assert_called_once_with(str(self.organization.id))
        publish.assert_called_once_with([alias("reporting.orders")], None)
        connect.return_value.__enter__.return_value.cursor.return_value.execute.assert_not_called()

    def test_disabled_team_stops_before_connecting(self) -> None:
        with (
            patch("posthog.ph_client.feature_enabled_or_false", return_value=False),
            patch("products.managed_warehouse.backend.trino_model_aliases.connect_managed_warehouse_trino") as connect,
        ):
            assert reconcile_trino_model_aliases(self.team.pk, lambda: None) == ModelAliasReconciliation(active=False)
        connect.assert_not_called()

    def test_empty_team_cleans_up_owned_aliases_then_stops(self) -> None:
        with (
            patch("posthog.ph_client.feature_enabled_or_false", return_value=True),
            patch("products.managed_warehouse.backend.trino_model_aliases.connect_managed_warehouse_trino") as connect,
        ):
            cursor = connect.return_value.__enter__.return_value.cursor.return_value
            cursor.fetchall.side_effect = [
                [("old_alias", "VIEW")],
                [("old_alias", f"posthog:model-alias:{self.team.pk}:old")],
                [],
                [],
            ]
            assert reconcile_trino_model_aliases(self.team.pk, lambda: None) == ModelAliasReconciliation(
                removed=1, active=False
            )
            assert cursor.execute.call_args_list[-1].args[0].endswith('."old_alias"')
            assert cursor.execute.call_args_list[-1].args[0].startswith("DROP VIEW IF EXISTS ")


@pytest.mark.parametrize("exists", [False, True])
def test_targeted_refresh_reads_only_requested_metadata_and_leaves_other_aliases(exists: bool) -> None:
    cursor = MagicMock()
    cursor.fetchall.side_effect = [
        [(TABLE, "BASE TABLE"), *(([("daily_revenue", "VIEW")]) if exists else [])],
        *([[("daily_revenue", published_comment())]] if exists else []),
        [("amount", "bigint", "", "")],
        [],
    ]
    result = ModelAliasPublisher(cursor, "catalog", 42, lambda: None).reconcile(
        [alias(), ModelAlias(saved_query_id=OTHER_ID, name="unrelated", table_name="other_table")], (str(MODEL_ID),)
    )
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert cursor.execute.call_args_list[0].args[1] == ["posthog_data_modeling_team_42", "daily_revenue", TABLE]
    assert not any("information_schema.columns" in sql or "DROP VIEW" in sql for sql in statements)
    assert f'SHOW COLUMNS FROM {SCHEMA}."{TABLE}"' in statements
    assert (
        result == ModelAliasReconciliation(unchanged=1) if exists else result == ModelAliasReconciliation(published=1)
    )
