from uuid import UUID

import pytest
from unittest import mock

from rest_framework.response import Response
from structlog.testing import capture_logs

from posthog.schema import HogQLQuery

from posthog.hogql.transforms.trino.manifest import (
    TrinoCatalogManifest,
    TrinoManifestColumn,
    TrinoManifestTable,
    build_trino_manifest_database,
)

from posthog.models import Organization, Team
from posthog.schema_enums import DatabaseSerializedFieldType

from products.data_modeling.backend.facade.modeling import DataWarehouseModelPath
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseTableNames,
    ManagedWarehouseTeamMembership,
    TrinoExpansionMode,
)
from products.managed_warehouse.backend.table_binding import build_trino_table_locators
from products.managed_warehouse.backend.trino_compiler import (
    TrinoTargetUnavailable,
    compile_hogql_to_trino_sql,
    get_ready_trino_catalog_name,
    prepare_hogql_to_trino_compiler,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


def _membership(*, team_id: int, organization_id: str) -> ManagedWarehouseTeamMembership:
    return ManagedWarehouseTeamMembership(
        team_id=team_id,
        organization_id=organization_id,
        schema_name="production",
        enabled=True,
        backfill_enabled=True,
        table_names=ManagedWarehouseTableNames(
            events_table="events_production",
            persons_table="persons_production",
            data_imports_schema="posthog_data_imports_production",
        ),
        earliest_event_date=None,
    )


def _team() -> Team:
    return Team(id=7, organization_id=UUID("00000000-0000-0000-0000-000000000001"))


class TestReadyTrinoCatalogName:
    @pytest.mark.parametrize("catalog_key", ["trino_catalog_name", "catalog"])
    def test_reads_ready_catalog_and_supports_rolling_deploys(self, catalog_key: str) -> None:
        body = {
            "enabled": True,
            "status": {
                "org": "org-1",
                "state": "ready",
                catalog_key: " org_catalog ",
            },
        }
        with (
            mock.patch(
                "products.managed_warehouse.backend.presentation.views._request",
                return_value=Response(body, status=200),
            ) as request,
            capture_logs() as logs,
        ):
            assert get_ready_trino_catalog_name("org-1") == "org_catalog"

        request.assert_called_once_with("GET", "org-1", "/trino", require_enabled=False)
        assert logs == []

    @pytest.mark.parametrize(
        "body, status_code, expected_log",
        [
            ({"error": "example upstream failure"}, 503, {"reason": "http_error", "log_level": "warning"}),
            ([], 200, {"reason": "invalid_response", "response_type": "list", "log_level": "warning"}),
            (
                {"enabled": False},
                200,
                {"reason": "not_enabled", "enabled": False, "enabled_type": "bool", "log_level": "info"},
            ),
            (
                {},
                200,
                {"reason": "not_enabled", "enabled": None, "enabled_type": "NoneType", "log_level": "info"},
            ),
            (
                {"enabled": True},
                200,
                {"reason": "invalid_status", "status_type": "NoneType", "log_level": "warning"},
            ),
            (
                {"enabled": True, "status": []},
                200,
                {"reason": "invalid_status", "status_type": "list", "log_level": "warning"},
            ),
            (
                {"enabled": True, "status": {"org": "org-1", "state": "pending", "trino_catalog_name": "cat"}},
                200,
                {"reason": "state_not_ready", "state": "pending", "state_type": "str", "log_level": "info"},
            ),
            (
                {"enabled": True, "status": {}},
                200,
                {"reason": "state_not_ready", "state": None, "state_type": "NoneType", "log_level": "info"},
            ),
            (
                {"enabled": True, "status": {"org": "another-org", "state": "ready", "trino_catalog_name": "cat"}},
                200,
                {"reason": "organization_mismatch", "response_organization_id": "another-org", "log_level": "warning"},
            ),
            (
                {"enabled": True, "status": {"org": "org-1", "state": "ready", "trino_catalog_name": " "}},
                200,
                {"reason": "invalid_catalog", "catalog_type": "str", "log_level": "warning"},
            ),
            (
                {"enabled": True, "status": {"org": "org-1", "state": "ready"}},
                200,
                {"reason": "invalid_catalog", "catalog_type": "NoneType", "log_level": "warning"},
            ),
        ],
    )
    def test_rejects_an_unusable_target(self, body: object, status_code: int, expected_log: dict[str, object]) -> None:
        if isinstance(body, dict):
            body = {**body, "error": "example upstream failure", "token": "example-secret"}
            if isinstance(body.get("status"), dict):
                body["status"] = {**body["status"], "connection": {"password": "example-secret"}}
        with (
            mock.patch(
                "products.managed_warehouse.backend.presentation.views._request",
                return_value=Response(body, status=status_code),
            ),
            capture_logs() as logs,
        ):
            assert get_ready_trino_catalog_name("org-1") is None
        assert logs == [
            {
                "event": "trino_target_not_ready",
                "organization_id": "org-1",
                "status_code": status_code,
                **expected_log,
            }
        ]


class TestCompileHogQLToTrinoSQL:
    def test_preserves_sql_bind_values_and_diagnostics_across_the_transpiler_boundary(self) -> None:
        team = _team()
        membership = _membership(team_id=team.pk, organization_id=str(team.organization_id))

        with (
            mock.patch(
                "products.managed_warehouse.backend.trino_compiler.get_ready_trino_catalog_name",
                return_value="org_catalog",
            ),
            mock.patch(
                "products.managed_warehouse.backend.trino_compiler.get_org_team_membership",
                return_value=membership,
            ),
            mock.patch("posthog.hogql.database.database.Database.create_for") as create_database,
            mock.patch("posthog.hogql.modifiers.create_default_modifiers_for_team") as create_modifiers,
            mock.patch(
                "products.managed_warehouse.backend.trino_compiler.build_trino_table_locators"
            ) as build_locators,
        ):
            compiled = compile_hogql_to_trino_sql(
                team.pk,
                HogQLQuery(query="SELECT event FROM events WHERE event = {event}", values={"event": "signup"}),
                team=team,
                include_hogql=True,
            )

        create_database.assert_not_called()
        create_modifiers.assert_not_called()
        build_locators.assert_not_called()

        assert compiled.sql == (
            'SELECT "org_catalog"."posthog"."events_production"."event" '
            'FROM "org_catalog"."posthog"."events_production" '
            'WHERE ("org_catalog"."posthog"."events_production"."event" = %(hogql_val_0)s) LIMIT 50000'
        )
        assert compiled.values == {"hogql_val_0": "signup"}
        assert compiled.hogql == "SELECT event FROM events WHERE equals(event, 'signup') LIMIT 50000"

    @pytest.mark.django_db
    @pytest.mark.parametrize("include_hogql", [False, True])
    def test_populates_core_table_locators_from_control_plane_state(self, include_hogql: bool) -> None:
        organization = Organization.objects.create(name="trino-core-locators")
        team = Team.objects.create(organization=organization)
        membership = _membership(team_id=team.pk, organization_id=str(organization.pk))

        with (
            mock.patch("products.managed_warehouse.backend.cp_teams.list_org_teams", return_value=[]),
            mock.patch(
                "products.managed_warehouse.backend.trino_compiler.get_ready_trino_catalog_name",
                return_value="org_catalog",
            ),
            mock.patch(
                "products.managed_warehouse.backend.trino_compiler.get_org_team_membership",
                return_value=membership,
            ),
        ):
            compiled = compile_hogql_to_trino_sql(
                team.pk,
                HogQLQuery(query="SELECT event FROM events LIMIT 1"),
                team=team,
                include_hogql=include_hogql,
                expansion_mode=TrinoExpansionMode.DJANGO,
            )

        assert compiled.sql == (
            'SELECT "org_catalog"."posthog"."events_production"."event" '
            'FROM "org_catalog"."posthog"."events_production" LIMIT 1'
        )
        assert compiled.values == {}
        assert compiled.hogql == ("SELECT event FROM events LIMIT 1" if include_hogql else None)

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "expression",
        [
            "date(translation_source.timestamp)",
            "ifnotfinite(1.0, 2.0)",
            "medianexactweighted(3, 2)",
            "cardinality([translation_source.event])",
            "json_value('{\"a\": 1}', '$.a')",
        ],
    )
    def test_django_diagnostics_preserve_trino_compilation_with_saved_query_dependencies(self, expression: str) -> None:
        organization = Organization.objects.create(name="trino-diagnostics")
        team = Team.objects.create(organization=organization)
        membership = _membership(team_id=team.pk, organization_id=str(organization.pk))
        DataWarehouseSavedQuery.objects.create(
            team=team,
            name="translation_source",
            query={"kind": "HogQLQuery", "query": "SELECT event, timestamp FROM events"},
            columns={
                "event": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                "timestamp": {"clickhouse": "DateTime", "hogql": "DateTimeDatabaseField"},
            },
        )
        query = HogQLQuery(
            query=f"SELECT {expression} AS result FROM translation_source WHERE translation_source.event = {{event}}",
            values={"event": "signup"},
        )

        with (
            mock.patch("products.managed_warehouse.backend.cp_teams.list_org_teams", return_value=[]),
            mock.patch(
                "products.managed_warehouse.backend.trino_compiler.get_ready_trino_catalog_name",
                return_value="org_catalog",
            ),
            mock.patch(
                "products.managed_warehouse.backend.trino_compiler.get_org_team_membership",
                return_value=membership,
            ),
        ):
            without_diagnostics = compile_hogql_to_trino_sql(
                team.pk,
                query,
                team=team,
                expansion_mode=TrinoExpansionMode.DJANGO,
                bypass_warehouse_access_control=True,
            )
            compiled = compile_hogql_to_trino_sql(
                team.pk,
                query,
                team=team,
                expansion_mode=TrinoExpansionMode.DJANGO,
                bypass_warehouse_access_control=True,
                include_hogql=True,
            )
            assert compiled.hogql is not None
            round_trip = compile_hogql_to_trino_sql(
                team.pk,
                HogQLQuery(query=compiled.hogql),
                team=team,
                expansion_mode=TrinoExpansionMode.DJANGO,
                bypass_warehouse_access_control=True,
            )

        assert (compiled.sql, compiled.values) == (without_diagnostics.sql, without_diagnostics.values)
        assert (round_trip.sql, round_trip.values) == (compiled.sql, compiled.values)
        assert '"org_catalog"."posthog"."events_production"' in compiled.sql
        assert "signup" in compiled.values.values()
        assert "translation_source" in compiled.hogql

    def test_fails_closed_without_a_ready_catalog(self) -> None:
        team = _team()

        with mock.patch(
            "products.managed_warehouse.backend.trino_compiler.get_ready_trino_catalog_name",
            return_value=None,
        ):
            with pytest.raises(TrinoTargetUnavailable, match="ready Trino catalog"):
                compile_hogql_to_trino_sql(team.pk, HogQLQuery(query="SELECT 1"), team=team)

    def test_fails_closed_without_a_team_mapping(self) -> None:
        team = _team()

        with (
            mock.patch(
                "products.managed_warehouse.backend.trino_compiler.get_ready_trino_catalog_name",
                return_value="org_catalog",
            ),
            mock.patch(
                "products.managed_warehouse.backend.trino_compiler.get_org_team_membership",
                return_value=None,
            ),
        ):
            with pytest.raises(TrinoTargetUnavailable, match="physical table mapping"):
                compile_hogql_to_trino_sql(team.pk, HogQLQuery(query="SELECT 1"), team=team)


