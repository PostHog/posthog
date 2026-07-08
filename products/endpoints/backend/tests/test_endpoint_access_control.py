import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.rbac.user_access_control import ACCESS_CONTROL_RESOURCES, model_to_resource

from products.endpoints.backend.models import Endpoint, EndpointVersion
from products.endpoints.backend.tests.conftest import create_endpoint_with_version

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


SAMPLE_QUERY = {"kind": "HogQLQuery", "query": "SELECT 1"}


class TestEndpointResourceRegistration(SimpleTestCase):
    def test_endpoint_is_a_controllable_resource(self):
        self.assertIn("endpoint", ACCESS_CONTROL_RESOURCES)

    def test_endpoint_model_maps_to_endpoint_resource(self):
        self.assertEqual(model_to_resource(Endpoint()), "endpoint")

    def test_endpoint_version_inherits_parent_endpoint_resource(self):
        # Versions have no route of their own, so access control on a version resolves
        # to the parent endpoint resource via the model_to_resource override.
        self.assertEqual(model_to_resource(EndpointVersion()), "endpoint")


@pytest.mark.ee
class TestEndpointAccessControl(ClickhouseTestMixin, APIBaseTest):
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

        self.endpoint = create_endpoint_with_version(
            name="my_endpoint",
            team=self.team,
            query=SAMPLE_QUERY,
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

    def _create_project_default(self, resource="endpoint", access_level="none"):
        return AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=None,
            access_level=access_level,
            organization_member=None,
            role=None,
        )

    def _list_url(self) -> str:
        return f"/api/environments/{self.team.pk}/endpoints/"

    def _detail_url(self, name=None) -> str:
        return f"/api/environments/{self.team.pk}/endpoints/{name or self.endpoint.name}/"

    @parameterized.expand(
        [
            # (access_level, method, expected_status, patch_body)
            ("viewer", "GET", status.HTTP_200_OK, None),
            ("viewer", "PATCH", status.HTTP_403_FORBIDDEN, {"description": "updated"}),
            ("viewer", "DELETE", status.HTTP_403_FORBIDDEN, None),
            ("editor", "GET", status.HTTP_200_OK, None),
            ("editor", "PATCH", status.HTTP_200_OK, {"description": "updated"}),
            ("editor", "DELETE", status.HTTP_204_NO_CONTENT, None),
            ("none", "GET", status.HTTP_403_FORBIDDEN, None),
        ]
    )
    def test_access_level_matrix(self, access_level, method, expected_status, patch_body):
        user = {"viewer": self.viewer_user, "editor": self.editor_user, "none": self.no_access_user}[access_level]
        self._create_access_control(user, access_level=access_level)
        self.client.force_login(user)

        if method == "GET":
            response = self.client.get(self._detail_url())
        elif method == "PATCH":
            response = self.client.patch(self._detail_url(), data=patch_body, format="json")
        elif method == "DELETE":
            response = self.client.delete(self._detail_url())
        else:
            raise AssertionError(f"Unsupported method {method}")

        self.assertEqual(response.status_code, expected_status, getattr(response, "data", None))

    def test_viewer_can_list(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        self.assertEqual(self.client.get(self._list_url()).status_code, status.HTTP_200_OK)

    def test_project_default_none_blocks_non_creator_retrieve(self):
        self._create_project_default(access_level="none")
        self.client.force_login(self.viewer_user)
        self.assertEqual(self.client.get(self._detail_url()).status_code, status.HTTP_403_FORBIDDEN)

    def test_object_level_none_blocks_specific_endpoint(self):
        # Resource-level viewer access, but object-level "none" on this specific endpoint.
        self._create_access_control(self.viewer_user, access_level="viewer")
        self._create_access_control(self.viewer_user, resource_id=str(self.endpoint.id), access_level="none")
        self.client.force_login(self.viewer_user)
        self.assertEqual(self.client.get(self._detail_url()).status_code, status.HTTP_403_FORBIDDEN)

    def test_run_blocked_by_object_level_denial(self):
        # run (execution) is gated by object-level access only: an explicit per-endpoint "none"
        # blocks execution before the query runs.
        self._create_access_control(self.viewer_user, resource_id=str(self.endpoint.id), access_level="none")
        self.client.force_login(self.viewer_user)
        response = self.client.get(self._detail_url() + "run/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_run_not_blocked_by_resource_level_default(self):
        # A restrictive resource-level default must NOT block execution — run is the public-facing
        # data API. Without an explicit per-endpoint denial, the team member can still run it.
        self._create_project_default(access_level="none")
        self.client.force_login(self.viewer_user)
        response = self.client.get(self._detail_url() + "run/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, getattr(response, "data", None))

    def test_create_blocked_without_resource_editor_access(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.post(
            self._list_url(), data={"name": "blocked_create", "query": SAMPLE_QUERY}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Endpoint.objects.filter(team=self.team, name="blocked_create").exists())

    def test_create_allowed_with_resource_editor_access(self):
        self._create_access_control(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)
        response = self.client.post(
            self._list_url(), data={"name": "editor_create", "query": SAMPLE_QUERY}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        self.assertTrue(Endpoint.objects.filter(team=self.team, name="editor_create").exists())

    def test_creator_list_filters_out_object_blocked_endpoint(self):
        # Creator sees their own endpoint; an object-level "none" on another user's endpoint excludes it.
        other_user = User.objects.create_and_join(self.organization, "otheruser@posthog.com", "testtest")
        other_endpoint = create_endpoint_with_version(
            name="other_endpoint", team=self.team, query=SAMPLE_QUERY, created_by=other_user
        )
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="endpoint",
            resource_id=str(other_endpoint.id),
            access_level="none",
            organization_member=membership,
        )
        self.client.force_login(self.user)
        response = self.client.get(self._list_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [e["name"] for e in response.json()["results"]]
        self.assertIn(self.endpoint.name, names)
        self.assertNotIn(other_endpoint.name, names)

    def test_object_level_grant_works_through_project_default_none(self):
        # With the project default at "none", an object-level grant still lets the user read and
        # edit that specific endpoint, while other endpoints stay blocked.
        other_endpoint = create_endpoint_with_version(
            name="other_endpoint", team=self.team, query=SAMPLE_QUERY, created_by=self.user
        )
        self._create_project_default(access_level="none")
        self._create_access_control(self.viewer_user, resource_id=str(self.endpoint.id), access_level="editor")
        self.client.force_login(self.viewer_user)

        self.assertEqual(self.client.get(self._detail_url()).status_code, status.HTTP_200_OK)
        patch_response = self.client.patch(self._detail_url(), data={"description": "granted edit"}, format="json")
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)

        # A different endpoint without an object-level grant stays blocked.
        self.assertEqual(self.client.get(self._detail_url(other_endpoint.name)).status_code, status.HTTP_403_FORBIDDEN)
