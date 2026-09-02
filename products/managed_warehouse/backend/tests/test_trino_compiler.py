from uuid import UUID

import pytest
from unittest import mock

from rest_framework.response import Response

from posthog.schema import HogQLQuery, HogQLQueryModifiers

from posthog.hogql.database.database import Database

from posthog.models import Organization, Team
from posthog.schema_enums import PersonsOnEventsMode

from products.data_modeling.backend.facade.modeling import DataWarehouseModelPath
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseTableNames,
    ManagedWarehouseTeamMembership,
)
from products.managed_warehouse.backend.table_binding import build_trino_table_locators
from products.managed_warehouse.backend.trino_compiler import (
    TrinoTargetUnavailable,
    compile_hogql_to_trino_sql,
    get_ready_trino_catalog_name,
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
                catalog_key: "org_catalog",
            },
        }
        with mock.patch(
            "products.managed_warehouse.backend.presentation.views._request",
            return_value=Response(body, status=200),
        ) as request:
            assert get_ready_trino_catalog_name("org-1") == "org_catalog"

        request.assert_called_once_with("GET", "org-1", "/trino", require_enabled=False)

    @pytest.mark.parametrize(
        "body",
        [
            {"enabled": False},
            {"enabled": True, "status": {"org": "org-1", "state": "pending", "trino_catalog_name": "cat"}},
            {"enabled": True, "status": {"org": "another-org", "state": "ready", "trino_catalog_name": "cat"}},
            {"enabled": True, "status": {"org": "org-1", "state": "ready", "trino_catalog_name": ""}},
        ],
    )
    def test_rejects_an_unusable_target(self, body: dict[str, object]) -> None:
        with mock.patch(
            "products.managed_warehouse.backend.presentation.views._request",
            return_value=Response(body, status=200),
        ):
            assert get_ready_trino_catalog_name("org-1") is None


class TestCompileHogQLToTrinoSQL:
    def test_preserves_sql_bind_values_and_diagnostics_across_the_transpiler_boundary(self) -> None:
        team = _team()
        membership = _membership(team_id=team.pk, organization_id=str(team.organization_id))
        database = Database(include_posthog_tables=True)
        modifiers = HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS)

        with (
            mock.patch(
                "products.managed_warehouse.backend.trino_compiler.get_ready_trino_catalog_name",
                return_value="org_catalog",
            ),
            mock.patch(
                "products.managed_warehouse.backend.trino_compiler.get_org_team_membership",
                return_value=membership,
            ),
            mock.patch("posthog.hogql.database.database.Database.create_for", return_value=database),
            mock.patch(
                "posthog.hogql.modifiers.create_default_modifiers_for_team",
                return_value=modifiers,
            ),
            mock.patch(
                "products.managed_warehouse.backend.trino_compiler.build_trino_table_locators",
                return_value={"events": ("org_catalog", "posthog", "events_production")},
            ),
            mock.patch(
                "products.access_control.backend.property_access_control.get_restricted_properties_with_group_type_index_for_team",
                return_value=set(),
            ),
        ):
            compiled = compile_hogql_to_trino_sql(
                team.pk,
                HogQLQuery(query="SELECT event FROM events WHERE event = {event}", values={"event": "signup"}),
                team=team,
                include_hogql=True,
            )

        assert compiled.sql == (
            'SELECT "org_catalog"."posthog"."events_production"."event" '
            'FROM "org_catalog"."posthog"."events_production" '
            'WHERE ("org_catalog"."posthog"."events_production"."event" = %(hogql_val_0)s) LIMIT 50000'
        )
        assert compiled.values == {"hogql_val_0": "signup"}
        assert compiled.hogql == "SELECT event FROM events WHERE equals(event, 'signup') LIMIT 50000"

    @pytest.mark.parametrize(
        ("include_hogql", "expected_hogql", "expected_print_calls"),
        [(False, None, 1), (True, "SELECT event FROM events", 2)],
    )
    def test_populates_core_table_locators_from_control_plane_state(
        self, include_hogql: bool, expected_hogql: str | None, expected_print_calls: int
    ) -> None:
        team = _team()
        membership = _membership(team_id=team.pk, organization_id=str(team.organization_id))
        database = mock.MagicMock()
        locators = {"events": ("org_catalog", "posthog", "events_production")}
        modifiers = HogQLQueryModifiers()

        with (
            mock.patch(
                "products.managed_warehouse.backend.trino_compiler.get_ready_trino_catalog_name",
                return_value="org_catalog",
            ),
            mock.patch(
                "products.managed_warehouse.backend.trino_compiler.get_org_team_membership",
                return_value=membership,
            ),
            mock.patch("posthog.hogql.database.database.Database.create_for", return_value=database),
            mock.patch(
                "posthog.hogql.modifiers.create_default_modifiers_for_team",
                return_value=modifiers,
            ),
            mock.patch(
                "products.managed_warehouse.backend.trino_compiler.build_trino_table_locators",
                return_value=locators,
            ) as build_locators,
            mock.patch(
                "posthog.hogql.printer.utils.prepare_and_print_ast",
                side_effect=[("SELECT event FROM target", None), ("SELECT event FROM events", None)],
            ) as prepare_and_print,
        ):
            compiled = compile_hogql_to_trino_sql(
                team.pk,
                HogQLQuery(query="SELECT event FROM events LIMIT 1"),
                team=team,
                include_hogql=include_hogql,
            )

        assert compiled.sql == "SELECT event FROM target"
        assert compiled.values == {}
        assert compiled.hogql == expected_hogql
        build_locators.assert_called_once_with(
            database,
            team.pk,
            catalog_name="org_catalog",
            table_names=membership.table_names,
        )
        trino_context = prepare_and_print.call_args_list[0].args[1]
        assert trino_context.trino_table_locators == locators
        assert trino_context.modifiers is modifiers
        assert prepare_and_print.call_args_list[0].kwargs["dialect"] == "trino"
        assert prepare_and_print.call_count == expected_print_calls
        if include_hogql:
            hogql_context = prepare_and_print.call_args_list[1].args[1]
            assert hogql_context.database is database
            assert prepare_and_print.call_args_list[1].kwargs["dialect"] == "hogql"

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