class TestPreparedTrinoCompiler:
    def test_reuses_one_control_plane_snapshot_for_multiple_queries(self) -> None:
        team = _team()
        membership = _membership(team_id=team.pk, organization_id=str(team.organization_id))

        with (
            mock.patch(
                "products.managed_warehouse.backend.trino_compiler.get_ready_trino_catalog_name",
                return_value="org_catalog",
            ) as get_catalog,
            mock.patch(
                "products.managed_warehouse.backend.trino_compiler.get_org_team_membership",
                return_value=membership,
            ) as get_membership,
            mock.patch(
                "posthog.hogql.transforms.trino.manifest.build_trino_manifest_database",
                wraps=build_trino_manifest_database,
            ) as build_database,
        ):
            compiler = prepare_hogql_to_trino_compiler(team.pk, team=team)
            first = compiler.compile(HogQLQuery(query="SELECT {value}", values={"value": "first"}))
            second = compiler.compile(HogQLQuery(query="SELECT {value}", values={"value": "second"}))

        get_catalog.assert_called_once_with(str(team.organization_id))
        get_membership.assert_called_once_with(str(team.organization_id), team.pk)
        build_database.assert_called_once()
        assert compiler.team_id == team.pk
        assert compiler.organization_id == str(team.organization_id)
        assert compiler.catalog_name == "org_catalog"
        assert first.values == {"hogql_val_0": "first"}
        assert second.values == {"hogql_val_0": "second"}

    def test_rejects_a_team_object_for_another_project(self) -> None:
        team = _team()

        with mock.patch(
            "products.managed_warehouse.backend.trino_compiler.get_ready_trino_catalog_name"
        ) as get_catalog:
            with pytest.raises(TrinoTargetUnavailable, match="provided team"):
                prepare_hogql_to_trino_compiler(team.pk + 1, team=team)

        get_catalog.assert_not_called()

    def test_rejects_a_control_plane_mapping_for_another_tenant(self) -> None:
        team = _team()
        membership = _membership(team_id=team.pk, organization_id="another-organization")

        with (
            mock.patch(
                "products.managed_warehouse.backend.trino_compiler.get_ready_trino_catalog_name",
                return_value="org_catalog",
            ),
            mock.patch(
                "products.managed_warehouse.backend.trino_compiler.get_org_team_membership",
                return_value=membership,
            ),
        ):
            with pytest.raises(TrinoTargetUnavailable, match="mapping does not match"):
                prepare_hogql_to_trino_compiler(team.pk, team=team)

    def test_preserves_explicitly_allowlisted_relations_from_another_catalog(self) -> None:
        team = _team()
        membership = _membership(team_id=team.pk, organization_id=str(team.organization_id))
        manifest = TrinoCatalogManifest(
            tables=(
                TrinoManifestTable(
                    logical_name="orders",
                    locator=("another_catalog", "imports", "orders"),
                    columns=(TrinoManifestColumn(name="id", type=DatabaseSerializedFieldType.STRING),),
                ),
            )
        )

        with (
            mock.patch(
                "products.managed_warehouse.backend.trino_compiler.get_ready_trino_catalog_name",
                return_value="org_catalog",
            ),
            mock.patch(
                "products.managed_warehouse.backend.trino_compiler.get_org_team_membership",
                return_value=membership,
            ),
        ):
            compiled = compile_hogql_to_trino_sql(
                team.pk,
                HogQLQuery(query="SELECT id FROM orders"),
                team=team,
                catalog_manifest=manifest,
            )

        assert 'FROM "another_catalog"."imports"."orders"' in compiled.sql


