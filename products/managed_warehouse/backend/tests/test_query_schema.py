from contextlib import nullcontext
from uuid import UUID

import pytest
from unittest.mock import MagicMock, PropertyMock, patch

from posthog.schema import DatabaseSchemaQuery

from posthog.hogql.errors import ExposedHogQLError

from posthog.api.services.query import process_database_schema_query
from posthog.clickhouse.query_tagging import AccessMethod, QueryTags
from posthog.exceptions import DatabaseSchemaUnavailable
from posthog.models import Team, User


@pytest.mark.parametrize("include_fields,table_names", [(False, None), (True, None), (True, ["analytics.orders"])])
def test_native_schema_uses_warehouse_inventory(include_fields: bool, table_names: list[str] | None) -> None:
    team = Team(id=7, organization_id=UUID("00000000-0000-0000-0000-000000000001"))
    user = User(id=9)
    cursor = MagicMock()
    cursor.fetchall.side_effect = [
        [("analytics", "orders"), ("posthog", "events_example")],
        [("analytics", "orders", "order id", "bigint", "NO")],
        [("posthog", "events_example", "event", "varchar", "YES")],
    ]
    connection = MagicMock(catalog="example_catalog")
    connection.cursor.return_value = cursor
    with (
        patch("posthoganalytics.feature_enabled", return_value=True),
        patch("products.managed_warehouse.backend.query_execution.get_query_tags", return_value=QueryTags()),
        patch(
            "products.managed_warehouse.backend.query_execution.UserAccessControl.has_project_access",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch("products.managed_warehouse.backend.query_schema.MANAGED_TRINO_SCHEMA_DISCOVERY_TIMEOUT_SECONDS", 10),
        patch(
            "products.managed_warehouse.backend.query_schema.connect_managed_warehouse_trino",
            return_value=nullcontext(connection),
        ) as connect,
    ):
        response = process_database_schema_query(
            team,
            DatabaseSchemaQuery(executionTarget="managed_trino", includeFields=include_fields, tables=table_names),
            user=user,
        )
    assert set(response.tables) == (set(table_names) if table_names else {"analytics.orders", "posthog.events_example"})
    assert response.joins == []
    assert "events" not in response.tables
    if include_fields:
        field = response.tables["analytics.orders"].fields["order id"]
        assert field.type == "integer"
        assert field.hogql_value == "`order id`"
    else:
        assert all(not table.fields for table in response.tables.values())
        assert cursor.execute.call_count == 1
    connect.assert_called_once_with(str(team.organization_id), principal="posthog:sql-editor:team:7:user:9")
    cursor.close.assert_called_once()


@pytest.mark.parametrize("failure", ["flag", "anonymous", "token", "project", "connection", "discovery"])
def test_native_schema_rejects_unavailable_access_without_loading_default_catalog(failure: str) -> None:
    team = Team(id=7, organization_id=UUID("00000000-0000-0000-0000-000000000001"))
    with (
        patch("posthoganalytics.feature_enabled", return_value=failure != "flag"),
        patch(
            "products.managed_warehouse.backend.query_execution.get_query_tags",
            return_value=QueryTags(access_method=AccessMethod.PERSONAL_API_KEY if failure == "token" else None),
        ),
        patch(
            "products.managed_warehouse.backend.query_execution.UserAccessControl.has_project_access",
            new_callable=PropertyMock,
            return_value=failure != "project",
        ),
        patch(
            "products.managed_warehouse.backend.query_schema.connect_managed_warehouse_trino",
            side_effect=RuntimeError("discovery failed"),
        ) as connect,
        patch("posthog.api.services.query.resolve_database_for_connection") as default_catalog,
        patch("posthog.api.services.query.capture_exception"),
        pytest.raises(DatabaseSchemaUnavailable if failure == "discovery" else ExposedHogQLError),
    ):
        process_database_schema_query(
            team,
            DatabaseSchemaQuery(
                executionTarget="managed_trino", connectionId="external" if failure == "connection" else None
            ),
            user=None if failure == "anonymous" else User(id=9),
        )
    default_catalog.assert_not_called()
    assert connect.call_count == (1 if failure == "discovery" else 0)
