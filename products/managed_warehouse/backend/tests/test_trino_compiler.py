from uuid import UUID

import pytest
from unittest import mock

from rest_framework.response import Response

from posthog.schema import HogQLQuery, HogQLQueryModifiers

from posthog.models import Team

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
    def test_populates_core_table_locators_from_control_plane_state(self) -> None:
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
            )

        assert compiled.sql == "SELECT event FROM target"
        assert compiled.values == {}
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


def test_build_trino_table_locators_combines_core_and_bound_tables() -> None:
    table_names = ManagedWarehouseTableNames(
        events_table="events_production",
        persons_table="persons_production",
        data_imports_schema="imports_production",
    )
    bindings = [
        mock.Mock(logical_name="orders_model", schema_name="shadow_7_models", table_name="orders_model"),
        mock.Mock(logical_name="stripe_customers", schema_name="imports_production", table_name="customers"),
    ]

    with mock.patch(
        "products.managed_warehouse.backend.table_binding.bind_tables_to_ducklake",
        return_value=bindings,
    ) as bind:
        locators = build_trino_table_locators(
            mock.sentinel.database,
            7,
            catalog_name="org_catalog",
            table_names=table_names,
        )

    assert locators == {
        "events": ("org_catalog", "posthog", "events_production"),
        "persons": ("org_catalog", "posthog", "persons_production"),
        "orders_model": ("org_catalog", "shadow_7_models", "orders_model"),
        "stripe_customers": ("org_catalog", "imports_production", "customers"),
    }
    bind.assert_called_once_with(mock.sentinel.database, 7, data_imports_schema_name="imports_production")