@pytest.mark.django_db
def test_build_trino_table_locators_uses_provisioned_names_and_canonical_source_aliases() -> None:
    organization = Organization.objects.create(name="trino-locators")
    team = Team.objects.create(organization=organization)
    model_table = DataWarehouseTable.objects.create(
        name="orders_model",
        format="Parquet",
        team=team,
        url_pattern="https://bucket.s3.amazonaws.com/models/orders/*.parquet",
    )
    saved_query_id = UUID("32345678-1234-5678-1234-567812345678")
    saved_query = DataWarehouseSavedQuery.objects.create(
        id=saved_query_id,
        team=team,
        name="orders_model",
        query={"query": "SELECT 1", "kind": "HogQLQuery"},
        table=model_table,
        is_materialized=True,
    )
    DataWarehouseModelPath.objects.create(
        team=team,
        saved_query=saved_query,
        path=["legacy_orders_model"],
    )
    source = ExternalDataSource.objects.create(
        team=team,
        source_id="source_id",
        connection_id="connection_id",
        status=ExternalDataSource.Status.COMPLETED,
        source_type=ExternalDataSourceType.STRIPE,
        prefix="myprefix_",
    )
    source_table = DataWarehouseTable.objects.create(
        name="myprefix_stripe_customers",
        format="Parquet",
        team=team,
        external_data_source=source,
        url_pattern="https://bucket.s3.amazonaws.com/stripe/customers/*.parquet",
    )
    ExternalDataSchema.objects.create(
        team=team,
        name="customers",
        source=source,
        table=source_table,
        should_sync=True,
    )
    table_names = ManagedWarehouseTableNames(
        events_table="events_production",
        persons_table="persons_production",
        data_imports_schema="imports_production",
    )
    database = mock.Mock()
    database.has_table.return_value = True

    with mock.patch(
        "products.managed_warehouse.backend.team_state.data_imports_table_naming_version",
        return_value="copy_v1",
    ):
        locators = build_trino_table_locators(
            database,
            team.pk,
            catalog_name="org_catalog",
            table_names=table_names,
        )

    assert locators == {
        "events": ("org_catalog", "posthog", "events_production"),
        "persons": ("org_catalog", "posthog", "persons_production"),
        "orders_model": (
            "org_catalog",
            f"posthog_data_modeling_team_{team.pk}",
            "legacy_orders_model",
        ),
        "myprefix_stripe_customers": ("org_catalog", "imports_production", "stripe_myprefix_customers"),
        "stripe.myprefix.customers": ("org_catalog", "imports_production", "stripe_myprefix_customers"),
    }
