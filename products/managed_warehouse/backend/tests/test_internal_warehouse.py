import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from rest_framework.response import Response

from posthog.schema import HogQLQuery

from posthog.hogql.errors import ExposedHogQLError

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.managed_warehouse.backend.facade.access import internal_loading_enabled
from products.managed_warehouse.backend.internal_loading import load_internal_team
from products.managed_warehouse.backend.logic.connection import (
    activate_managed_warehouse_source_lifecycle,
    deactivate_managed_warehouse_source_lifecycle,
    ensure_managed_warehouse_direct_source,
)
from products.managed_warehouse.backend.logic.sql_editor import managed_warehouse_sql_editor_uses_trino
from products.managed_warehouse.backend.models import DuckgresServer, ManagedWarehouseSourceLifecycle
from products.managed_warehouse.backend.presentation import views
from products.managed_warehouse.backend.query_execution import validate_managed_trino_query
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseCredential,
    DataWarehouseTable,
    ExternalDataSchema,
    ExternalDataSource,
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("flags_enabled", [False, True])
def test_internal_provision_loads_without_customer_access(team, django_capture_on_commit_callbacks, flags_enabled):
    def control_plane(method, organization_id, path, **kwargs):
        if path == "/provision":
            assert views.data_ops_variant(team.organization_id) is None
            return Response({"username": "root", "password": "synthetic-password"}, status=202)
        return Response({}, status=200)

    with (
        patch.object(views, "_request", side_effect=control_plane),
        patch(
            "posthoganalytics.feature_enabled",
            side_effect=lambda flag, *args, **kwargs: flags_enabled and flag == "data-warehouse-scene",
        ),
        patch("products.data_warehouse.backend.facade.tasks.sync_team_earliest_event_date.delay"),
        patch("products.managed_warehouse.backend.tasks.load_internal_warehouse.delay") as enqueue,
        django_capture_on_commit_callbacks(execute=True),
    ):
        response = views.provision(
            team.organization_id,
            "example-warehouse",
            team.id,
            "main",
            require_enabled=False,
            triggered_by="django-admin:staff@example.com",
            internal_only=True,
        )
        assert response.status_code == 202
        assert views.data_ops_variant(team.organization_id) is None
        assert not managed_warehouse_sql_editor_uses_trino(team.organization_id)
        with pytest.raises(ExposedHogQLError, match="not enabled"):
            validate_managed_trino_query(HogQLQuery(query="SELECT 1"), team, team.organization.members.first())

    lifecycle = ManagedWarehouseSourceLifecycle.objects.get(organization_id=team.organization_id)
    enqueue.assert_called_once_with(str(team.organization_id), team.id, lifecycle.generation)
    assert DuckgresServer.objects.filter(organization_id=team.organization_id).exists()
    assert (
        ensure_managed_warehouse_direct_source(
            team_id=team.id, organization_id=team.organization_id, expected_generation=lifecycle.generation
        )
        is None
    )
    assert not ExternalDataSource.objects.filter(team_id=team.id).exists()


