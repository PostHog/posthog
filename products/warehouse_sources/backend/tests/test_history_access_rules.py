import uuid

import pytest

from parameterized import parameterized
from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.warehouse_sources.backend.facade.contracts import HistoryAccessRulesNotAllowedError
from products.warehouse_sources.backend.facade.testing import WarehouseAccessControlTestMixin
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.history_access_rules import (
    PENDING_COPY_KEY,
    registered_history_table,
    request_access_rules_copy,
    run_pending_access_rules_copy,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import build_table_name

STAMPED = {"history_table": True, "history_naming": "ph_validity"}


@pytest.mark.ee
class TestHistoryAccessRules(WarehouseAccessControlTestMixin):
    resource = "warehouse_table"

    def setUp(self) -> None:
        super().setUp()
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )
        self.source = ExternalDataSource.objects.create(
            team=self.team, source_id=str(uuid.uuid4()), connection_id=str(uuid.uuid4()), source_type="Postgres"
        )
        self.table = self._table("orders")
        self.schema = ExternalDataSchema.objects.create(
            name="orders",
            team=self.team,
            source=self.source,
            table=self.table,
            sync_type=ExternalDataSchema.SyncType.CDC,
            sync_type_config={"cdc_table_mode": "both"},
        )
        self._create_access_control(self.viewer_user, resource_id=str(self.table.id), access_level="none")
        AccessControl.objects.create(
            team=self.team, resource="warehouse_table", resource_id=str(self.table.id), access_level="viewer"
        )

    def _table(self, storage_name: str, options: dict | None = None) -> DataWarehouseTable:
        return DataWarehouseTable.objects.create(
            team=self.team,
            name=build_table_name(self.source, storage_name),
            format="DeltaS3Wrapper",
            url_pattern=f"s3://bucket/{storage_name}",
            external_data_source=self.source,
            options=options or {},
        )

    def _rules(self, table: DataWarehouseTable) -> set[tuple[str, uuid.UUID | None]]:
        return set(
            AccessControl.objects.filter(
                team=self.team, resource="warehouse_table", resource_id=str(table.id)
            ).values_list("access_level", "organization_member_id")
        )

    def _pending(self) -> object:
        self.schema.refresh_from_db()
        return (self.schema.sync_type_config or {}).get(PENDING_COPY_KEY)

    @parameterized.expand(
        [
            ("stamped_history_table", "orders_history", STAMPED, False, True),
            ("legacy_history_table", "orders_cdc", {"history_table": True}, False, True),
            ("history_table_is_the_schemas_own_table", "orders_history", STAMPED, True, False),
            ("another_schema_syncs_into_the_name", "orders_cdc", {}, None, False),
        ]
    )
    def test_finds_the_registered_history_table(
        self, _name: str, storage_name: str, options: dict, own_table: bool | None, found: bool
    ) -> None:
        history = self._table(storage_name, options)
        if own_table:
            self.schema.table = history
            self.schema.save()
        if own_table is None:
            ExternalDataSchema.objects.create(name=storage_name, team=self.team, source=self.source, table=history)

        assert registered_history_table(history if own_table else self.table) == (history if found else None)

    @parameterized.expand([("asked", True), ("not_asked", False)])
    def test_copies_the_rules_when_the_history_table_registers(self, _name: str, asked: bool) -> None:
        if asked:
            request_access_rules_copy(self.schema, self.user)
        history = self._table("orders_history", STAMPED)

        run_pending_access_rules_copy(self.schema.id, self.team.id, history)

        assert self._rules(history) == (self._rules(self.table) if asked else set())
        assert self._pending() is None
        logged = ActivityLog.objects.filter(team_id=self.team.id, scope="AccessControl", user=self.user)
        assert logged.count() == (2 if asked else 0)

    def test_a_copy_that_waits_is_skipped_once_the_user_can_no_longer_set_the_rules(self) -> None:
        request_access_rules_copy(self.schema, self.user)
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.MEMBER
        )
        history = self._table("orders_history", STAMPED)

        run_pending_access_rules_copy(self.schema.id, self.team.id, history)

        assert self._rules(history) == set()
        assert self._pending() is None

    def test_replaces_the_rules_of_an_existing_history_table(self) -> None:
        history = self._table("orders_history", STAMPED)
        self._create_access_control(self.editor_user, resource_id=str(history.id), access_level="manager")

        request_access_rules_copy(self.schema, self.user)

        assert self._rules(history) == self._rules(self.table)
        assert self._pending() is None

    @parameterized.expand([("history_table_registered", True), ("history_table_not_registered_yet", False)])
    def test_refuses_a_user_who_cannot_manage_access(self, _name: str, registered: bool) -> None:
        history = self._table("orders_history", STAMPED) if registered else None

        with pytest.raises(HistoryAccessRulesNotAllowedError):
            request_access_rules_copy(self.schema, self.editor_user)

        if history is not None:
            assert self._rules(history) == set()
        assert self._pending() is None

    def test_schema_update_refuses_the_copy_before_saving(self) -> None:
        self.client.force_login(self.editor_user)

        response = self.client.patch(
            f"/api/projects/{self.team.pk}/external_data_schemas/{self.schema.id}/",
            {"copy_access_rules_to_history": True, "should_sync": False},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert self._pending() is None
        assert self.schema.should_sync is True

    @parameterized.expand([("can_manage_access", True), ("cannot_manage_access", False)])
    def test_table_endpoint_returns_the_history_table_only_to_who_can_manage_its_access(
        self, _name: str, can_manage: bool
    ) -> None:
        history = self._table("orders_history", STAMPED)
        self.client.force_login(self.user if can_manage else self.editor_user)

        response = self.client.get(f"/api/projects/{self.team.pk}/warehouse_tables/{self.table.id}/history_table/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        expected = {"id": str(history.id), "name": "postgres.orders_history"} if can_manage else None
        assert response.json() == {"history_table": expected}
