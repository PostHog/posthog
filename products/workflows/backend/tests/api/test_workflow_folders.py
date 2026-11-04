from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.constants import AvailableFeature
from posthog.models.file_system.file_system import FileSystem
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.access_control.backend.facade.testing import create_access_control
from products.messaging.backend.facade.testing import create_message_template_for_test
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


class TestWorkflowFolders(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag = patch("posthoganalytics.feature_enabled", return_value=True)
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
            deleted = self.client.delete(f"{files_url}{entry['id']}/")
            self.assertEqual(deleted.status_code, {"none": 404, "viewer": 403, "editor": 200}[level], deleted.content)
            restored = self.client.post(
                f"{files_url}undo_delete/",
                {"items": [{"type": "message_template", "ref": template["id"]}]},
                format="json",
            )
            self.assertEqual(restored.status_code, 200 if level == "editor" else 400, restored.content)

    @patch("posthoganalytics.feature_enabled", return_value=False)
    def test_disabled_files_do_not_leave_an_empty_unfiled_tree(self, _flag: MagicMock) -> None:
        create_message_template_for_test(team_id=self.team.id, name="Synthetic email", content={})
        for path in ("Unfiled", "Unfiled/Email templates"):
            FileSystem.objects.create(team=self.team, path=path, depth=len(path.split("/")), type="folder")
        response = self.client.get(f"/api/projects/{self.team.id}/file_system/", {"search": "Unfiled"})
        self.assertEqual(response.json()["results"], [])
        FileSystem.objects.filter(team=self.team, type="message_template").delete()
        response = self.client.get(f"/api/projects/{self.team.id}/file_system/", {"path": "Unfiled"})
        self.assertEqual([entry["path"] for entry in response.json()["results"]], ["Unfiled"])

    @patch("posthoganalytics.feature_enabled", return_value=False)
    def test_disabled_project_files_leave_tree_search_and_unfiled_unchanged(self, _flag: MagicMock) -> None:
        with patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers"):
            workflow = HogFlow.objects.create(team=self.team, name="Synthetic welcome")
        template_id = create_message_template_for_test(team_id=self.team.id, name="Synthetic email", content={})
        FileSystem.objects.create(team=self.team, path="Unfiled", depth=1, type="folder")
        FileSystem.objects.create(team=self.team, path="Unfiled/Workflows", depth=2, type="folder")
        FileSystem.objects.create(team=self.team, path="Unfiled/Email templates", depth=2, type="folder")
        notebook = FileSystem.objects.create(
            team=self.team, path="Unfiled/Synthetic notebook", depth=2, type="notebook", ref="invented"
        )
        files_url = f"/api/projects/{self.team.id}/file_system/"
        for params in ({}, {"search": "Synthetic"}, {"parent": "Unfiled", "depth": "2"}):
            response = self.client.get(files_url, params)
            self.assertEqual(response.status_code, 200)
            rows = response.json()["results"]
            self.assertFalse(any(row["type"] in ("hog_flow", "message_template") for row in rows))
            self.assertFalse(any(row["path"] in ("Unfiled/Workflows", "Unfiled/Email templates") for row in rows))
            self.assertTrue(any(row["id"] == str(notebook.id) for row in rows))
        FileSystem.objects.filter(team=self.team, type__in=["hog_flow", "message_template"]).delete()
        response = self.client.get(f"{files_url}unfiled/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(FileSystem.objects.filter(team=self.team, type__in=["hog_flow", "message_template"]).exists())
        self.assertTrue(HogFlow.objects.filter(team=self.team, id=workflow.id).exists())
        self.assertEqual(
            self.client.get(f"/api/projects/{self.team.id}/messaging_templates/{template_id}/").status_code, 200
        )

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
    @patch("posthoganalytics.feature_enabled", return_value=False)
    def test_disabled_files_survive_recursive_folder_deletion(self, _flag: MagicMock, _reload: MagicMock) -> None:
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
        folder = self.client.get(files_url, {"path": "Campaigns"}).json()["results"][0]
        preview = self.client.post(f"{files_url}{folder['id']}/count/").json()
        self.assertEqual(preview["count"], 0)
        deleted = self.client.delete(f"{files_url}{folder['id']}/?recursive=true")
        self.assertEqual(deleted.status_code, 204, deleted.content)
        self.assertEqual(self.client.get(f"/api/projects/{self.team.id}/hog_flows/{workflow['id']}/").status_code, 200)
        self.assertEqual(
            self.client.get(f"/api/projects/{self.team.id}/messaging_templates/{template['id']}/").status_code, 200
        )
        with patch("posthoganalytics.feature_enabled", return_value=True):
            paths = {row["path"] for row in self.client.get(files_url).json()["results"]}
        self.assertTrue({"Campaigns", "Campaigns/Hidden workflow", "Campaigns/Hidden email"} <= paths)

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_deleting_workflow_through_project_files_records_activity(self, _reload: MagicMock) -> None:
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

    def test_email_template_can_be_created_and_moved_in_project_files(self) -> None:
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

    @patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers")
    def test_new_workflow_is_created_in_the_requested_project_folder(self, _reload: MagicMock) -> None:
        created = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/",
            {
                "name": "Renewal",
                "_create_in_folder": "Campaigns/Retention",
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
