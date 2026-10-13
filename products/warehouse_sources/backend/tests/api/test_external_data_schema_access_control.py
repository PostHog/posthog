import uuid

import pytest
from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.access_control.backend.models.access_control import AccessControl
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource


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

    def _patch(self, user):
        self.client.force_login(user)
        return self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{self.schema.id}/", {"sync_frequency": "6hour"}
        )

    @parameterized.expand(
        [
            # A rule on the table itself wins over whatever the source says, in both directions.
            ("table_lock_beats_source_editor", ("external_data_source", None, "editor"), "viewer", "viewer", False),
            (
                "table_grant_beats_source_viewer",
                ("external_data_source", "SOURCE_ID", "viewer"),
                "editor",
                "editor",
                True,
            ),
            # Without a table rule the source's access applies, whether it's set on the source
            # object or across all sources.
            (
                "source_object_restriction_cascades",
                ("external_data_source", "SOURCE_ID", "viewer"),
                None,
                "viewer",
                False,
            ),
            ("source_editor_without_table_rule", ("external_data_source", None, "editor"), None, "editor", True),
        ]
    )
    def test_effective_access(self, _name, source_rule, table_level, expected_level, may_write):
        resource, resource_id, level = source_rule
        self._grant(self.editor_user, resource, str(self.source.id) if resource_id else None, level)
        if table_level:
            self._grant(self.editor_user, "warehouse_table", str(self.table.id), table_level)

        self.assertEqual(self._reported_level(self.editor_user), expected_level)
        if may_write:
            self.assertEqual(self._patch(self.editor_user).status_code, status.HTTP_200_OK)
            self.assertNotEqual(self._reload(self.editor_user).status_code, status.HTTP_403_FORBIDDEN)
        else:
            self.assertEqual(self._patch(self.editor_user).status_code, status.HTTP_403_FORBIDDEN)
            self.assertEqual(self._reload(self.editor_user).status_code, status.HTTP_403_FORBIDDEN)

    def test_unsynced_schema_falls_back_to_source(self):
        # No table exists until the first sync, so there's nothing to carry a per-table rule.
        self.schema.table = None
        self.schema.save()
        self._grant(self.editor_user, "external_data_source", None, "editor")

        self.assertEqual(self._reported_level(self.editor_user), "editor")

    def test_org_admin_bypasses_table_lock(self):
        admin = User.objects.create_and_join(self.organization, "admin2@posthog.com", "testtest")
        membership = OrganizationMembership.objects.get(user=admin, organization=self.organization)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()
        self._grant(admin, "warehouse_table", str(self.table.id), "none")

        self.assertEqual(self._reported_level(admin), "manager")
        self.assertEqual(self._patch(admin).status_code, status.HTTP_200_OK)

    def test_reads_follow_source_access(self):
        # Reads resolve through the schema's source/table too, so a member restricted from one
        # source can't read its schemas, while the source they were granted stays readable.
        other_source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            prefix="other",
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"}},
        )
        other_schema = ExternalDataSchema.objects.create(
            name="Invoices", team_id=self.team.pk, source_id=other_source.id, table=None
        )
        self._grant(self.editor_user, "external_data_source", None, "none")
        self._grant(self.editor_user, "external_data_source", str(self.source.id), "viewer")

        self.client.force_login(self.editor_user)
        base = f"/api/environments/{self.team.pk}/external_data_schemas"
        self.assertEqual(self.client.get(f"{base}/{self.schema.id}/").status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get(f"{base}/{other_schema.id}/").status_code, status.HTTP_403_FORBIDDEN)

        # The list must agree with retrieve: the denied source's schemas aren't served at all,
        # not just blocked on the detail endpoint.
        listed = self.client.get(f"{base}/")
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        listed_ids = {row["id"] for row in listed.json()["results"]}
        self.assertIn(str(self.schema.id), listed_ids)
        self.assertNotIn(str(other_schema.id), listed_ids)

    def test_source_endpoints_respect_table_lock(self):
        # These live on the source viewset, which authorizes the source and never resolves a schema
        # through object permissions, so the per-table check has to happen there explicitly.
        self._grant(self.editor_user, "external_data_source", None, "editor")
        self._grant(self.editor_user, "warehouse_table", str(self.table.id), "viewer")
        self.schema.should_sync = True
        self.schema.save()

        self.client.force_login(self.editor_user)
        source_base = f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}"
        bulk = self.client.patch(
            f"{source_base}/bulk_update_schemas/",
            {"schemas": [{"id": str(self.schema.id), "should_sync": True}]},
            format="json",
        )
        self.assertEqual(bulk.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.post(f"{source_base}/reload/").status_code, status.HTTP_403_FORBIDDEN)
        # Deleting the source deletes every table it synced, so the same lock blocks it.
        self.assertEqual(self.client.delete(f"{source_base}/").status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(ExternalDataSource.objects.get(id=self.source.id).deleted)

    def test_source_wide_sync_allowed_without_locked_tables(self):
        # The guard above must not break the ordinary case.
        self._grant(self.editor_user, "external_data_source", None, "editor")
        self.schema.should_sync = True
        self.schema.save()

        self.client.force_login(self.editor_user)
        resp = self.client.post(f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/reload/")
        self.assertNotEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