@pytest.mark.parametrize("state", ["inactive", "stale", "wrong_org", "not_ready", "ready", "promoted"])
def test_internal_loading_respects_lifecycle_and_dispatches_existing_data(team, state):
    generation = activate_managed_warehouse_source_lifecycle(
        organization_id=team.organization_id, expected_generation=0, internal_only=True
    )
    assert generation is not None
    DuckgresServer.objects.create(
        organization_id=team.organization_id, host="warehouse.example.com", username="root", password="synthetic"
    )
    if state == "promoted":
        ManagedWarehouseSourceLifecycle.objects.filter(organization_id=team.organization_id).update(internal_only=False)
    if state == "inactive":
        deactivate_managed_warehouse_source_lifecycle(
            organization_id=team.organization_id, expected_generation=generation
        )
    credential = DataWarehouseCredential.objects.create(
        team=team, access_key="example-key", access_secret="example-secret"
    )
    source = ExternalDataSource.objects.create(team=team, source_type="Postgres")
    schemas: list[ExternalDataSchema] = []
    for folder in ["queryable_2026_01_01", None]:
        table = DataWarehouseTable.objects.create(
            team=team,
            name=f"table_{len(schemas)}",
            format="Parquet",
            url_pattern="s3://example-bucket/table",
            credential=credential,
            queryable_folder=folder,
            external_data_source=source,
        )
        schemas.append(ExternalDataSchema.objects.create(team=team, source=source, table=table, name=table.name))
    model = DataWarehouseSavedQuery.objects.create(
        team=team,
        name="example_materialized_view",
        query={"kind": "HogQLQuery", "query": "SELECT 1"},
        is_materialized=True,
        table=schemas[0].table,
    )
    temporal = MagicMock(start_workflow=AsyncMock())
    with (
        patch(
            "products.managed_warehouse.backend.internal_loading.get_ready_trino_connection_target",
            return_value=None if state == "not_ready" else MagicMock(),
        ),
        patch.object(views, "_get_project_team_row", return_value={"backfill_enabled": True}),
        patch(
            "products.managed_warehouse.backend.internal_loading.async_connect", new=AsyncMock(return_value=temporal)
        ),
    ):
        if state == "not_ready":
            with pytest.raises(RuntimeError, match="not ready"):
                load_internal_team(str(team.organization_id), team.id, generation)
        else:
            load_internal_team(
                str(team.organization_id),
                team.id + (1000 if state == "wrong_org" else 0),
                generation + (1 if state == "stale" else 0),
            )
    if state in {"ready", "promoted"}:
        calls = temporal.start_workflow.call_args_list
        assert len(calls) == 3
        assert {call.args[0] for call in calls} == {
            "ducklake-register.data-imports",
            "ducklake-copy.data-imports",
            "ducklake-copy.data-modeling",
        }
        assert all(call.args[1].team_id == team.id for call in calls)
        copied_model = next(call.args[1].models[0] for call in calls if call.args[0] == "ducklake-copy.data-modeling")
        assert copied_model.saved_query_id == str(model.id)
        assert copied_model.table_uri.endswith(f"/{model.folder_path}/{model.normalized_name}")
    else:
        temporal.start_workflow.assert_not_called()


@pytest.mark.parametrize("entrypoint", ["data_ops", "query", "connection"])
def test_trino_flag_promotes_the_loaded_warehouse_without_reprovisioning(team, user, entrypoint):
    generation = activate_managed_warehouse_source_lifecycle(
        organization_id=team.organization_id, expected_generation=0, internal_only=True
    )
    assert generation is not None
    server = DuckgresServer.objects.create(
        organization_id=team.organization_id, host="warehouse.example.com", username="root", password="synthetic"
    )
    with patch("posthoganalytics.feature_enabled", return_value=True), patch.object(views, "_request") as control_plane:
        if entrypoint == "data_ops":
            assert views.data_ops_variant(team.organization_id) == "trino"
        elif entrypoint == "query":
            validate_managed_trino_query(HogQLQuery(query="SELECT 1"), team, user)
        else:
            assert managed_warehouse_sql_editor_uses_trino(team.organization_id)
        source = ensure_managed_warehouse_direct_source(
            team_id=team.id, organization_id=team.organization_id, expected_generation=generation
        )
        assert source is not None
        repeated = ensure_managed_warehouse_direct_source(
            team_id=team.id, organization_id=team.organization_id, expected_generation=generation
        )
        assert repeated is not None
        assert repeated.id == source.id
        control_plane.assert_not_called()
    lifecycle = ManagedWarehouseSourceLifecycle.objects.get(organization_id=team.organization_id)
    assert lifecycle.internal_only is False
    assert lifecycle.generation == generation
    assert internal_loading_enabled(team.organization_id)
    server.refresh_from_db()
    assert server.password == "synthetic"
    assert DuckgresServer.objects.get(organization_id=team.organization_id).id == server.id
