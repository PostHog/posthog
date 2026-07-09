import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.rbac.user_access_control import ACCESS_CONTROL_RESOURCES, model_to_resource

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob
from products.workflows.backend.models.hog_flow_schedule import HogFlowSchedule

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


TRIGGER_ACTION = {
    "id": "trigger_node",
    "name": "trigger_1",
    "type": "trigger",
    "config": {
        "type": "event",
        "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]},
    },
}

# Any UUID — the parent workflow's object-level check rejects before the schedule is ever looked up.
MISSING_SCHEDULE_ID = "00000000-0000-0000-0000-000000000000"


class TestHogFlowResourceRegistration(SimpleTestCase):
    def test_hog_flow_is_a_controllable_resource(self):
        self.assertIn("hog_flow", ACCESS_CONTROL_RESOURCES)

    def test_hog_flow_model_maps_to_hog_flow_resource(self):
        self.assertEqual(model_to_resource(HogFlow()), "hog_flow")

    @parameterized.expand([("batch_job", HogFlowBatchJob), ("schedule", HogFlowSchedule)])
    def test_child_models_inherit_parent_hog_flow_resource(self, _name, model_cls):
        # Batch jobs and schedules have no route of their own, so access control on them resolves to the
        # parent workflow resource via the model_to_resource override.
        self.assertEqual(model_to_resource(model_cls()), "hog_flow")


