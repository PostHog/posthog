import uuid

import pytest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

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

FACADE = "products.access_control.backend.facade.api"
SCHEMA_VIEWS = "products.warehouse_sources.backend.presentation.views.external_data_schema"
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

    @parameterized.expand([("demoted_from_admin",), ("removed_from_the_project",)])
    def test_a_copy_that_waits_denies_the_history_table_once_the_user_can_no_longer_set_the_rules(
        self, case: str
    ) -> None:
        requester = self.user
        if case == "removed_from_the_project":
            # Grants on the tables survive losing the project, so only the project check refuses the copy.
            requester = self.editor_user
            self._create_access_control(requester, resource_id=str(self.table.id), access_level="manager")
            self._create_access_control(requester, access_level="manager")
        request_access_rules_copy(self.schema, requester)
        if case == "demoted_from_admin":
            OrganizationMembership.objects.filter(user=requester, organization=self.organization).update(
                level=OrganizationMembership.Level.MEMBER
            )
        else:
            self._create_access_control(
                requester, resource="project", resource_id=str(self.team.id), access_level="none"
            )
        history = self._table("orders_history", STAMPED)

        run_pending_access_rules_copy(self.schema.id, self.team.id, history)

        assert self._rules(history) == {("none", None)}
        assert self._pending() is None

    def test_a_copy_that_fails_denies_the_history_table_and_stays_pending(self) -> None:
        request_access_rules_copy(self.schema, self.user)
        history = self._table("orders_history", STAMPED)

        with patch(f"{FACADE}.ACCESS_CONTROL_MAX_OBJECTS_PER_RESOURCE", 1):
            run_pending_access_rules_copy(self.schema.id, self.team.id, history)

        requester = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        # The requester keeps managing the history table, so the retry can still run.
        assert self._rules(history) == {("none", None), ("manager", requester.id)}
        assert self._pending() is not None

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

    @parameterized.expand(
        [
            ("cannot_manage_access", status.HTTP_403_FORBIDDEN),
            ("token_without_access_control_scope", status.HTTP_403_FORBIDDEN),
            ("object_rule_limit_reached", status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_schema_update_refuses_the_copy_before_saving(self, case: str, expected_status: int) -> None:
        headers = {}
        if case == "cannot_manage_access":
            self.client.force_login(self.editor_user)
        elif case == "token_without_access_control_scope":
            token = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                user=self.user, label="test", secure_value=hash_key_value(token), scopes=["external_data_source:write"]
            )
            headers = {"authorization": f"Bearer {token}"}
        else:
            self.client.force_login(self.user)

        with patch(f"{FACADE}.ACCESS_CONTROL_MAX_OBJECTS_PER_RESOURCE", 1):
            response = self.client.patch(
                f"/api/projects/{self.team.pk}/external_data_schemas/{self.schema.id}/",
                {"copy_access_rules_to_history": True, "should_sync": False},
                format="json",
                headers=headers,
            )

        assert response.status_code == expected_status, response.json()
        self.schema.refresh_from_db()
        assert self.schema.should_sync is True
        assert self._pending() is None

    @parameterized.expand(
        [
            ("can_manage_access", True, True, True),
            ("cannot_manage_access", False, True, True),
            ("cannot_view", False, False, True),
            ("table_without_rules_of_its_own", True, True, False),
        ]
    )
    def test_table_endpoint_describes_the_history_table_and_the_rules_to_copy(
        self, case: str, can_manage: bool, can_view: bool, own_rules: bool
    ) -> None:
        history = self._table("orders_history", STAMPED)
        if not can_view:
            self._create_access_control(self.editor_user, resource_id=str(history.id), access_level="none")
        if not own_rules:
            AccessControl.objects.filter(resource_id=str(self.table.id)).delete()
        self.client.force_login(self.user if can_manage else self.editor_user)

        response = self.client.get(f"/api/projects/{self.team.pk}/warehouse_tables/{self.table.id}/history_table/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        expected = {"id": str(history.id), "name": "postgres.orders_history", "user_can_manage_access": can_manage}
        assert response.json() == {
            "history_table": expected if can_view else None,
            # Only someone who can manage the table's access, with rules on the table itself, has rules to copy.
            "main_table_has_copyable_rules": can_manage and own_rules,
        }

    @parameterized.expand([("history_table_registered", True), ("history_table_not_registered_yet", False)])
    def test_schema_update_copies_now_or_once_the_history_table_registers(self, _name: str, registered: bool) -> None:
        history = self._table("orders_history", STAMPED) if registered else None
        self.client.force_login(self.user)

        response = self.client.patch(
            f"/api/projects/{self.team.pk}/external_data_schemas/{self.schema.id}/",
            {"copy_access_rules_to_history": True},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        if history is not None:
            assert self._rules(history) == self._rules(self.table)
            assert self._pending() is None
        else:
            assert self._pending() == {"table_id": str(self.table.id), "user_id": self.user.id}

    @parameterized.expand(
        [
            ("turning_history_off", "consolidated", False),
            ("an_editor_choosing_the_same_mode", "both", True),
        ]
    )
    def test_only_turning_history_off_withdraws_a_waiting_copy(self, case: str, mode: str, kept: bool) -> None:
        request_access_rules_copy(self.schema, self.user)
        self._create_access_control(self.editor_user, resource_id=str(self.table.id), access_level="editor")
        self.client.force_login(self.user if case == "turning_history_off" else self.editor_user)

        response = self.client.patch(
            f"/api/projects/{self.team.pk}/external_data_schemas/{self.schema.id}/",
            {"cdc_table_mode": mode},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert (self._pending() is not None) == kept

    @parameterized.expand(
        [
            ("can_manage_access", status.HTTP_200_OK),
            ("cannot_manage_access", status.HTTP_403_FORBIDDEN),
            ("no_history_table", status.HTTP_404_NOT_FOUND),
        ]
    )
    def test_table_endpoint_copies_the_rules_to_the_history_table(self, case: str, expected_status: int) -> None:
        history = None if case == "no_history_table" else self._table("orders_history", STAMPED)
        self.client.force_login(self.editor_user if case == "cannot_manage_access" else self.user)

        response = self.client.post(
            f"/api/projects/{self.team.pk}/warehouse_tables/{self.table.id}/copy_access_rules_to_history_table/"
        )

        assert response.status_code == expected_status, response.json()
        if history is not None:
            assert self._rules(history) == (self._rules(self.table) if case == "can_manage_access" else set())

    def test_a_sync_the_update_starts_finds_the_copy_request(self) -> None:
        self.schema.sync_type_config = {"cdc_table_mode": "consolidated"}
        self.schema.save()
        self.client.force_login(self.user)
        pending_when_sync_started: list[object] = []

        def record_pending(_schema: ExternalDataSchema) -> None:
            pending_when_sync_started.append(self._pending())

        with patch(f"{SCHEMA_VIEWS}._reset_cdc_for_full_resnapshot", side_effect=record_pending):
            response = self.client.patch(
                f"/api/projects/{self.team.pk}/external_data_schemas/{self.schema.id}/",
                {"cdc_table_mode": "both", "copy_access_rules_to_history": True},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert pending_when_sync_started == [{"table_id": str(self.table.id), "user_id": self.user.id}]

    def test_the_copy_endpoint_ends_a_waiting_request(self) -> None:
        request_access_rules_copy(self.schema, self.user)
        history = self._table("orders_history", STAMPED)
        self.client.force_login(self.user)

        response = self.client.post(
            f"/api/projects/{self.team.pk}/warehouse_tables/{self.table.id}/copy_access_rules_to_history_table/"
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert self._rules(history) == self._rules(self.table)
        assert self._pending() is None
