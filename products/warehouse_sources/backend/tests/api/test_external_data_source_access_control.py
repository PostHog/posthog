import uuid

import pytest
from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.role import Role, RoleMembership
from products.warehouse_sources.backend.facade.models import (
    MANAGED_WAREHOUSE_SOURCE_PREFIX,
    ExternalDataSchema,
    ExternalDataSource,
)


@pytest.mark.ee
class TestExternalDataSourceAccessControl(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()

        # Enable access control features
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ACCESS_CONTROL,
                "name": AvailableFeature.ACCESS_CONTROL,
            },
            {
                "key": AvailableFeature.ROLE_BASED_ACCESS,
                "name": AvailableFeature.ROLE_BASED_ACCESS,
            },
        ]
        self.organization.save()

        # Create test users
        self.viewer_user = User.objects.create_and_join(self.organization, "viewer@posthog.com", "testtest")
        self.editor_user = User.objects.create_and_join(self.organization, "editor@posthog.com", "testtest")
        self.no_access_user = User.objects.create_and_join(self.organization, "noaccess@posthog.com", "testtest")

        # Create a test source
        self.source = self._create_external_data_source()
        self.schema = self._create_external_data_schema(self.source.id)

    def _create_external_data_source(self, created_by=None) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=created_by or self.user,
            prefix="test",
            job_inputs={
                "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
            },
        )

    def _create_external_data_schema(self, source_id) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(
            name="Customers", team_id=self.team.pk, source_id=source_id, table=None
        )

    def _create_access_control(self, user, resource="external_data_source", resource_id=None, access_level="viewer"):
        """Helper to create access control for a user"""
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        return AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=resource_id,
            access_level=access_level,
            organization_member=membership,
        )

    def _create_project_default_access_control(self, access_level="none"):
        """Helper to create project-default access control (applies to all users without explicit access)"""
        return AccessControl.objects.create(
            team=self.team,
            resource="external_data_source",
            resource_id=None,
            access_level=access_level,
            organization_member=None,
            role=None,
        )

    def _create_managed_source(self, **overrides: object) -> ExternalDataSource:
        source_team = overrides.get("team")
        if not isinstance(source_team, Team):
            source_team = self.team
        fields: dict[str, object] = {
            "team": source_team,
            "source_id": str(uuid.uuid4()),
            "connection_id": str(uuid.uuid4()),
            "source_type": "Postgres",
            "prefix": MANAGED_WAREHOUSE_SOURCE_PREFIX,
            "access_method": ExternalDataSource.AccessMethod.DIRECT,
            "direct_query_enabled": True,
            "created_by": self.user,
            "connection_metadata": {
                "engine": "duckdb",
                "system_managed": True,
                "credential_kind": "project_reader",
                "reader_configured": True,
            },
            "job_inputs": {
                "host": "managed.example.com",
                "port": 5432,
                "database": "ducklake",
                "user": f"posthog_team_{source_team.id}",
                "password": "secret",
            },
        }
        fields.update(overrides)
        return ExternalDataSource.objects.create(**fields)

    def _create_legacy_managed_source(self, **overrides: object) -> ExternalDataSource:
        fields: dict[str, object] = {
            "connection_metadata": {
                "engine": "duckdb",
                "system_managed": True,
                "credential_kind": "org_root",
            },
            "job_inputs": {
                "host": "managed.example.com",
                "port": 5432,
                "database": "ducklake",
                "user": "organization_login",
                "password": "secret",
            },
        }
        fields.update(overrides)
        return self._create_managed_source(**fields)

    # --- Viewer Access Level Tests ---

    def test_viewer_can_list_sources(self):
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_retrieve_source(self):
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(self.source.id))

    def test_viewer_cannot_delete_source(self):
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)
        response = self.client.delete(f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("editor", response.json()["detail"].lower())

    def test_viewer_cannot_update_source(self):
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/",
            data={"description": "Updated description"},
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_reload_source(self):
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)
        response = self.client.post(f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/reload/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # --- Editor Access Level Tests ---

    def test_editor_can_list_sources(self):
        self._create_access_control(self.editor_user, access_level="editor")

        self.client.force_login(self.editor_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_editor_can_retrieve_source(self):
        self._create_access_control(self.editor_user, access_level="editor")

        self.client.force_login(self.editor_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_editor_can_update_source(self):
        self._create_access_control(self.editor_user, access_level="editor")

        self.client.force_login(self.editor_user)
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/",
            data={"description": "Updated description"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.source.refresh_from_db()
        self.assertEqual(self.source.description, "Updated description")

    def test_editor_can_delete_source(self):
        self._create_access_control(self.editor_user, access_level="editor")

        self.client.force_login(self.editor_user)
        response = self.client.delete(f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.source.refresh_from_db()
        self.assertTrue(self.source.deleted)

    # --- None Access Level Tests ---

    def test_none_access_cannot_list_sources(self):
        """Test that a user with no access at all gets 403 (not empty list)"""
        self._create_access_control(self.no_access_user, access_level="none")

        self.client.force_login(self.no_access_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")

        # When user has "none" resource access AND no specific object access, they get 403
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_none_access_cannot_retrieve_source(self):
        self._create_access_control(self.no_access_user, access_level="none")

        self.client.force_login(self.no_access_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # --- Project Default Access Control Tests ---

    def test_project_default_none_blocks_list_without_specific_access(self):
        self._create_project_default_access_control(access_level="none")

        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")

        # When user has "none" via project-default AND no specific object access, they get 403
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_explicit_access_overrides_project_default_none(self):
        self._create_project_default_access_control(access_level="none")
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

    # --- Object-Level Access Control Tests ---

    def test_specific_source_access_with_none_resource_access(self):
        # Create another source
        source2 = self._create_external_data_source()

        # Set resource-level access to none
        self._create_access_control(self.viewer_user, access_level="none")

        # Give viewer access to only the first source
        self._create_access_control(
            self.viewer_user,
            resource="external_data_source",
            resource_id=str(self.source.id),
            access_level="viewer",
        )

        self.client.force_login(self.viewer_user)

        # Should be able to access the first source
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should not be able to access the second source
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source2.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_filtered_list_with_mixed_access(self):
        # Create another source that viewer won't have access to
        self._create_external_data_source()

        # Set resource-level access to none
        self._create_access_control(self.viewer_user, access_level="none")

        # Give viewer access to only the first source
        self._create_access_control(
            self.viewer_user,
            resource="external_data_source",
            resource_id=str(self.source.id),
            access_level="viewer",
        )

        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Only the source with explicit access should be returned (not the other source)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], str(self.source.id))

    def test_connections_includes_only_ready_managed_warehouse_regardless_of_source_access(self):
        external_source = ExternalDataSource.objects.create(
            team=self.team,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            source_type="Postgres",
            prefix="Customer database",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
        )
        pending_source = self._create_managed_source(
            direct_query_enabled=False,
            connection_metadata={
                "engine": "duckdb",
                "system_managed": True,
                "credential_kind": "project_reader",
                "reader_configured": False,
            },
        )
        self._create_access_control(self.viewer_user, access_level="none")
        self.client.force_login(self.viewer_user)

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/connections/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), [])

        managed_source = self._create_managed_source()
        self._create_access_control(
            self.viewer_user,
            resource_id=str(managed_source.id),
            access_level="none",
        )
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/connections/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = [item["id"] for item in response.json()]
        self.assertEqual(returned_ids, [str(managed_source.id)])
        self.assertTrue(response.json()[0]["is_builtin_managed_warehouse"])
        self.assertNotIn(str(external_source.id), returned_ids)
        self.assertNotIn(str(pending_source.id), returned_ids)

    def test_connections_prefers_dynamic_service_source_over_project_reader(self) -> None:
        project_reader = self._create_managed_source()
        dynamic = self._create_managed_source(
            job_inputs={},
            connection_metadata={
                "engine": "duckdb",
                "system_managed": True,
                "credential_kind": "duckgres_service",
                "lifecycle_generation": 1,
            },
        )

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/connections/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in response.json()], [str(dynamic.id)])
        self.assertTrue(response.json()[0]["is_builtin_managed_warehouse"])
        self.assertNotEqual(dynamic.id, project_reader.id)

    @parameterized.expand(
        [
            ("missing_system_managed", {"connection_metadata": {"engine": "duckdb"}}),
            (
                "wrong_engine",
                {"connection_metadata": {"engine": "postgres", "system_managed": True}},
            ),
            ("wrong_source_type", {"source_type": "MySQL"}),
            (
                "synced_source",
                {
                    "access_method": ExternalDataSource.AccessMethod.WAREHOUSE,
                    "direct_query_enabled": True,
                },
            ),
            ("direct_query_disabled", {"direct_query_enabled": False}),
            (
                "reader_pending",
                {
                    "connection_metadata": {
                        "engine": "duckdb",
                        "system_managed": True,
                        "credential_kind": "project_reader",
                        "reader_configured": False,
                    }
                },
            ),
            (
                "missing_reader_marker",
                {
                    "connection_metadata": {
                        "engine": "duckdb",
                        "system_managed": True,
                        "credential_kind": "project_reader",
                    }
                },
            ),
            (
                "spoofed_root_username",
                {
                    "job_inputs": {
                        "host": "managed.example.com",
                        "port": 5432,
                        "database": "ducklake",
                        "user": "root",
                        "password": "secret",
                    }
                },
            ),
            (
                "malformed_credentials",
                {
                    "job_inputs": {
                        "host": "managed.example.com",
                        "port": "invalid",
                        "database": "ducklake",
                        "user": "posthog_team_invalid",
                        "password": "",
                    }
                },
            ),
        ]
    )
    def test_connections_omits_incomplete_reserved_sources(self, _name: str, overrides: dict[str, object]) -> None:
        source = self._create_managed_source(**overrides)

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/connections/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn(str(source.id), [item["id"] for item in response.json()])

    def test_connections_prefers_dynamic_auth_over_reader_and_legacy_sources(self) -> None:
        legacy_source = self._create_legacy_managed_source()
        ready_reader = self._create_managed_source()
        dynamic_source = self._create_managed_source(
            job_inputs={},
            connection_metadata={
                "engine": "duckdb",
                "system_managed": True,
                "credential_kind": "duckgres_service",
                "lifecycle_generation": 1,
            },
        )
        pending_reader = self._create_managed_source(
            connection_metadata={
                "engine": "duckdb",
                "system_managed": True,
                "credential_kind": "project_reader",
                "reader_configured": False,
            }
        )
        malformed_legacy = self._create_legacy_managed_source(job_inputs={})
        unknown_kind = self._create_managed_source(
            connection_metadata={
                "engine": "duckdb",
                "system_managed": True,
                "credential_kind": "unknown",
            }
        )
        external_source = ExternalDataSource.objects.create(
            team=self.team,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            source_type="Postgres",
            prefix="Customer database",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            created_by=self.user,
        )
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/connections/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["id"] for item in response.json()],
            [str(dynamic_source.id), str(external_source.id)],
        )
        self.assertTrue(
            next(item for item in response.json() if item["id"] == str(dynamic_source.id))[
                "is_builtin_managed_warehouse"
            ]
        )
        self.assertNotIn(str(ready_reader.id), [item["id"] for item in response.json()])
        self.assertNotIn(str(legacy_source.id), [item["id"] for item in response.json()])
        self.assertNotIn(str(pending_reader.id), [item["id"] for item in response.json()])
        self.assertNotIn(str(malformed_legacy.id), [item["id"] for item in response.json()])
        self.assertNotIn(str(unknown_kind.id), [item["id"] for item in response.json()])

    def test_connections_hides_legacy_source_and_marks_ready_reader_as_built_in(self) -> None:
        ready_reader = self._create_managed_source()
        legacy_source = self._create_legacy_managed_source()
        external_source = ExternalDataSource.objects.create(
            team=self.team,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            source_type="Postgres",
            prefix="Customer database",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/connections/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [(item["id"], item["is_builtin_managed_warehouse"]) for item in response.json()],
            [(str(ready_reader.id), True), (str(external_source.id), False)],
        )
        self.assertNotIn(str(legacy_source.id), [item["id"] for item in response.json()])

    def test_connections_applies_external_source_access_control_to_canonical_legacy_source(self) -> None:
        legacy_source = self._create_legacy_managed_source()
        self._create_access_control(self.viewer_user, access_level="none")
        self.client.force_login(self.viewer_user)

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/connections/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), [])

        self._create_access_control(
            self.viewer_user,
            resource_id=str(legacy_source.id),
            access_level="viewer",
        )
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/connections/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [(item["id"], item["is_builtin_managed_warehouse"]) for item in response.json()],
            [(str(legacy_source.id), False)],
        )

    @parameterized.expand([("org_root",), ("stored_server_login",)])
    def test_connections_exposes_a_valid_grandfathered_legacy_source(self, credential_kind: str) -> None:
        legacy_source = self._create_legacy_managed_source(
            connection_metadata={
                "engine": "duckdb",
                "system_managed": True,
                "credential_kind": credential_kind,
            }
        )

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/connections/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [(item["id"], item["is_builtin_managed_warehouse"]) for item in response.json()],
            [(str(legacy_source.id), False)],
        )

    def test_connections_does_not_fall_back_to_an_older_accessible_legacy_source(self) -> None:
        older_source = self._create_legacy_managed_source()
        self._create_legacy_managed_source()
        self._create_access_control(self.viewer_user, access_level="none")
        self._create_access_control(
            self.viewer_user,
            resource_id=str(older_source.id),
            access_level="viewer",
        )
        self.client.force_login(self.viewer_user)

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/connections/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), [])

    def test_connections_uses_a_ready_reader_when_a_newer_reserved_row_is_malformed(self) -> None:
        managed_source = self._create_managed_source()
        malformed_source = self._create_managed_source(
            job_inputs={
                "host": "managed.example.com",
                "port": 5432,
                "database": "ducklake",
                "user": "root",
                "password": "secret",
            }
        )

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/connections/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = [item["id"] for item in response.json()]
        self.assertIn(str(managed_source.id), returned_ids)
        self.assertNotIn(str(malformed_source.id), returned_ids)

    def test_connections_omits_deleted_and_cross_team_managed_sources(self) -> None:
        deleted_source = self._create_managed_source(deleted=True)
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        cross_team_source = self._create_managed_source(team=other_team)

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/connections/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = [item["id"] for item in response.json()]
        self.assertNotIn(str(deleted_source.id), returned_ids)
        self.assertNotIn(str(cross_team_source.id), returned_ids)

    @parameterized.expand(
        [
            ("external_data_source_read", "external_data_source:read", status.HTTP_200_OK),
            ("query_read", "query:read", status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_connections_preserves_external_data_source_api_scope(
        self, _name: str, scope: str, expected_status: int
    ) -> None:
        api_key = self.create_personal_api_key_with_scopes([scope])
        self.client.force_authenticate(None)

        response = self.client.get(
            f"/api/environments/{self.team.pk}/external_data_sources/connections/",
            headers={"authorization": f"Bearer {api_key}"},
        )

        self.assertEqual(response.status_code, expected_status)

    def test_external_source_resources_expose_only_the_canonical_legacy_source(self) -> None:
        legacy_source = self._create_legacy_managed_source()
        managed_source = self._create_managed_source()
        incomplete_source = self._create_managed_source(connection_metadata={})

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = [item["id"] for item in response.json()["results"]]
        self.assertIn(str(legacy_source.id), returned_ids)
        self.assertNotIn(str(managed_source.id), returned_ids)
        self.assertNotIn(str(incomplete_source.id), returned_ids)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{legacy_source.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for source in (managed_source, incomplete_source):
            response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.id}/")
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_preserves_legacy_managed_source_as_read_only_external_resource(self) -> None:
        legacy_source = self._create_legacy_managed_source()
        ready_reader = self._create_managed_source()
        pending_reader = self._create_managed_source(
            connection_metadata={
                "engine": "duckdb",
                "system_managed": True,
                "credential_kind": "project_reader",
                "reader_configured": False,
            }
        )
        malformed_legacy = self._create_legacy_managed_source(job_inputs={})
        unknown_kind = self._create_managed_source(
            connection_metadata={
                "engine": "duckdb",
                "system_managed": True,
                "credential_kind": "unknown",
            }
        )
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        cross_team_legacy = self._create_legacy_managed_source(team=other_team)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = [item["id"] for item in response.json()["results"]]
        self.assertIn(str(legacy_source.id), returned_ids)
        self.assertNotIn(str(ready_reader.id), returned_ids)
        self.assertNotIn(str(pending_reader.id), returned_ids)
        self.assertNotIn(str(malformed_legacy.id), returned_ids)
        self.assertNotIn(str(unknown_kind.id), returned_ids)
        self.assertNotIn(str(cross_team_legacy.id), returned_ids)

        for hidden_source in (ready_reader, pending_reader, malformed_legacy, unknown_kind):
            response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{hidden_source.id}/")
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{legacy_source.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{legacy_source.id}/",
            data={"description": "Updated description"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # --- Organization Admin Tests ---

    def test_org_admin_has_full_access(self):
        self._create_project_default_access_control(access_level="none")

        # Make user an org admin
        membership = OrganizationMembership.objects.get(user=self.editor_user, organization=self.organization)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()

        self.client.force_login(self.editor_user)

        # Should be able to list
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

        # Should be able to delete without explicit permissions
        response = self.client.delete(f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    # --- Role-Based Access Tests ---

    def test_role_grants_editor_access(self):
        self._create_project_default_access_control(access_level="none")

        # Create a role with editor access to sources
        role = Role.objects.create(name="Source Editors", organization=self.organization)
        RoleMembership.objects.create(user=self.editor_user, role=role)

        AccessControl.objects.create(team=self.team, resource="external_data_source", access_level="editor", role=role)

        self.client.force_login(self.editor_user)

        # Should be able to list
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

        # Should be able to delete via role access
        response = self.client.delete(f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_role_grants_viewer_access(self):
        self._create_project_default_access_control(access_level="none")

        # Create a role with viewer access
        role = Role.objects.create(name="Source Viewers", organization=self.organization)
        RoleMembership.objects.create(user=self.viewer_user, role=role)

        AccessControl.objects.create(team=self.team, resource="external_data_source", access_level="viewer", role=role)

        self.client.force_login(self.viewer_user)

        # Should be able to list
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

        # Should NOT be able to delete
        response = self.client.delete(f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # --- Creator Access Tests ---

    def test_creator_can_delete_other_users_blocked_source(self):
        source = self._create_external_data_source(created_by=self.editor_user)

        # Set project-default to none (blocks access for everyone)
        self._create_project_default_access_control(access_level="none")

        # Give editor_user editor resource access (required for delete action)
        self._create_access_control(self.editor_user, access_level="editor")

        # Block viewer_user specifically from this source
        self._create_access_control(
            self.viewer_user,
            resource="external_data_source",
            resource_id=str(source.id),
            access_level="none",
        )

        self.client.force_login(self.editor_user)

        # Creator should be able to delete their own source
        response = self.client.delete(f"/api/environments/{self.team.pk}/external_data_sources/{source.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_viewer_cannot_delete_regardless_of_creator(self):
        source = self._create_external_data_source(created_by=self.viewer_user)

        # Give viewer_user only viewer resource access
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)

        # Even though they created it, viewer resource access is not enough for DELETE action
        # (DELETE requires editor resource-level access)
        response = self.client.delete(f"/api/environments/{self.team.pk}/external_data_sources/{source.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_creator_can_modify_access_controls(self):
        source = self._create_external_data_source(created_by=self.editor_user)

        uac = UserAccessControl(self.editor_user, self.team)
        can_modify = uac.check_can_modify_access_levels_for_object(source)

        self.assertTrue(can_modify)

    # --- user_access_level Response Field Tests ---

    def test_user_access_level_in_list_response(self):
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertIn("user_access_level", results[0])

    def test_user_access_level_in_detail_response(self):
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("user_access_level", response.json())

    # --- Manager Access Tests ---

    def test_manager_can_access_access_controls_endpoint(self):
        self._create_access_control(self.editor_user, access_level="manager")

        self.client.force_login(self.editor_user)
        response = self.client.get(
            f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/access_controls/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access_controls", response.json())
        self.assertIn("user_can_edit_access_levels", response.json())
