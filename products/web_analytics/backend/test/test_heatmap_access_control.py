import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.rbac.user_access_control import ACCESS_CONTROL_RESOURCES, model_to_resource

from products.web_analytics.backend.models import SavedHeatmap

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


class TestHeatmapResourceRegistration(SimpleTestCase):
    def test_heatmap_is_a_controllable_resource(self):
        self.assertIn("heatmap", ACCESS_CONTROL_RESOURCES)

    def test_saved_heatmap_model_maps_to_heatmap_resource(self):
        self.assertEqual(model_to_resource(SavedHeatmap()), "heatmap")


@pytest.mark.ee
class TestHeatmapAccessControl(ClickhouseTestMixin, APIBaseTest):
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

        self.heatmap = SavedHeatmap.objects.create(
            team=self.team,
            name="my heatmap",
            url="https://example.com",
            target_widths=[1024],
            created_by=self.user,
            status=SavedHeatmap.Status.COMPLETED,
        )

    def _create_access_control(self, user, resource="heatmap", resource_id=None, access_level="viewer"):
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        return AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=resource_id,
            access_level=access_level,
            organization_member=membership,
        )

    def _create_project_default(self, resource="heatmap", access_level="none"):
        return AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=None,
            access_level=access_level,
            organization_member=None,
            role=None,
        )

    def _list_url(self) -> str:
        return f"/api/environments/{self.team.pk}/saved/"

    def _detail_url(self, short_id=None) -> str:
        return f"/api/environments/{self.team.pk}/saved/{short_id or self.heatmap.short_id}/"

    @parameterized.expand(
        [
            # (access_level, method, expected_status, patch_body)
            ("viewer", "GET", status.HTTP_200_OK, None),
            ("viewer", "PATCH", status.HTTP_403_FORBIDDEN, {"name": "updated"}),
            ("viewer", "POST_REGENERATE", status.HTTP_403_FORBIDDEN, None),
            ("editor", "GET", status.HTTP_200_OK, None),
            ("editor", "PATCH", status.HTTP_200_OK, {"name": "updated"}),
            ("editor", "POST_REGENERATE", status.HTTP_200_OK, None),
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
        elif method == "POST_REGENERATE":
            response = self.client.post(self._detail_url() + "regenerate/")
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

    def test_object_level_none_blocks_specific_heatmap(self):
        # Resource-level viewer access, but object-level "none" on this specific heatmap.
        self._create_access_control(self.viewer_user, access_level="viewer")
        self._create_access_control(self.viewer_user, resource_id=str(self.heatmap.id), access_level="none")
        self.client.force_login(self.viewer_user)
        self.assertEqual(self.client.get(self._detail_url()).status_code, status.HTTP_403_FORBIDDEN)

    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.generate_heatmap_screenshot.delay")
    def test_create_blocked_without_resource_editor_access(self, mock_task):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.post(self._list_url(), data={"url": "https://example.com/blocked"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(SavedHeatmap.objects.filter(team=self.team, url="https://example.com/blocked").exists())
        mock_task.assert_not_called()

    @patch("products.web_analytics.backend.tasks.heatmap_screenshot.generate_heatmap_screenshot.delay")
    def test_create_allowed_with_resource_editor_access(self, mock_task):
        self._create_access_control(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)
        response = self.client.post(self._list_url(), data={"url": "https://example.com/allowed"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        self.assertTrue(SavedHeatmap.objects.filter(team=self.team, url="https://example.com/allowed").exists())

    def test_creator_list_filters_out_object_blocked_heatmap(self):
        # Creator sees their own heatmap; an object-level "none" on another user's heatmap excludes it.
        other_user = User.objects.create_and_join(self.organization, "otheruser@posthog.com", "testtest")
        other_heatmap = SavedHeatmap.objects.create(
            team=self.team,
            name="other heatmap",
            url="https://other.example.com",
            target_widths=[1024],
            created_by=other_user,
            status=SavedHeatmap.Status.COMPLETED,
        )
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="heatmap",
            resource_id=str(other_heatmap.id),
            access_level="none",
            organization_member=membership,
        )
        self.client.force_login(self.user)
        response = self.client.get(self._list_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [h["short_id"] for h in response.json()["results"]]
        self.assertIn(self.heatmap.short_id, names)
        self.assertNotIn(other_heatmap.short_id, names)

    def test_object_level_grant_works_through_project_default_none(self):
        # With the project default at "none", an object-level grant still lets the user read and
        # edit that specific heatmap, while other heatmaps stay blocked.
        other_heatmap = SavedHeatmap.objects.create(
            team=self.team,
            name="other heatmap",
            url="https://other.example.com",
            target_widths=[1024],
            created_by=self.user,
            status=SavedHeatmap.Status.COMPLETED,
        )
        self._create_project_default(access_level="none")
        self._create_access_control(self.viewer_user, resource_id=str(self.heatmap.id), access_level="editor")
        self.client.force_login(self.viewer_user)

        self.assertEqual(self.client.get(self._detail_url()).status_code, status.HTTP_200_OK)
        patch_response = self.client.patch(self._detail_url(), data={"name": "granted edit"}, format="json")
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)

        # A different heatmap without an object-level grant stays blocked.
        self.assertEqual(
            self.client.get(self._detail_url(other_heatmap.short_id)).status_code, status.HTTP_403_FORBIDDEN
        )

    def test_response_includes_user_access_level(self):
        self._create_access_control(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)
        response = self.client.get(self._detail_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["user_access_level"], "editor")
