from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.api.file_system.access_levels import filter_workflow_files_by_access_level
from posthog.constants import AvailableFeature
from posthog.models.file_system.file_system import FileSystem
from posthog.models.file_system.file_system_shortcut import FileSystemShortcut
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.access_control.backend.facade.testing import create_access_control
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


class TestWorkflowFolders(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag = patch("posthoganalytics.feature_enabled", return_value=True)
        flag.start()
        self.addCleanup(flag.stop)

    def _local_flag_answer(self, local: bool | None) -> None:
        flag = patch(
            "posthoganalytics.feature_enabled",
            side_effect=lambda *args, only_evaluate_locally=False, **kwargs: local if only_evaluate_locally else True,
        )
        flag.start()
        self.addCleanup(flag.stop)

    def test_template_tree_permissions_follow_workflow_access(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        template = self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/",
            {"name": "Permission email", "type": "email"},
            format="json",
        ).json()
        files_url = f"/api/projects/{self.team.id}/file_system/"
        entry = self.client.get(files_url, {"type": "message_template", "ref": template["id"]}).json()["results"][0]
        for level in ("none", "viewer", "editor"):
            user = User.objects.create_and_join(self.organization, f"{level}@example.com", "invented-password")
            membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
            create_access_control(
                team_id=self.team.id, resource="hog_flow", access_level=level, organization_member_id=membership.id
            )
            self.client.force_login(user)
            rows = self.client.get(files_url, {"search": "Permission email"}).json()["results"]
            self.assertEqual(len(rows), 0 if level == "none" else 1)
            moved = self.client.post(
                f"{files_url}{entry['id']}/move/", {"new_path": "Campaigns/Permission email"}, format="json"
            )
            self.assertEqual(moved.status_code, {"none": 404, "viewer": 403, "editor": 200}[level], moved.content)
            patched = self.client.patch(
                f"{files_url}{entry['id']}/", {"path": f"Patched/{level}/Permission email"}, format="json"
            )
            self.assertEqual(patched.status_code, {"none": 404, "viewer": 403, "editor": 200}[level], patched.content)
            deleted = self.client.delete(f"{files_url}{entry['id']}/")
            self.assertEqual(deleted.status_code, {"none": 404, "viewer": 403, "editor": 200}[level], deleted.content)
            restored = self.client.post(
                f"{files_url}undo_delete/",
                {"items": [{"type": "message_template", "ref": template["id"]}]},
                format="json",
            )
            self.assertEqual(restored.status_code, 200 if level == "editor" else 400, restored.content)

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_private_workflow_files_follow_member_grants(self, _reload: MagicMock) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        workflow = HogFlow.objects.create(team=self.team, name="Private renewal", created_by=self.user)
        files_url = f"/api/projects/{self.team.id}/file_system/"
        entry = FileSystem.objects.get(team=self.team, type="hog_flow", ref=str(workflow.id))
        create_access_control(
            team_id=self.team.id, resource="hog_flow", resource_id=str(workflow.id), access_level="none"
        )
        member = User.objects.create_and_join(self.organization, "granted@example.com", "invented-password")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        create_access_control(
            team_id=self.team.id,
            resource="hog_flow",
            resource_id=str(workflow.id),
            access_level="editor",
            organization_member_id=membership.id,
        )
        self.client.force_login(member)

        rows = self.client.get(files_url, {"type": "hog_flow"}).json()["results"]
        self.assertEqual([row["id"] for row in rows], [str(entry.id)])
        moved = self.client.post(
            f"{files_url}{entry.id}/move/", {"new_path": "Campaigns/Private renewal"}, format="json"
        )
        self.assertEqual(moved.status_code, 200, moved.content)

        visible = filter_workflow_files_by_access_level(
            FileSystem.objects.filter(team=self.team),
            UserAccessControl(user=member, team=self.team),
            self.team.project_id,
        )
        filed_later = HogFlow.objects.create(team=self.team, name="Private launch", created_by=self.user)
        create_access_control(
            team_id=self.team.id, resource="hog_flow", resource_id=str(filed_later.id), access_level="none"
        )
        self.assertEqual(list(visible.filter(type="hog_flow").values_list("ref", flat=True)), [str(workflow.id)])

        revoked = User.objects.create_and_join(self.organization, "revoked@example.com", "invented-password")
        stale = FileSystemShortcut.objects.create(
            team=self.team, user=revoked, path="Private renewal", type="hog_flow", ref=str(workflow.id)
        )
        self.client.force_login(revoked)
        removed = self.client.delete(f"/api/projects/{self.team.id}/file_system_shortcut/{stale.id}/")
        self.assertEqual(removed.status_code, 204, removed.content)

        alias = self.client.post(
            files_url, {"path": "Private renewal copy", "type": "hog_flow", "ref": workflow.id.hex}, format="json"
        )
        self.assertEqual(alias.status_code, 201, alias.content)
        alias_deleted = self.client.delete(f"{files_url}{alias.json()['id']}/")
        self.assertEqual(alias_deleted.status_code, 404, alias_deleted.content)
        self.assertTrue(HogFlow.objects.filter(pk=workflow.id).exists())

    @parameterized.expand(
        [
            ("api_alias_deleted", "api", "alias"),
            ("legacy_alias_deleted", "upper_hex", "alias"),
            ("canonical_deleted_beside_upper_hex_alias", "upper_hex", "canonical"),
            ("canonical_deleted_beside_braced_alias", "braced", "canonical"),
            ("canonical_deleted_beside_urn_alias", "urn", "canonical"),
        ]
    )
    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_deleting_one_spelling_of_a_workflow_ref_keeps_the_workflow_and_the_other_file(
        self, _name: str, spelling: str, deleted_row: str, _reload: MagicMock
    ) -> None:
        workflow = HogFlow.objects.create(team=self.team, name="Renewal", created_by=self.user)
        files_url = f"/api/projects/{self.team.id}/file_system/"
        canonical_id = FileSystem.objects.get(team=self.team, type="hog_flow", ref=str(workflow.id)).id
        if spelling == "api":
            created = self.client.post(
                files_url, {"path": "Renewal copy", "type": "hog_flow", "ref": workflow.id.hex}, format="json"
            )
            self.assertEqual(created.status_code, 201, created.content)
            self.assertEqual(created.json()["ref"], str(workflow.id))
            alias_id = created.json()["id"]
        else:
            stored_ref = {
                "upper_hex": workflow.id.hex.upper(),
                "braced": f"{{{workflow.id}}}",
                "urn": f"urn:uuid:{workflow.id}",
            }[spelling]
            alias_id = FileSystem.objects.create(
                team=self.team, path="Renewal copy", depth=1, type="hog_flow", ref=stored_ref, shortcut=False
            ).id
        deleted_id, kept_id = (alias_id, canonical_id) if deleted_row == "alias" else (canonical_id, alias_id)

        deleted = self.client.delete(f"{files_url}{deleted_id}/")

        self.assertEqual(deleted.status_code, 204, deleted.content)
        self.assertTrue(HogFlow.objects.filter(pk=workflow.id).exists())
        self.assertTrue(FileSystem.objects.filter(pk=kept_id).exists())

    @parameterized.expand(
        [
            ("workflow_too_deep", "hog_flows", "_create_in_folder", "/".join(["Level"] * 51)),
            ("workflow_too_long", "hog_flows", "_create_in_folder", "a" * 4001),
            ("workflow_folder_alias_too_deep", "hog_flows", "folder", "/".join(["Level"] * 51)),
            ("workflow_folder_alias_too_long", "hog_flows", "folder", "a" * 4001),
            ("template_too_deep", "messaging_templates", "_create_in_folder", "/".join(["Level"] * 51)),
            ("template_too_long", "messaging_templates", "_create_in_folder", "a" * 4001),
        ]
    )
    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_create_in_folder_rejects_paths_past_the_tree_limits(
        self, _name: str, resource: str, field: str, folder: str, _reload: MagicMock
    ) -> None:
        payloads: dict[str, dict[str, Any]] = {
            "hog_flows": {
                "name": "Bounded",
                "actions": [{"id": "trigger", "name": "Trigger", "type": "trigger", "config": {"type": "manual"}}],
                "edges": [],
            },
            "messaging_templates": {"name": "Bounded", "type": "email"},
        }
        payload = payloads[resource]

        created = self.client.post(
            f"/api/projects/{self.team.id}/{resource}/", {**payload, field: folder}, format="json"
        )

        self.assertEqual(created.status_code, 400, created.content)
        self.assertEqual(created.json()["attr"], field)
        self.assertFalse(FileSystem.objects.filter(team=self.team, type="folder").exists())

    def test_disabled_files_do_not_leave_an_empty_unfiled_tree(self) -> None:
        self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/",
            {"name": "Synthetic email", "type": "email"},
            format="json",
        )
        for path in ("Unfiled", "Unfiled/Email templates"):
            FileSystem.objects.create(team=self.team, path=path, depth=len(path.split("/")), type="folder")
        with patch("posthoganalytics.feature_enabled", return_value=False):
            response = self.client.get(f"/api/projects/{self.team.id}/file_system/", {"search": "Unfiled"})
            self.assertEqual(response.json()["results"], [])
            FileSystem.objects.filter(team=self.team, type="message_template").delete()
            response = self.client.get(f"/api/projects/{self.team.id}/file_system/", {"path": "Unfiled"})
        self.assertEqual([entry["path"] for entry in response.json()["results"]], ["Unfiled"])

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_list_v2_off_writes_no_rows_and_hides_the_ones_filed_earlier(self, _reload: MagicMock) -> None:
        trigger = [{"id": "trigger", "name": "Trigger", "type": "trigger", "config": {"type": "manual"}}]
        hog_flows_url = f"/api/projects/{self.team.id}/hog_flows/"
        templates_url = f"/api/projects/{self.team.id}/messaging_templates/"
        filed = HogFlow.objects.create(team=self.team, name="Synthetic welcome", created_by=self.user)
        self.client.post(templates_url, {"name": "Synthetic email", "type": "email"}, format="json")
        workflow_files = FileSystem.objects.filter(team=self.team, type__in=["hog_flow", "message_template"])
        self.assertEqual(workflow_files.count(), 2)
        FileSystem.objects.create(team=self.team, path="Unfiled/Workflows", depth=2, type="folder")
        FileSystem.objects.create(team=self.team, path="Unfiled/Email templates", depth=2, type="folder")
        notebook = FileSystem.objects.create(
            team=self.team, path="Unfiled/Synthetic notebook", depth=2, type="notebook", ref="invented"
        )
        files_url = f"/api/projects/{self.team.id}/file_system/"

        with patch("posthoganalytics.feature_enabled", return_value=False):
            unfiled_workflow = self.client.post(
                hog_flows_url,
                {"name": "Synthetic dark", "_create_in_folder": "Campaigns", "actions": trigger, "edges": []},
                format="json",
            )
            unfiled_template = self.client.post(
                templates_url, {"name": "Synthetic dark email", "type": "email"}, format="json"
            )
            filed.name = "Synthetic renamed"
            filed.save()
            for params in ({}, {"search": "Synthetic"}, {"parent": "Unfiled", "depth": "2"}):
                response = self.client.get(files_url, params)
                self.assertEqual(response.status_code, 200)
                rows = response.json()["results"]
                self.assertFalse(any(row["type"] in ("hog_flow", "message_template") for row in rows))
                self.assertFalse(any(row["path"] in ("Unfiled/Workflows", "Unfiled/Email templates") for row in rows))
                self.assertTrue(any(row["id"] == str(notebook.id) for row in rows))
            ranked = self.client.get(f"{files_url}search/", {"search": "Synthetic"}).json()["results"]
            self.assertEqual([result["entry"]["id"] for result in ranked], [str(notebook.id)])
            self.assertEqual(self.client.get(f"{files_url}unfiled/").status_code, 200)

        self.assertEqual(unfiled_workflow.status_code, 201, unfiled_workflow.content)
        self.assertEqual(unfiled_template.status_code, 201, unfiled_template.content)
        self.assertEqual(
            sorted(workflow_files.values_list("path", flat=True)),
            ["Unfiled/Email templates/Synthetic email", "Unfiled/Workflows/Synthetic renamed"],
        )
        self.assertFalse(FileSystem.objects.filter(team=self.team, path="Campaigns").exists())

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_other_workflow_product_surfaces_are_not_filed_as_workflows(self, _reload: MagicMock) -> None:
        for origin_product in ("broadcasts", "loops"):
            created = self.client.post(
                f"/api/projects/{self.team.id}/hog_flows/",
                {
                    "name": "Other surface",
                    "origin_product": origin_product,
                    "actions": [{"id": "trigger", "name": "Trigger", "type": "trigger", "config": {"type": "manual"}}],
                    "edges": [],
                },
                format="json",
            )
            self.assertEqual(created.status_code, 201, created.content)
            files_url = f"/api/projects/{self.team.id}/file_system/"
            self.client.get(f"{files_url}unfiled/", {"type": "hog_flow"})
            self.assertEqual(
                self.client.get(files_url, {"type": "hog_flow", "ref": created.json()["id"]}).json()["results"], []
            )

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_disabled_files_survive_recursive_folder_deletion(self, _reload: MagicMock) -> None:
        workflow = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/",
            {
                "name": "Hidden workflow",
                "_create_in_folder": "Campaigns",
                "actions": [{"id": "trigger", "name": "Trigger", "type": "trigger", "config": {"type": "manual"}}],
                "edges": [],
            },
            format="json",
        ).json()
        template = self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/",
            {"name": "Hidden email", "type": "email", "_create_in_folder": "Campaigns"},
            format="json",
        ).json()
        files_url = f"/api/projects/{self.team.id}/file_system/"
        FileSystem.objects.create(team=self.team, path="Campaigns", depth=1, type="folder")
        with patch("posthoganalytics.feature_enabled", return_value=False):
            folder = self.client.get(files_url, {"path": "Campaigns"}).json()["results"][0]
            preview = self.client.post(f"{files_url}{folder['id']}/count/").json()
            self.assertEqual(preview["count"], 0)
            refused = self.client.delete(f"{files_url}{folder['id']}/?recursive=false")
            self.assertEqual(refused.status_code, 409, refused.content)
            deleted = self.client.delete(f"{files_url}{folder['id']}/?recursive=true")
            self.assertEqual(deleted.status_code, 204, deleted.content)
            self.assertEqual(
                self.client.get(f"/api/projects/{self.team.id}/hog_flows/{workflow['id']}/").status_code, 200
            )
            self.assertEqual(
                self.client.get(f"/api/projects/{self.team.id}/messaging_templates/{template['id']}/").status_code, 200
            )
        paths = {row["path"] for row in self.client.get(files_url).json()["results"]}
        self.assertTrue({"Campaigns", "Campaigns/Hidden workflow", "Campaigns/Hidden email"} <= paths)

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_deleting_workflow_through_the_project_tree_records_activity(self, _reload: MagicMock) -> None:
        created = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/",
            {
                "name": "Welcome",
                "actions": [{"id": "trigger", "name": "Trigger", "type": "trigger", "config": {"type": "manual"}}],
                "edges": [],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        workflow_id = created.json()["id"]
        files = self.client.get(
            f"/api/projects/{self.team.id}/file_system/", {"type": "hog_flow", "ref": workflow_id}
        ).json()["results"]
        with (
            patch("products.workflows.backend.services.hog_flow_activity.report_user_action") as report_action,
            self.captureOnCommitCallbacks(execute=True),
        ):
            deleted = self.client.delete(f"/api/projects/{self.team.id}/file_system/{files[0]['id']}/")
        self.assertTrue(any(call.args[1] == "hog_flow_deleted" for call in report_action.call_args_list))
        self.assertEqual(deleted.status_code, 200, deleted.content)
        activity = self.client.get(f"/api/projects/{self.team.id}/activity_log", {"scope": "HogFlow"}).json()["results"]
        self.assertTrue(any(entry["item_id"] == workflow_id and entry["activity"] == "deleted" for entry in activity))

    @parameterized.expand([("flag_on", True), ("local_evaluation_inconclusive", None)])
    def test_email_template_can_be_created_and_moved_in_the_project_tree(self, _name: str, local: bool | None) -> None:
        self._local_flag_answer(local)
        created = self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/",
            {"name": "Welcome email", "type": "email", "_create_in_folder": "Campaigns"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        files_url = f"/api/projects/{self.team.id}/file_system/"
        files = self.client.get(files_url, {"type": "message_template", "ref": created.json()["id"]}).json()["results"]
        self.assertEqual([file["path"] for file in files], ["Campaigns/Welcome email"])
        entry = files[0]
        moved = self.client.post(
            f"{files_url}{entry['id']}/move/", {"new_path": "Campaigns/Retention/Welcome email"}, format="json"
        )
        self.assertEqual(moved.status_code, 200, moved.content)
        reloaded = self.client.get(f"{files_url}{entry['id']}/")
        self.assertEqual(reloaded.json()["path"], "Campaigns/Retention/Welcome email")

    @parameterized.expand(
        [
            ("create_in_folder", "_create_in_folder", True),
            ("create_in_folder_local_evaluation_inconclusive", "_create_in_folder", None),
            ("folder", "folder", True),
            ("folder_local_evaluation_inconclusive", "folder", None),
        ]
    )
    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_new_workflow_is_created_in_the_requested_project_folder(
        self, _name: str, field: str, local: bool | None, _reload: MagicMock
    ) -> None:
        self._local_flag_answer(local)
        created = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/",
            {
                "name": "Renewal",
                field: "Campaigns/Retention",
                "actions": [{"id": "trigger", "name": "Trigger", "type": "trigger", "config": {"type": "manual"}}],
                "edges": [],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        files = self.client.get(
            f"/api/projects/{self.team.id}/file_system/", {"type": "hog_flow", "ref": created.json()["id"]}
        ).json()["results"]
        self.assertEqual([file["path"] for file in files], ["Campaigns/Retention/Renewal"])

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_folder_files_nothing_while_list_v2_is_off(self, _reload: MagicMock) -> None:
        with patch("posthoganalytics.feature_enabled", return_value=False):
            created = self.client.post(
                f"/api/projects/{self.team.id}/hog_flows/",
                {
                    "name": "Renewal",
                    "folder": "Campaigns/Retention",
                    "actions": [{"id": "trigger", "name": "Trigger", "type": "trigger", "config": {"type": "manual"}}],
                    "edges": [],
                },
                format="json",
            )
        self.assertEqual(created.status_code, 201, created.content)
        self.assertFalse(FileSystem.objects.filter(team=self.team, type="hog_flow", ref=created.json()["id"]).exists())
        self.assertFalse(FileSystem.objects.filter(team=self.team, path__startswith="Campaigns").exists())

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_workflow_move_survives_reload_and_rename(self, _reload: MagicMock) -> None:
        created = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/",
            {
                "name": "Welcome",
                "actions": [
                    {"id": "trigger", "name": "Trigger", "type": "trigger", "config": {"type": "manual"}},
                    {"id": "exit", "name": "Exit", "type": "exit", "config": {}},
                ],
                "edges": [{"from": "trigger", "to": "exit", "type": "continue"}],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        workflow_id = created.json()["id"]
        files_url = f"/api/projects/{self.team.id}/file_system/"
        files = self.client.get(files_url, {"type": "hog_flow"}).json()["results"]
        entry = next(item for item in files if item["ref"] == workflow_id)
        moved = self.client.post(f"{files_url}{entry['id']}/move/", {"new_path": "Campaigns/Welcome"}, format="json")
        self.assertEqual(moved.status_code, 200, moved.content)
        renamed = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{workflow_id}/", {"name": "Welcome back"}, format="json"
        )
        self.assertEqual(renamed.status_code, 200, renamed.content)
        reloaded = self.client.get(f"{files_url}{entry['id']}/")
        self.assertEqual(reloaded.json()["path"], "Campaigns/Welcome back")
        self.assertEqual(reloaded.json()["ref"], workflow_id)
