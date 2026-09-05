from datetime import timedelta

import pytest
from posthog.test.base import APIBaseTest

from django.test import override_settings

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models import OrganizationMembership, Team, User

from products.access_control.backend.models.access_control import AccessControl
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource
from products.workflows.backend.models import HogFlow
from products.workflows.backend.service_jwt import WORKFLOW_WAREHOUSE_ACCESS_PURPOSE


@pytest.mark.ee
@override_settings(WORKFLOW_WAREHOUSE_ACCESS_JWT_SECRETS=["test-warehouse-access"])
class TestWarehouseTriggerAccess(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.owner = User.objects.create_and_join(self.organization, "workflow-owner@example.com", "testtest")
        self.membership = OrganizationMembership.objects.get(user=self.owner, organization=self.organization)
        self.view = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="daily_totals", query={"kind": "HogQLQuery", "query": "select 1"}
        )
        self.flow = HogFlow.objects.create(
            team=self.team,
            name="Warehouse rows",
            created_by=self.owner,
            status=HogFlow.State.ACTIVE,
            trigger={"type": "data-warehouse-view", "table_name": self.view.name},
        )
        self.url = f"/api/projects/{self.team.id}/workflow_warehouse_access/"
        self.client.logout()

    def _allowed(self, trigger_type: str = "data-warehouse-view", table_name: str = "daily_totals") -> list[str]:
        response = self.client.post(
            self.url,
            {"trigger_type": trigger_type, "table_name": table_name, "flow_ids": [str(self.flow.id)]},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {WORKFLOW_WAREHOUSE_ACCESS_PURPOSE.mint({'team_id': self.team.id})}",
        )
        self.assertEqual(response.status_code, 200, response.json())
        return response.json()["allowed_flow_ids"]

    @parameterized.expand([("view",), ("table",), ("source",), ("resource",)])
    def test_revoked_access_stops_existing_workflow(self, denied_resource: str) -> None:
        trigger_type = "data-warehouse-view"
        table_name = self.view.name
        resource = "warehouse_view"
        resource_id: str | None = str(self.view.id)
        if denied_resource in ("table", "source"):
            source = ExternalDataSource.objects.create(team=self.team, source_type="Postgres", prefix="billing")
            table = DataWarehouseTable.objects.create(
                team=self.team, name="billing_postgres_orders", columns={}, external_data_source=source
            )
            trigger_type, table_name = "data-warehouse-table", "postgres.billing.orders"
            resource = "warehouse_table" if denied_resource == "table" else "external_data_source"
            resource_id = str(table.id if denied_resource == "table" else source.id)
            self.flow.trigger = {"type": trigger_type, "table_name": table_name}
            self.flow.save()
        elif denied_resource == "resource":
            resource, resource_id = "warehouse_objects", None

        self.assertEqual(self._allowed(trigger_type, table_name), [str(self.flow.id)])
        AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=resource_id,
            organization_member=self.membership,
            access_level="none",
        )
        self.assertEqual(self._allowed(trigger_type, table_name), [])

    @parameterized.expand(
        [
            ("deleted_view",),
            ("missing_creator",),
            ("inactive_creator",),
            ("removed_member",),
            ("paused",),
            ("unfiltered",),
            ("other_team",),
        ]
    )
    def test_ineligible_workflows_receive_no_rows(self, reason: str) -> None:
        if reason == "deleted_view":
            self.view.deleted = True
            self.view.save()
        elif reason == "missing_creator":
            self.flow.created_by = None
            self.flow.save()
        elif reason == "inactive_creator":
            self.owner.is_active = False
            self.owner.save()
        elif reason == "removed_member":
            self.membership.delete()
        elif reason == "paused":
            self.flow.status = HogFlow.State.DRAFT
            self.flow.save()
        elif reason == "unfiltered":
            self.flow.trigger = {"type": "data-warehouse-view"}
            self.flow.save()
        elif reason == "other_team":
            self.flow.team = Team.objects.create(organization=self.organization, name="Other project")
            self.flow.save()
        self.assertEqual(self._allowed(), [])

    @parameterized.expand([("session",), ("wrong_team",), ("wrong_audience",), ("expired",)])
    def test_rejects_invalid_service_credentials(self, reason: str) -> None:
        authorization = ""
        if reason == "session":
            self.client.force_login(self.user)
        else:
            team_id = self.team.id
            if reason == "wrong_team":
                team_id = Team.objects.create(organization=self.organization, name="Other project").id
            token = encode_jwt(
                {"team_id": team_id},
                timedelta(minutes=-5 if reason == "expired" else 5),
                PosthogJwtAudience.TASKS_CREATE
                if reason == "wrong_audience"
                else PosthogJwtAudience.WORKFLOW_WAREHOUSE_ACCESS,
                signing_key="test-warehouse-access",
            )
            authorization = f"Bearer {token}"
        response = self.client.post(self.url, {}, format="json", HTTP_AUTHORIZATION=authorization)
        self.assertEqual(response.status_code, 401, response.json())
