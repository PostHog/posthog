from typing import Any, cast
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from drf_spectacular.generators import SchemaGenerator
from parameterized import parameterized
from rest_framework.routers import SimpleRouter

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.presentation.views.workflow_views import WorkflowViewViewSet


class TestWorkflowViewSchema(SimpleTestCase):
    def test_shared_view_patch_requires_a_version_and_allows_optional_changes(self) -> None:
        router = SimpleRouter()
        router.register("workflow_views", WorkflowViewViewSet, basename="workflow_views")
        schema = SchemaGenerator(patterns=router.urls).get_schema(request=None, public=True)
        operation = schema["paths"]["/workflow_views/{id}/"]["patch"]
        request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        request_schema = schema["components"]["schemas"][request_ref.rsplit("/", 1)[-1]]

        self.assertEqual(request_schema.get("required", []), ["version"])
        self.assertTrue(operation["requestBody"]["required"])
        self.assertEqual(set(request_schema["properties"]), {"version", "name", "state"})


class TestWorkflowViewAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/workflow_views/"
        self.flags = patch("posthoganalytics.feature_enabled", return_value=True)
        self.flags.start()
        self.addCleanup(self.flags.stop)

    def _create_view(self) -> dict[str, Any]:
        response = self.client.post(
            self.base_url,
            {"name": "Shared", "state": {"filters": [], "text": "", "columns": ["owner"]}},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def test_shared_view_can_be_created_selected_and_reloaded(self) -> None:
        saved_state = {
            "filters": [
                {"facet": "createdBy", "value": "me", "negated": False},
                {"facet": "kind", "value": "messaging", "negated": True},
            ],
            "text": "welcome",
            "columns": ["created_by", "health", "owner"],
        }
        created = self.client.post(self.base_url, {"name": "My workflows", "state": saved_state}, format="json")
        self.assertEqual(created.status_code, 201, created.content)
        view: dict[str, Any] = created.json()
        self.assertEqual(view["version"], 1)
        selected = self.client.get(f"{self.base_url}{view['id']}/")
        self.assertEqual(selected.status_code, 200, selected.content)
        self.assertEqual(selected.json()["state"], saved_state)
        reloaded = self.client.get(self.base_url)
        self.assertEqual(reloaded.status_code, 200, reloaded.content)
        self.assertEqual(reloaded.json()["results"], [view])

    def test_paging_through_shared_views_returns_every_view_once(self) -> None:
        first = self._create_view()
        second = self._create_view()
        first_page = self.client.get(self.base_url, {"limit": 1}).json()
        next_page = self.client.get(self.base_url, {"limit": 1, "offset": 1}).json()
        self.assertEqual(first_page["count"], 2)
        self.assertEqual(
            [row["id"] for row in first_page["results"] + next_page["results"]], [first["id"], second["id"]]
        )

    @parameterized.expand(
        [
            ("saved_views_off", "workflows-saved-views", False),
            ("list_off", "workflows-list-v2", False),
            ("unknown", "workflows-saved-views", None),
            ("failure", "workflows-saved-views", "raises"),
        ]
    )
    def test_all_endpoints_fail_closed_when_a_prerequisite_flag_is_unavailable(
        self, _case: str, disabled_flag: str, result: bool | str | None
    ) -> None:
        view = self._create_view()

        def evaluate(flag: str, *args: object, **kwargs: object) -> bool | None:
            if flag != disabled_flag:
                return True
            if result == "raises":
                raise RuntimeError("Flag evaluation unavailable")
            return cast(bool | None, result)

        with patch("posthoganalytics.feature_enabled", side_effect=evaluate):
            for method, path, data in [
                ("get", self.base_url, {}),
                ("get", f"{self.base_url}{view['id']}/", {}),
                ("post", self.base_url, {"name": "Blocked", "state": view["state"]}),
                ("patch", f"{self.base_url}{view['id']}/", {"name": "Blocked", "version": 1}),
                ("delete", f"{self.base_url}{view['id']}/?version=1", {}),
                ("post", f"{self.base_url}initialize/", {}),
                ("post", f"{self.base_url}restore_default/", {}),
            ]:
                with self.subTest(method=method, path=path):
                    response = getattr(self.client, method)(path, data, format="json")
                    self.assertEqual(response.status_code, 403, response.content)

        self.assertEqual(self.client.get(f"{self.base_url}{view['id']}/").json()["name"], "Shared")

    def test_shared_edits_and_deletes_require_the_latest_version(self) -> None:
        view = self._create_view()
        detail_url = f"{self.base_url}{view['id']}/"
        colleague = User.objects.create_and_join(self.organization, "colleague@example.com", None)
        self.client.force_login(colleague)
        their_snapshot = self.client.get(detail_url).json()
        changed_state = {
            "filters": [{"facet": "status", "value": "active", "negated": False}],
            "text": "invoice",
            "columns": [],
        }

        saved = self.client.patch(
            detail_url, {"state": changed_state, "version": their_snapshot["version"]}, format="json"
        )
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(saved.json()["version"], 2)
        self.client.force_login(self.user)

        stale_rename = self.client.patch(
            detail_url, {"name": "Stale rename", "version": view["version"]}, format="json"
        )
        self.assertEqual(stale_rename.status_code, 409, stale_rename.content)
        stale_delete = self.client.delete(f"{detail_url}?version={view['version']}")
        self.assertEqual(stale_delete.status_code, 409, stale_delete.content)
        self.assertEqual(self.client.get(detail_url).json()["state"], changed_state)

        missing_version = self.client.patch(detail_url, {"name": "Missing version"}, format="json")
        self.assertEqual(missing_version.status_code, 400, missing_version.content)
        nothing_to_change = self.client.patch(detail_url, {"version": 2}, format="json")
        self.assertEqual(nothing_to_change.status_code, 400, nothing_to_change.content)
        self.assertEqual(self.client.delete(detail_url).status_code, 400)
        incomplete_state = self.client.patch(detail_url, {"state": {"filters": []}, "version": 2}, format="json")
        self.assertEqual(incomplete_state.status_code, 400, incomplete_state.content)

        renamed = self.client.patch(detail_url, {"name": "Current rename", "version": 2}, format="json")
        self.assertEqual(renamed.status_code, 200, renamed.content)
        self.assertEqual(renamed.json()["state"], changed_state)
        self.assertEqual(renamed.json()["version"], 3)
        removed = self.client.delete(f"{detail_url}?version=3")
        self.assertEqual(removed.status_code, 204, removed.content)
        self.assertEqual(self.client.get(detail_url).status_code, 404)
        self.assertEqual(self.client.get(self.base_url).json()["results"], [])

    def test_my_workflows_initializes_once_and_deletion_survives_reload_until_restored(self) -> None:
        initialized = self.client.post(f"{self.base_url}initialize/", {}, format="json")
        self.assertEqual(initialized.status_code, 200, initialized.content)
        default = initialized.json()
        detail_url = f"{self.base_url}{default['id']}/"
        self.assertEqual(default["name"], "My workflows")
        self.assertEqual(default["default_key"], "my-workflows")
        original_state = {
            "filters": [{"facet": "createdBy", "value": "me", "negated": False}],
            "text": "",
            "columns": ["owner"],
        }
        self.assertEqual(default["state"], original_state)
        self.assertEqual(self.client.post(f"{self.base_url}initialize/", {}, format="json").json(), default)

        edited = self.client.patch(detail_url, {"name": "Renamed default", "version": 1}, format="json")
        self.assertEqual(edited.status_code, 200, edited.content)
        self.assertEqual(self.client.post(f"{self.base_url}restore_default/", {}, format="json").json(), edited.json())
        self.assertEqual(self.client.delete(f"{detail_url}?version=2").status_code, 204)
        self.assertEqual(self.client.get(detail_url).status_code, 404)
        self.assertEqual(self.client.get(self.base_url).json()["results"], [])

        another_viewer = User.objects.create_and_join(self.organization, "viewer@example.com", None)
        self.client.force_login(another_viewer)
        tombstone = self.client.post(f"{self.base_url}initialize/", {}, format="json").json()
        self.assertEqual(tombstone["id"], default["id"])
        self.assertTrue(tombstone["deleted"])
        self.assertEqual(tombstone["version"], 3)

        restored = self.client.post(f"{self.base_url}restore_default/", {}, format="json")
        self.assertEqual(restored.status_code, 200, restored.content)
        self.assertEqual(restored.json()["id"], default["id"])
        self.assertEqual(restored.json()["name"], "My workflows")
        self.assertEqual(restored.json()["state"], original_state)
        self.assertEqual(restored.json()["version"], 4)
        self.assertFalse(restored.json()["deleted"])
        stale_save = self.client.patch(detail_url, {"name": "Old snapshot", "version": 2}, format="json")
        self.assertEqual(stale_save.status_code, 409, stale_save.content)

    def test_an_individual_workflow_grant_does_not_grant_access_to_shared_views(self) -> None:
        view = self._create_view()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        member = User.objects.create_and_join(self.organization, "limited@example.com", None)
        membership = OrganizationMembership.objects.get(organization=self.organization, user=member)
        flow = HogFlow.objects.create(team=self.team, name="Permitted workflow", created_by=self.user)
        AccessControl.objects.create(team=self.team, resource="hog_flow", access_level="none")
        AccessControl.objects.create(
            team=self.team,
            resource="hog_flow",
            resource_id=str(flow.id),
            organization_member=membership,
            access_level="editor",
        )
        self.client.force_login(member)

        self.assertEqual(self.client.get(f"/api/projects/{self.team.pk}/hog_flows/{flow.id}/").status_code, 200)
        for method, path, data in [
            ("get", self.base_url, {}),
            ("get", f"{self.base_url}{view['id']}/", {}),
            ("post", f"{self.base_url}initialize/", {}),
            ("post", self.base_url, {"name": "Forbidden", "state": view["state"]}),
            ("patch", f"{self.base_url}{view['id']}/", {"name": "Forbidden", "version": 1}),
            ("delete", f"{self.base_url}{view['id']}/?version=1", {}),
            ("post", f"{self.base_url}restore_default/", {}),
        ]:
            with self.subTest(method=method, path=path):
                response = getattr(self.client, method)(path, data, format="json")
                self.assertEqual(response.status_code, 403, response.content)

    @parameterized.expand([("session", False), ("read_api_key", True)])
    def test_a_viewer_can_provision_only_the_fixed_default_and_cannot_resurrect_it(
        self, _case: str, use_api_key: bool
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        member = User.objects.create_and_join(self.organization, "read-only@example.com", None)
        AccessControl.objects.create(team=self.team, resource="hog_flow", access_level="viewer")
        key = generate_random_token_personal()
        if use_api_key:
            PersonalAPIKey.objects.create(
                user=member, label="Saved view reader", secure_value=hash_key_value(key), scopes=["hog_flow:read"]
            )

        def authenticate_viewer() -> None:
            self.client.logout()
            if use_api_key:
                self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")
            else:
                self.client.force_login(member)

        authenticate_viewer()
        initialized = self.client.post(
            f"{self.base_url}initialize/", {"name": "Cannot customize provisioning"}, format="json"
        )
        self.assertEqual(initialized.status_code, 200, initialized.content)
        default = initialized.json()
        detail_url = f"{self.base_url}{default['id']}/"
        self.assertEqual(default["name"], "My workflows")
        self.assertEqual(self.client.post(f"{self.base_url}initialize/", {}, format="json").json()["id"], default["id"])
        self.assertEqual(self.client.get(self.base_url).json()["results"], [default])
        for method, path, data in [
            ("post", self.base_url, {"name": "Forbidden", "state": default["state"]}),
            ("patch", detail_url, {"name": "Forbidden", "version": 1}),
            ("delete", f"{detail_url}?version=1", {}),
            ("post", f"{self.base_url}restore_default/", {}),
        ]:
            with self.subTest(method=method, path=path):
                response = getattr(self.client, method)(path, data, format="json")
                self.assertEqual(response.status_code, 403, response.content)

        self.client.credentials()
        editor_membership = OrganizationMembership.objects.get(organization=self.organization, user=self.user)
        AccessControl.objects.create(
            team=self.team, resource="hog_flow", access_level="editor", organization_member=editor_membership
        )
        self.client.force_login(self.user)
        removed = self.client.delete(f"{detail_url}?version=1")
        self.assertEqual(removed.status_code, 204, removed.content)
        authenticate_viewer()
        deleted = self.client.post(f"{self.base_url}initialize/", {}, format="json")
        self.assertEqual(deleted.status_code, 200, deleted.content)
        self.assertEqual(deleted.json()["id"], default["id"])
        self.assertTrue(deleted.json()["deleted"])
        self.assertEqual(self.client.get(self.base_url).json()["results"], [])
        self.assertEqual(self.client.post(f"{self.base_url}restore_default/", {}, format="json").status_code, 403)

    def test_views_follow_the_url_project_and_canonical_environment_without_crossing_tenants(self) -> None:
        view = self._create_view()
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        other_url = f"/api/projects/{other_team.pk}/workflow_views/"
        other_created = self.client.post(
            other_url,
            {"name": "Other", "state": view["state"], "team_id": self.team.pk, "default_key": "my-workflows"},
            format="json",
        )
        self.assertEqual(other_created.status_code, 201, other_created.content)
        other_view = other_created.json()
        self.assertIsNone(other_view["default_key"])
        self.assertEqual(self.client.get(other_url).json()["results"], [other_view])
        self.assertEqual(self.client.get(f"{self.base_url}{other_view['id']}/").status_code, 404)
        self.assertEqual(
            self.client.patch(
                f"{self.base_url}{other_view['id']}/", {"name": "Leak", "version": 1}, format="json"
            ).status_code,
            404,
        )
        self.assertEqual(self.client.delete(f"{self.base_url}{other_view['id']}/?version=1").status_code, 404)

        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child environment")
        child_url = f"/api/environments/{child.pk}/workflow_views/"
        self.assertEqual(self.client.get(child_url).json()["results"], [view])
        child_default = self.client.post(f"{child_url}initialize/", {}, format="json")
        self.assertEqual(child_default.status_code, 200, child_default.content)
        parent_default = self.client.post(f"{self.base_url}initialize/", {}, format="json")
        self.assertEqual(parent_default.json()["id"], child_default.json()["id"])
        self.assertEqual(self.client.get(f"{child_url}{other_view['id']}/").status_code, 404)

        foreign_org = Organization.objects.create(name="Unrelated organization")
        foreign_team = Team.objects.create(organization=foreign_org)
        self.assertEqual(self.client.get(f"/api/projects/{foreign_team.pk}/workflow_views/").status_code, 403)
        self.assertEqual(self.client.get(f"{self.base_url}{uuid4()}/").status_code, 404)
        self.assertEqual(self.client.get(f"{self.base_url}invalid-id/").status_code, 404)

    @parameterized.expand(
        [
            ("unsupported_facet", {"filters": [{"facet": "folder", "value": "Finance", "negated": False}]}),
            ("retired_type_facet", {"filters": [{"facet": "type", "value": "messaging", "negated": False}]}),
            ("unsupported_column", {"columns": ["folder"]}),
            ("invalid_filter", {"filters": [{"facet": "status", "negated": False}]}),
            ("filter_limit", {"filters": [{"facet": "status", "value": "active", "negated": False}] * 101}),
            ("column_limit", {"columns": ["owner"] * 7}),
            ("text_limit", {"text": "x" * 1001}),
        ]
    )
    def test_invalid_saved_state_is_rejected_without_replacing_the_shared_view(
        self, _case: str, state_changes: dict[str, Any]
    ) -> None:
        view = self._create_view()
        invalid_state = {**view["state"], **state_changes}
        create = self.client.post(self.base_url, {"name": "Invalid", "state": invalid_state}, format="json")
        self.assertEqual(create.status_code, 400, create.content)
        detail_url = f"{self.base_url}{view['id']}/"
        update = self.client.patch(detail_url, {"state": invalid_state, "version": 1}, format="json")
        self.assertEqual(update.status_code, 400, update.content)
        self.assertEqual(self.client.get(detail_url).json(), view)
