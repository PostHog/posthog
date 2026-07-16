import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.rbac.user_access_control import ACCESS_CONTROL_RESOURCES, model_to_resource

from products.web_analytics.backend.models import SavedHeatmap
from products.web_analytics.backend.test.test_heatmaps_api import INSERT_SINGLE_HEATMAP_EVENT

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

    def test_list_response_includes_user_access_level(self):
        # The list path preloads access controls via a separate batch code path
        # (UserAccessControlSerializerMixin) from retrieve — assert it independently so a
        # regression there (e.g. a silent `None`) is caught even if retrieve still passes.
        self._create_access_control(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)
        response = self.client.get(self._list_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = next(h for h in response.json()["results"] if h["short_id"] == self.heatmap.short_id)
        self.assertEqual(result["user_access_level"], "editor")


@pytest.mark.ee
class TestHeatmapAggregateQueryAccessControl(ClickhouseTestMixin, APIBaseTest):
    """
    Regression coverage for a privilege-escalation reported on the access-control PR: `heatmap`
    is the shared `scope_object` for both `SavedHeatmapViewSet` (persisted, object-bindable) and
    `HeatmapViewSet`/`LegacyHeatmapViewSet` (ClickHouse aggregate queries with no object to bind
    to). `AccessControlPermission`'s generic "has ANY specific-object grant for this resource
    type" fallback doesn't know the aggregate endpoints have no real object — so a viewer granted
    access to ONE saved heatmap could query aggregate click/event data for ANY url on the site.
    """

    def setUp(self):
        super().setUp()

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()

        self.viewer_user = User.objects.create_and_join(self.organization, "viewer2@posthog.com", "testtest")

        self.authorized_heatmap = SavedHeatmap.objects.create(
            team=self.team,
            name="authorized",
            url="https://example.com/authorized",
            data_url="https://example.com/authorized",
            target_widths=[1024],
            created_by=self.user,
            status=SavedHeatmap.Status.COMPLETED,
        )

        # Resource-level default is "none" — the only access this user has is the object-level
        # grant on `self.authorized_heatmap` below.
        AccessControl.objects.create(
            team=self.team, resource="heatmap", resource_id=None, access_level="none", organization_member=None
        )
        membership = OrganizationMembership.objects.get(user=self.viewer_user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="heatmap",
            resource_id=str(self.authorized_heatmap.id),
            access_level="viewer",
            organization_member=membership,
        )

        self._insert_heatmap_click(url="https://example.com/authorized")
        self._insert_heatmap_click(url="https://example.com/secret-unrelated-page")

    def _insert_heatmap_click(self, url: str) -> None:
        p = ClickhouseProducer()
        p.produce(
            topic=KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
            sql=INSERT_SINGLE_HEATMAP_EVENT,
            data={
                "session_id": "session1",
                "team_id": self.team.pk,
                "distinct_id": "user1",
                "timestamp": format_clickhouse_timestamp("2023-03-08T09:00:00"),
                "x": 10,
                "y": 20,
                "scale_factor": 16,
                "viewport_width": 100,
                "viewport_height": 100,
                "type": "click",
                "pointer_target_fixed": True,
                "current_url": url,
            },
        )

    def _query_aggregate(self, url_exact: str | None = None, url_pattern: str | None = None):
        self.client.force_login(self.viewer_user)
        params: dict[str, str] = {"type": "click", "date_from": "2023-03-01"}
        if url_exact is not None:
            params["url_exact"] = url_exact
        if url_pattern is not None:
            params["url_pattern"] = url_pattern
        return self.client.get(f"/api/environments/{self.team.pk}/heatmaps/", params)

    def test_object_grant_does_not_expose_aggregate_data_for_other_urls(self):
        response = self._query_aggregate(url_exact="https://example.com/secret-unrelated-page")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.json())

    def test_object_grant_still_allows_aggregate_data_for_the_authorized_url(self):
        # Permission-level check only: confirms the fix doesn't regress the legitimate case
        # (the point of adding object-level grants at all) by blocking the very url the user
        # was granted access to. Row counts depend on the heatmaps ClickHouse table, which is
        # exercised in test_heatmaps_api.py.
        response = self._query_aggregate(url_exact="https://example.com/authorized")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

    def test_object_grant_allows_query_url_differing_only_by_trailing_slash(self):
        # The aggregate query itself ignores a trailing slash (`trimRight(current_url, '/')`);
        # the permission check must normalize the same way or a legitimately-authorized url
        # gets a spurious 403.
        response = self._query_aggregate(url_exact="https://example.com/authorized/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

    def test_object_grant_allows_matching_url_pattern(self):
        response = self._query_aggregate(url_pattern=r"https://example\.com/authorized")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

    def test_object_grant_denies_non_matching_url_pattern(self):
        response = self._query_aggregate(url_pattern=r"https://example\.com/secret-unrelated-page")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.json())

    def test_events_drilldown_does_not_expose_other_urls(self):
        self.client.force_login(self.viewer_user)
        response = self.client.get(
            f"/api/environments/{self.team.pk}/heatmaps/events/"
            "?type=click&date_from=2023-03-01"
            "&url_exact=https://example.com/secret-unrelated-page"
            '&points=[{"x":0.1,"y":320}]'
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.json())
