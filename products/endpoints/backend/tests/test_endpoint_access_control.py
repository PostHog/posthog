import pytest
from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.endpoints.backend.tests.conftest import create_endpoint_with_version

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


@pytest.mark.ee
class TestEndpointAccessControl(APIBaseTest):
    def setUp(self):
        super().setUp()

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        self.viewer_user = User.objects.create_and_join(self.organization, "viewer@posthog.com", "testtest")
        self.editor_user = User.objects.create_and_join(self.organization, "editor@posthog.com", "testtest")
        self.no_access_user = User.objects.create_and_join(self.organization, "noaccess@posthog.com", "testtest")

        self.sample_query = {
            "kind": "HogQLQuery",
            "query": "SELECT count(1) FROM query_log",
        }
        self.endpoint = create_endpoint_with_version(
            name="my_endpoint",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
        )

    def _create_access_control(self, user, resource="endpoint", resource_id=None, access_level="viewer"):
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        return AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=resource_id,
            access_level=access_level,
            organization_member=membership,
        )

    def _create_project_default(self, access_level="none"):
        return AccessControl.objects.create(
            team=self.team,
            resource="endpoint",
            resource_id=None,
            access_level=access_level,
            organization_member=None,
            role=None,
        )

    # --- Viewer ---

    def test_viewer_can_list_endpoints(self):
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/endpoints/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_retrieve_endpoint(self):
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/endpoints/{self.endpoint.name}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], self.endpoint.name)

    def test_viewer_cannot_create_endpoint(self):
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)
        response = self.client.post(
            f"/api/environments/{self.team.pk}/endpoints/",
            {"name": "new_endpoint", "query": self.sample_query},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_update_endpoint(self):
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/endpoints/{self.endpoint.name}/",
            data={"description": "Updated description"},
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_delete_endpoint(self):
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)
        response = self.client.delete(f"/api/environments/{self.team.pk}/endpoints/{self.endpoint.name}/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # --- Editor ---

    def test_editor_can_update_endpoint(self):
        self._create_access_control(self.editor_user, access_level="editor")

        self.client.force_login(self.editor_user)
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/endpoints/{self.endpoint.name}/",
            data={"description": "Updated description"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual(response.json()["description"], "Updated description")

    def test_editor_can_delete_endpoint(self):
        self._create_access_control(self.editor_user, access_level="editor")

        self.client.force_login(self.editor_user)
        response = self.client.delete(f"/api/environments/{self.team.pk}/endpoints/{self.endpoint.name}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.endpoint.refresh_from_db()
        self.assertTrue(self.endpoint.deleted)

    # --- None ---

    def test_none_access_cannot_list_endpoints(self):
        self._create_access_control(self.no_access_user, access_level="none")

        self.client.force_login(self.no_access_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/endpoints/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_none_access_cannot_retrieve_endpoint(self):
        self._create_access_control(self.no_access_user, access_level="none")

        self.client.force_login(self.no_access_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/endpoints/{self.endpoint.name}/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # --- Project default ---

    def test_project_default_none_blocks_list_without_specific_access(self):
        self._create_project_default(access_level="none")

        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/endpoints/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_explicit_access_overrides_project_default_none(self):
        self._create_project_default(access_level="none")
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/endpoints/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # --- Object-level ---

    def test_object_level_editor_overrides_resource_none(self):
        # Resource-level access is none, but the user has editor on this specific endpoint.
        self._create_access_control(self.editor_user, access_level="none")
        self._create_access_control(
            self.editor_user,
            resource_id=str(self.endpoint.id),
            access_level="editor",
        )

        self.client.force_login(self.editor_user)
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/endpoints/{self.endpoint.name}/",
            data={"description": "Updated via object access"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

    def test_object_level_viewer_cannot_update(self):
        # Object-level viewer access is read-only for that endpoint.
        self._create_access_control(self.viewer_user, access_level="none")
        self._create_access_control(
            self.viewer_user,
            resource_id=str(self.endpoint.id),
            access_level="viewer",
        )

        self.client.force_login(self.viewer_user)
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/endpoints/{self.endpoint.name}/",
            data={"description": "Should be blocked"},
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # --- Serialized access level ---

    def test_serialized_response_includes_user_access_level(self):
        self._create_access_control(self.editor_user, access_level="editor")

        self.client.force_login(self.editor_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/endpoints/{self.endpoint.name}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["user_access_level"], "editor")
