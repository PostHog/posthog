import uuid

import pytest
from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


@pytest.mark.ee
class TestExternalDataSchemaAccessControl(APIBaseTest):
    def setUp(self):
        super().setUp()

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()

        # editor_user is the subject; self.user (org admin) is only used to create objects.
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.editor_user = User.objects.create_and_join(self.organization, "editor@posthog.com", "testtest")

        self.source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            prefix="test",
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"}},
        )
        self.table = DataWarehouseTable.objects.create(
            name="Customers",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            external_data_source=self.source,
            columns={"id": {"clickhouse": "Int32", "hogql": "integer", "valid": True}},
        )
        self.schema = ExternalDataSchema.objects.create(
            name="Customers", team_id=self.team.pk, source_id=self.source.id, table=self.table
        )

    def _grant(self, user, resource, resource_id, level):
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        return AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=resource_id,
            access_level=level,
            organization_member=membership,
        )

    def _reported_level(self, user):
        self.client.force_login(user)
        listed = self.client.get(f"/api/environments/{self.team.pk}/external_data_schemas/")
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        row = next(r for r in listed.json()["results"] if r["id"] == str(self.schema.id))
        return row["user_access_level"]

    def _reload(self, user):
        self.client.force_login(user)
        return self.client.post(f"/api/environments/{self.team.pk}/external_data_schemas/{self.schema.id}/reload/")

    def test_table_lock_blocks_sync_for_source_editor(self):
        # Editor on the parent source, but the specific table locked to viewer.
        self._grant(self.editor_user, "external_data_source", None, "editor")
        self._grant(self.editor_user, "warehouse_table", str(self.table.id), "viewer")

        # The table's own rule is the most specific, so it wins over the source's editor access.
        self.assertEqual(self._reported_level(self.editor_user), "viewer")
        # And syncing the locked table is forbidden.
        self.assertEqual(self._reload(self.editor_user).status_code, status.HTTP_403_FORBIDDEN)

    def test_source_object_restriction_cascades_to_unruled_tables(self):
        # Restricting the source itself (per-object rule) applies to tables without their own rules.
        self._grant(self.editor_user, "external_data_source", str(self.source.id), "viewer")

        self.assertEqual(self._reported_level(self.editor_user), "viewer")
        self.assertEqual(self._reload(self.editor_user).status_code, status.HTTP_403_FORBIDDEN)

    def test_table_grant_overrides_restricted_source(self):
        # A table-level editor rule takes precedence over the restricted source.
        self._grant(self.editor_user, "external_data_source", str(self.source.id), "viewer")
        self._grant(self.editor_user, "warehouse_table", str(self.table.id), "editor")

        self.assertEqual(self._reported_level(self.editor_user), "editor")
        self.client.force_login(self.editor_user)
        resp = self.client.patch(f"/api/environments/{self.team.pk}/external_data_schemas/{self.schema.id}/", {})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_table_lock_blocks_schedule_update_for_source_editor(self):
        # PATCH (changing sync frequency / method) is a write action — gated by the table lock too.
        self._grant(self.editor_user, "external_data_source", None, "editor")
        self._grant(self.editor_user, "warehouse_table", str(self.table.id), "viewer")

        self.client.force_login(self.editor_user)
        resp = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{self.schema.id}/",
            {"sync_frequency": "6hour"},
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_null_table_falls_back_to_source_gate(self):
        # A schema not yet synced (no table) has no per-table lock — only the source gate applies.
        self.schema.table = None
        self.schema.save()
        self._grant(self.editor_user, "external_data_source", None, "editor")

        self.assertEqual(self._reported_level(self.editor_user), "editor")

    def test_org_admin_bypasses_table_lock(self):
        # Org admins bypass object-level access control everywhere.
        admin = User.objects.create_and_join(self.organization, "admin2@posthog.com", "testtest")
        membership = OrganizationMembership.objects.get(user=admin, organization=self.organization)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()
        self._grant(admin, "warehouse_table", str(self.table.id), "none")

        self.assertEqual(self._reported_level(admin), "manager")