@pytest.mark.ee
class TestHogFlowAccessControl(ClickhouseTestMixin, APIBaseTest):
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

        self.hog_flow = self._create_workflow(name="my_workflow")

    def _create_workflow(self, name="my_workflow", state=HogFlow.State.DRAFT) -> HogFlow:
        return HogFlow.objects.create(
            team=self.team,
            name=name,
            created_by=self.user,
            status=state,
            actions=[TRIGGER_ACTION],
            edges=[],
        )

    def _create_access_control(self, user, resource="hog_flow", resource_id=None, access_level="viewer"):
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        return AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=resource_id,
            access_level=access_level,
            organization_member=membership,
        )

    def _create_project_default(self, resource="hog_flow", access_level="none"):
        return AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=None,
            access_level=access_level,
            organization_member=None,
            role=None,
        )

    def _list_url(self) -> str:
        return f"/api/projects/{self.team.pk}/hog_flows"

    def _detail_url(self, flow_id=None) -> str:
        return f"/api/projects/{self.team.pk}/hog_flows/{flow_id or self.hog_flow.id}"

    def _create_payload(self, name="new_workflow") -> dict:
        return {"name": name, "actions": [TRIGGER_ACTION]}

    @parameterized.expand(
        [
            ("viewer", "get", status.HTTP_200_OK),
            ("viewer", "patch", status.HTTP_403_FORBIDDEN),
            ("viewer", "delete", status.HTTP_403_FORBIDDEN),
            ("editor", "get", status.HTTP_200_OK),
            ("editor", "patch", status.HTTP_200_OK),
            ("editor", "delete", status.HTTP_204_NO_CONTENT),
            ("none", "get", status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_access_level_matrix(self, access_level, method, expected_status):
        user = {"viewer": self.viewer_user, "editor": self.editor_user, "none": self.no_access_user}[access_level]
        self._create_access_control(user, access_level=access_level)
        self.client.force_login(user)

        if method == "get":
            response = self.client.get(self._detail_url())
        elif method == "patch":
            response = self.client.patch(self._detail_url(), data={"description": "updated"}, format="json")
        else:
            response = self.client.delete(self._detail_url())

        self.assertEqual(response.status_code, expected_status, getattr(response, "data", None))

    def test_user_access_level_in_retrieve_and_list(self):
        self._create_access_control(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        retrieve = self.client.get(self._detail_url())
        self.assertEqual(retrieve.status_code, status.HTTP_200_OK)
        self.assertEqual(retrieve.json()["user_access_level"], "editor")

        list_response = self.client.get(self._list_url())
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        results = list_response.json()["results"]
        self.assertTrue(results)
        self.assertTrue(all(row["user_access_level"] == "editor" for row in results))

    def test_project_default_none_blocks_retrieve(self):
        self._create_project_default(access_level="none")
        self.client.force_login(self.viewer_user)
        self.assertEqual(self.client.get(self._detail_url()).status_code, status.HTTP_403_FORBIDDEN)

    def test_object_level_none_blocks_and_excludes_from_list(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self._create_access_control(self.viewer_user, resource_id=str(self.hog_flow.id), access_level="none")
        self.client.force_login(self.viewer_user)

        self.assertEqual(self.client.get(self._detail_url()).status_code, status.HTTP_403_FORBIDDEN)
        ids = [row["id"] for row in self.client.get(self._list_url()).json()["results"]]
        self.assertNotIn(str(self.hog_flow.id), ids)

    def test_create_blocked_without_resource_editor_access(self):
        # A project default of "none" leaves the member below editor, so create is rejected.
        self._create_project_default(access_level="none")
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.post(self._list_url(), data=self._create_payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(HogFlow.objects.filter(team=self.team, name="new_workflow").exists())

    def test_create_allowed_with_resource_editor_access(self):
        self._create_access_control(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)
        response = self.client.post(self._list_url(), data=self._create_payload(name="editor_create"), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        self.assertTrue(HogFlow.objects.filter(team=self.team, name="editor_create").exists())

    @parameterized.expand(
        [
            ("batch_jobs_list", "get", "/batch_jobs", None),
            ("batch_jobs_create", "post", "/batch_jobs", {}),
            ("schedules_list", "get", "/schedules", None),
            ("schedules_create", "post", "/schedules", {"rrule": "FREQ=DAILY", "starts_at": "2026-01-01T00:00:00Z"}),
            ("schedule_update", "patch", f"/schedules/{MISSING_SCHEDULE_ID}", {"status": "paused"}),
            ("schedule_delete", "delete", f"/schedules/{MISSING_SCHEDULE_ID}", None),
            ("invocation_results", "get", "/invocation_results", None),
            ("invocations", "post", "/invocations", {"globals": {}}),
            (
                "graph",
                "patch",
                "/graph",
                {"operations": [{"op": "update_action", "id": "trigger_node", "patch": {"name": "x"}}]},
            ),
        ]
    )
    def test_custom_actions_enforce_object_level_access(self, _label, method, suffix, body):
        # An object-level "none" on the workflow must 403 every custom action — they all resolve the parent
        # workflow via self.get_object() first (and must not swallow the resulting PermissionDenied).
        self._create_access_control(self.no_access_user, resource_id=str(self.hog_flow.id), access_level="none")
        self.client.force_login(self.no_access_user)

        url = self._detail_url() + suffix
        client_method = getattr(self.client, method)
        response = client_method(url) if body is None else client_method(url, data=body, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, getattr(response, "data", response.content))

    def test_bulk_delete_only_deletes_editable_workflows(self):
        # Bulk delete must enforce object-level editor access, exactly like the single destroy path — not
        # mere visibility. A resource-level editor with an object override below editor keeps the workflow.
        archived_ok = self._create_workflow(name="archived_ok", state=HogFlow.State.ARCHIVED)
        archived_denied = self._create_workflow(name="archived_denied", state=HogFlow.State.ARCHIVED)
        archived_viewer = self._create_workflow(name="archived_viewer", state=HogFlow.State.ARCHIVED)
        self._create_access_control(self.editor_user, access_level="editor")
        self._create_access_control(self.editor_user, resource_id=str(archived_denied.id), access_level="none")
        # Visible but not editable: an object-specific viewer override must block deletion even though the
        # caller has resource-level editor access.
        self._create_access_control(self.editor_user, resource_id=str(archived_viewer.id), access_level="viewer")
        self.client.force_login(self.editor_user)

        response = self.client.post(
            f"{self._list_url()}/bulk_delete",
            data={"ids": [str(archived_ok.id), str(archived_denied.id), str(archived_viewer.id)]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, getattr(response, "data", response.content))
        self.assertEqual(response.json()["deleted"], 1)
        self.assertFalse(HogFlow.objects.filter(id=archived_ok.id).exists())
        self.assertTrue(HogFlow.objects.filter(id=archived_denied.id).exists())
        self.assertTrue(HogFlow.objects.filter(id=archived_viewer.id).exists())

    def test_user_blast_radius_requires_resource_level_access(self):
        # user_blast_radius is detail=False, so AccessControlPermission falls back to "access to any one
        # workflow". A viewer grant on a single workflow must not unlock the project-wide audience count:
        # the action requires resource-level workflow access.
        self._create_project_default(access_level="none")
        self._create_access_control(self.no_access_user, resource_id=str(self.hog_flow.id), access_level="viewer")
        self.client.force_login(self.no_access_user)

        response = self.client.post(
            f"{self._list_url()}/user_blast_radius",
            data={"filters": {"properties": []}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, getattr(response, "data", response.content))

    def test_org_admin_bypasses_object_level_denial(self):
        # self.user is the organization owner; object-level denials never apply to org admins.
        self._create_access_control(self.user, resource_id=str(self.hog_flow.id), access_level="none")
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self._detail_url()).status_code, status.HTTP_200_OK)

    def test_no_enforcement_without_access_control_feature(self):
        # Drop the entitlement — access control rows become inert and ordinary members regain access.
        self.organization.available_product_features = []
        self.organization.save()
        self._create_access_control(self.no_access_user, resource_id=str(self.hog_flow.id), access_level="none")
        self.client.force_login(self.no_access_user)
        self.assertEqual(self.client.get(self._detail_url()).status_code, status.HTTP_200_OK)
