from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any
from uuid import UUID

from posthog.test.base import APIBaseTest, NonAtomicBaseTest
from unittest.mock import patch

from django.db import DatabaseError, OperationalError, close_old_connections, connection, transaction
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.constants import AvailableFeature
from posthog.models.file_system.file_system import FileSystem, create_or_update_file
from posthog.models.file_system.file_system_shortcut import FileSystemShortcut
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.facade.testing import create_access_control, delete_access_control
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


class TestWorkflowFolders(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag = patch("posthoganalytics.feature_enabled", return_value=True)
        flag.start()
        self.addCleanup(flag.stop)

    def _local_flag_answer(self, local: bool | None) -> list[str]:
        remote_requests: list[str] = []

        def answer(key: str, *args: Any, only_evaluate_locally: bool = False, **kwargs: Any) -> bool | None:
            if only_evaluate_locally:
                return local
            remote_requests.append(key)
            return True

        flag = patch("posthoganalytics.feature_enabled", side_effect=answer)
        flag.start()
        self.addCleanup(flag.stop)
        return remote_requests

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

    @parameterized.expand(
        [
            ("object_denied_under_an_open_resource", None, "none", False, True),
            ("object_shared_under_a_closed_resource", "none", "viewer", True, False),
        ]
    )
    def test_workflow_files_list_by_each_workflow_own_grant(
        self, _name, resource_level, object_level, granted_visible, other_visible
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        granted = HogFlow.objects.create(team=self.team, name="Synthetic granted", created_by=self.user)
        other = HogFlow.objects.create(team=self.team, name="Synthetic other", created_by=self.user)
        for flow, name in ((granted, "Synthetic granted"), (other, "Synthetic other")):
            create_or_update_file(
                team=self.team,
                base_folder="Workflows",
                name=name,
                file_type="hog_flow",
                ref=str(flow.id),
                href=f"/workflows/{flow.id}",
                meta={},
                created_by_id=self.user.id,
            )
        member = User.objects.create_and_join(self.organization, "member@example.com", "invented-password")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        if resource_level:
            create_access_control(
                team_id=self.team.id,
                resource="hog_flow",
                access_level=resource_level,
                organization_member_id=membership.id,
            )
        create_access_control(
            team_id=self.team.id,
            resource="hog_flow",
            resource_id=str(granted.id),
            access_level=object_level,
            organization_member_id=membership.id,
        )
        self.client.force_login(member)

        rows = self.client.get(f"/api/projects/{self.team.id}/file_system/", {"type": "hog_flow"}).json()["results"]

        refs = {row["ref"] for row in rows}
        self.assertEqual((str(granted.id) in refs, str(other.id) in refs), (granted_visible, other_visible), refs)

    def test_a_template_creator_downgraded_to_viewer_cannot_delete_or_restore_it_from_the_tree(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        creator = User.objects.create_and_join(self.organization, "creator@example.com", "invented-password")
        membership = OrganizationMembership.objects.get(user=creator, organization=self.organization)
        editor_grant = create_access_control(
            team_id=self.team.id, resource="hog_flow", access_level="editor", organization_member_id=membership.id
        )
        self.client.force_login(creator)
        template = self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/",
            {"name": "Creator email", "type": "email"},
            format="json",
        ).json()
        files_url = f"/api/projects/{self.team.id}/file_system/"
        entry = self.client.get(files_url, {"type": "message_template", "ref": template["id"]}).json()["results"][0]
        delete_access_control(team_id=self.team.id, access_control_id=editor_grant)
        create_access_control(
            team_id=self.team.id, resource="hog_flow", access_level="viewer", organization_member_id=membership.id
        )

        deleted = self.client.delete(f"{files_url}{entry['id']}/")
        self.client.force_login(self.user)
        template_after_delete = self.client.get(f"/api/projects/{self.team.id}/messaging_templates/{template['id']}/")
        self.client.delete(f"{files_url}{entry['id']}/")
        self.client.force_login(creator)
        restored = self.client.post(
            f"{files_url}undo_delete/", {"items": [{"type": "message_template", "ref": template["id"]}]}, format="json"
        )
        self.client.force_login(self.user)
        template_after_restore = self.client.get(f"/api/projects/{self.team.id}/messaging_templates/{template['id']}/")

        self.assertEqual(
            [
                deleted.status_code,
                template_after_delete.status_code,
                restored.status_code,
                template_after_restore.status_code,
            ],
            [403, 200, 400, 404],
            [deleted.content, restored.content],
        )

    def test_workflow_viewers_cannot_place_or_unlink_a_workflow_file(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        template = self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/",
            {"name": "Shared email", "type": "email"},
            format="json",
        ).json()
        files_url = f"/api/projects/{self.team.id}/file_system/"
        entry = self.client.get(files_url, {"type": "message_template", "ref": template["id"]}).json()["results"][0]
        copy = {"path": "Copies/Shared email", "type": "message_template", "ref": template["id"]}
        placed_copy = self.client.post(files_url, copy, format="json")
        self.assertEqual(placed_copy.status_code, 201, placed_copy.content)
        FileSystem.objects.filter(pk=placed_copy.json()["id"]).update(shortcut=None)
        viewer = User.objects.create_and_join(self.organization, "viewer@example.com", "invented-password")
        membership = OrganizationMembership.objects.get(user=viewer, organization=self.organization)
        create_access_control(
            team_id=self.team.id, resource="hog_flow", access_level="viewer", organization_member_id=membership.id
        )
        self.client.force_login(viewer)

        placed = self.client.post(files_url, {**copy, "path": "Viewer/Shared email"}, format="json")
        shortcut = self.client.post(files_url, {**copy, "path": "Viewer/Shortcut", "shortcut": True}, format="json")
        promoted = self.client.patch(f"{files_url}{shortcut.json()['id']}/", {"shortcut": False}, format="json")
        folder = self.client.post(files_url, {"path": "Viewer/Folder", "type": "folder"}, format="json")
        retyped = self.client.patch(
            f"{files_url}{folder.json()['id']}/", {"type": "message_template", "ref": template["id"]}, format="json"
        )
        unlinked = self.client.delete(f"{files_url}{entry['id']}/")
        moved = self.client.post(
            f"{files_url}{placed_copy.json()['id']}/move/", {"new_path": "Viewer/Moved email"}, format="json"
        )

        self.assertEqual(
            [placed.status_code, promoted.status_code, retyped.status_code, unlinked.status_code, moved.status_code],
            [403, 403, 403, 403, 403],
            [placed.content, promoted.content, retyped.content, unlinked.content, moved.content],
        )
        rows = self.client.get(files_url, {"type": "message_template", "ref": template["id"]}).json()["results"]
        self.assertEqual(
            sorted(row["path"] for row in rows if not row["shortcut"]), sorted([entry["path"], "Copies/Shared email"])
        )

    @parameterized.expand(
        [
            ("file_by_editor", "file", "editor", 201, True),
            ("file_by_viewer", "file", "viewer", 403, False),
            ("file_by_key_without_workflow_scope", "file", "key_without_workflow_scope", 403, False),
            ("file_without_ref_by_editor", "file_without_ref", "editor", 400, False),
            (
                "file_without_ref_by_key_without_workflow_scope",
                "file_without_ref",
                "key_without_workflow_scope",
                400,
                False,
            ),
            (
                "retype_without_ref_by_key_without_workflow_scope",
                "retype_without_ref",
                "key_without_workflow_scope",
                400,
                False,
            ),
            ("shortcut_by_viewer", "shortcut", "viewer", 201, True),
            ("shortcut_by_member_without_access", "shortcut", "no_access", 403, False),
            ("shortcut_by_key_without_workflow_scope", "shortcut", "key_without_workflow_scope", 403, False),
            ("rename_by_editor", "rename", "editor", 200, True),
            ("rename_by_viewer", "rename", "viewer", 403, False),
            ("retype_by_editor", "retype", "editor", 200, True),
            ("retype_by_viewer", "retype", "viewer", 403, False),
            ("promote_by_editor", "promote", "editor", 200, True),
            ("promote_by_viewer", "promote", "viewer", 403, False),
            ("move_by_editor", "move", "editor", 200, True),
            ("move_by_viewer", "move", "viewer", 403, False),
            ("folder_move_by_editor", "folder_move", "editor", 200, True),
            ("folder_move_by_viewer", "folder_move", "viewer", 403, False),
            ("link_by_viewer", "link", "viewer", 200, True),
            ("link_by_key_without_workflow_scope", "link", "key_without_workflow_scope", 403, False),
            ("folder_link_by_viewer", "folder_link", "viewer", 200, True),
            ("folder_link_by_key_without_workflow_scope", "folder_link", "key_without_workflow_scope", 403, False),
            ("unlink_by_editor", "unlink", "editor", 204, True),
            ("unlink_by_viewer", "unlink", "viewer", 403, False),
            ("folder_delete_by_editor", "folder_delete", "editor", 204, True),
            ("folder_delete_by_viewer", "folder_delete", "viewer", 403, False),
            ("shortcut_folder_delete_by_viewer", "shortcut_folder_delete", "viewer", 204, True),
            (
                "shortcut_folder_delete_by_key_without_workflow_scope",
                "shortcut_folder_delete",
                "key_without_workflow_scope",
                403,
                False,
            ),
            ("delete_by_editor", "delete", "editor", 200, True),
            ("delete_by_viewer", "delete", "viewer", 403, False),
            ("restore_by_editor", "restore", "editor", 200, True),
            ("restore_by_key_without_workflow_scope", "restore", "key_without_workflow_scope", 403, False),
            ("unfiled_by_editor", "unfiled", "editor", 200, True),
            ("unfiled_by_viewer", "unfiled", "viewer", 200, False),
            ("unfiled_by_read_only_key", "unfiled", "read_only_key", 200, False),
        ]
    )
    def test_every_template_file_write_needs_access_to_change_the_template(
        self, _name: str, path: str, actor: str, expected_status: int, writes: bool
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        files_url = f"/api/projects/{self.team.id}/file_system/"
        templates_url = f"/api/projects/{self.team.id}/messaging_templates/"
        template_id = self.client.post(templates_url, {"name": "Guarded email", "type": "email"}, format="json").json()[
            "id"
        ]
        entry = FileSystem.objects.get(team=self.team, type="message_template", ref=template_id)
        inbox = FileSystem.objects.create(team=self.team, path="Inbox", depth=1, type="folder")
        copy = FileSystem.objects.create(
            team=self.team,
            path="Inbox/Guarded email",
            depth=2,
            type="message_template",
            ref=template_id,
            shortcut=False,
        )
        shortcut = FileSystem.objects.create(
            team=self.team, path="Starred email", depth=1, type="message_template", ref=template_id, shortcut=True
        )
        plain = FileSystem.objects.create(team=self.team, path="Plain", depth=1, type="folder")
        starred = FileSystem.objects.create(team=self.team, path="Starred", depth=1, type="folder")
        if path == "shortcut_folder_delete":
            FileSystem.objects.create(
                team=self.team,
                path="Starred/Guarded email",
                depth=2,
                type="message_template",
                ref=template_id,
                shortcut=True,
            )
        if path == "delete":
            copy.delete()
        if path == "restore":
            self.client.patch(f"{templates_url}{template_id}/", {"deleted": True}, format="json")
        if path == "unfiled":
            FileSystem.objects.filter(team=self.team, type="message_template").delete()
        requests: dict[str, tuple[str, str, dict | None]] = {
            "file": ("post", "", {"path": "Placed/Guarded email", "type": "message_template", "ref": template_id}),
            "shortcut": (
                "post",
                "",
                {"path": "Mine/Guarded email", "type": "message_template", "ref": template_id, "shortcut": True},
            ),
            "rename": ("patch", f"{entry.id}/", {"path": "Renamed/Guarded email"}),
            "retype": ("patch", f"{plain.id}/", {"type": "message_template", "ref": template_id}),
            "file_without_ref": ("post", "", {"path": "Placed/Guarded email", "type": "message_template", "ref": ""}),
            "retype_without_ref": ("patch", f"{plain.id}/", {"type": "message_template"}),
            "promote": ("patch", f"{shortcut.id}/", {"shortcut": False}),
            "move": ("post", f"{entry.id}/move/", {"new_path": "Moved/Guarded email"}),
            "folder_move": ("post", f"{inbox.id}/move/", {"new_path": "Archive/Inbox"}),
            "link": ("post", f"{entry.id}/link/", {"new_path": "Linked/Guarded email"}),
            "folder_link": ("post", f"{inbox.id}/link/", {"new_path": "Linked"}),
            "unlink": ("delete", f"{entry.id}/", None),
            "folder_delete": ("delete", f"{inbox.id}/?recursive=true", None),
            "shortcut_folder_delete": ("delete", f"{starred.id}/?recursive=true", None),
            "delete": ("delete", f"{entry.id}/", None),
            "restore": (
                "post",
                "undo_delete/",
                {"items": [{"type": "message_template", "ref": template_id, "path": "Restored/Guarded email"}]},
            ),
            "unfiled": ("get", "unfiled/?type=message_template", None),
        }
        headers: dict[str, str] = {}
        if "key" in actor:
            scopes = {
                "read_only_key": ["file_system:read", "hog_flow:read"],
                "key_without_workflow_scope": ["file_system:read", "file_system:write"],
            }[actor]
            headers["HTTP_AUTHORIZATION"] = f"Bearer {self.create_personal_api_key_with_scopes(scopes)}"
            self.client.logout()
        else:
            member = User.objects.create_and_join(self.organization, f"{actor}@example.com", "invented-password")
            membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
            create_access_control(
                team_id=self.team.id,
                resource="hog_flow",
                access_level={"editor": "editor", "viewer": "viewer", "no_access": "none"}[actor],
                organization_member_id=membership.id,
            )
            self.client.force_login(member)

        owner = APIClient()
        owner.force_login(self.user)

        def stored() -> tuple[list[tuple[str, bool]], int]:
            rows = FileSystem.objects.filter(team=self.team, type="message_template")
            template_status = owner.get(f"{templates_url}{template_id}/").status_code
            return sorted((row.path, bool(row.shortcut)) for row in rows), template_status

        before = stored()
        method, suffix, payload = requests[path]
        response = getattr(self.client, method)(f"{files_url}{suffix}", payload, format="json", **headers)

        self.assertEqual(response.status_code, expected_status, response.content)
        self.assertEqual(stored() != before, writes, stored())

    @parameterized.expand(
        [
            ("move", "post", "move/", {"new_path": "Archive/Inbox"}, 'INSERT INTO "posthog_filesystem"', 200),
            ("delete", "delete", "?recursive=true", None, '"posthog_filesystem"."ref" IN', 204),
        ]
    )
    def test_a_folder_change_leaves_template_files_that_arrive_after_its_access_check(
        self, _name: str, method: str, suffix: str, payload: dict | None, trigger: str, expected_status: int
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        template_id = self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/", {"name": "Late email", "type": "email"}, format="json"
        ).json()["id"]
        FileSystem.objects.filter(team=self.team, type="message_template", ref=template_id).delete()
        folder = FileSystem.objects.create(team=self.team, path="Inbox", depth=1, type="folder")
        dashboard_id = self.client.post(f"/api/projects/{self.team.id}/dashboards/", {"name": "Report"}).json()["id"]
        FileSystem.objects.create(team=self.team, path="Inbox/Report", depth=2, type="dashboard", ref=str(dashboard_id))
        viewer = User.objects.create_and_join(self.organization, "viewer@example.com", "invented-password")
        membership = OrganizationMembership.objects.get(user=viewer, organization=self.organization)
        create_access_control(
            team_id=self.team.id, resource="hog_flow", access_level="viewer", organization_member_id=membership.id
        )
        self.client.force_login(viewer)
        late_rows: list[FileSystem] = []
        filing_started = Event()

        def file_late_template(execute: Any, sql: str, params: Any, many: bool, context: dict[str, Any]) -> Any:
            result = execute(sql, params, many, context)
            if not filing_started.is_set() and trigger in sql and (method == "post" or "FOR UPDATE" in sql):
                filing_started.set()
                late_rows.append(
                    FileSystem.objects.create(
                        team=self.team, path="Inbox/Late email", depth=2, type="message_template", ref=template_id
                    )
                )
            return result

        with connection.execute_wrapper(file_late_template):
            changed = getattr(self.client, method)(
                f"/api/projects/{self.team.id}/file_system/{folder.id}/{suffix}", payload, format="json"
            )

        self.assertEqual(changed.status_code, expected_status, changed.content)
        late_rows[0].refresh_from_db()
        self.assertEqual(late_rows[0].path, "Inbox/Late email")

    @parameterized.expand(
        [
            (
                "folder_move",
                "folder",
                "post",
                "move/",
                {"new_path": "Archive/Inbox"},
                'SELECT "posthog_filesystem"."id" AS "pk" FROM',
            ),
            (
                "folder_root_move",
                "folder",
                "post",
                "move/",
                {"new_path": "Archive/Inbox"},
                'SELECT "posthog_filesystem"."team_id", "posthog_filesystem"."id", ',
            ),
            (
                "move",
                "child",
                "post",
                "move/",
                {"new_path": "Archive/Report"},
                'SELECT "posthog_filesystem"."team_id", "posthog_filesystem"."id", ',
            ),
            (
                "rename",
                "child",
                "patch",
                "",
                {"path": "Archive/Report"},
                'SELECT "posthog_filesystem"."team_id", "posthog_filesystem"."id", ',
            ),
            (
                "delete",
                "child",
                "delete",
                "",
                None,
                'SELECT "posthog_filesystem"."team_id", "posthog_filesystem"."id", ',
            ),
        ]
    )
    def test_a_file_write_checks_a_row_that_became_a_denied_template_before_its_lock(
        self, _name: str, target: str, method: str, suffix: str, payload: dict | None, read: str
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        template_id = self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/",
            {"name": "Hidden email", "type": "email"},
            format="json",
        ).json()["id"]
        FileSystem.objects.filter(team=self.team, type="message_template", ref=template_id).delete()
        folder = FileSystem.objects.create(team=self.team, path="Inbox", depth=1, type="folder")
        dashboard_id = self.client.post(f"/api/projects/{self.team.id}/dashboards/", {"name": "Report"}).json()["id"]
        child = FileSystem.objects.create(
            team=self.team, path="Inbox/Report", depth=2, type="dashboard", ref=str(dashboard_id), shortcut=False
        )
        member = User.objects.create_and_join(self.organization, "member@example.com", "invented-password")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        create_access_control(
            team_id=self.team.id, resource="hog_flow", access_level="none", organization_member_id=membership.id
        )
        self.client.force_login(member)
        retyped = Event()
        retargeted = folder if _name == "folder_root_move" else child
        path_before = retargeted.path

        def retype_after_the_read(execute: Any, sql: str, params: Any, many: bool, context: dict[str, Any]) -> Any:
            result = execute(sql, params, many, context)
            if not retyped.is_set() and sql.startswith(read) and "FOR UPDATE" not in sql:
                retyped.set()
                FileSystem.objects.filter(pk=retargeted.pk).update(type="message_template", ref=template_id)
            return result

        written = {"folder": folder, "child": child}[target]
        with connection.execute_wrapper(retype_after_the_read):
            response = getattr(self.client, method)(
                f"/api/projects/{self.team.id}/file_system/{written.id}/{suffix}", payload, format="json"
            )

        self.assertTrue(retyped.is_set())
        self.assertEqual(response.status_code, 403, response.content)
        retargeted.refresh_from_db()
        self.assertEqual(retargeted.path, path_before)

    @parameterized.expand(
        [
            ("folder_move", "post", "file_system/{folder_id}/move/", {"new_path": "Archive/Inbox"}, 0),
            (
                "file",
                "post",
                "file_system/",
                {"path": "Placed/Large email", "type": "message_template", "ref": "{template_id}"},
                0,
            ),
            ("folder_delete", "delete", "file_system/{folder_id}/?recursive=true", {}, 1),
            ("template_placement", "get", "messaging_templates/{template_id}/placement/", {}, 0),
        ]
    )
    def test_a_template_file_check_reads_only_the_template_access_fields(
        self, _name: str, method: str, suffix: str, payload: dict, template_locks: int
    ) -> None:
        template_id = self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/",
            {"name": "Large email", "type": "email", "content": {"email": {"subject": "Hi", "html": "<p>Hi</p>"}}},
            format="json",
        ).json()["id"]
        folder = FileSystem.objects.create(team=self.team, path="Inbox", depth=1, type="folder")
        FileSystem.objects.filter(team=self.team, type="message_template", ref=template_id).update(
            path="Inbox/Large email", depth=2
        )

        with CaptureQueriesContext(connection) as queries:
            response = getattr(self.client, method)(
                f"/api/projects/{self.team.id}/{suffix.format(folder_id=folder.id, template_id=template_id)}",
                {key: value.format(template_id=template_id) for key, value in payload.items()},
                **({} if method == "get" else {"format": "json"}),
            )

        self.assertIn(response.status_code, (200, 201), response.content)
        template_queries = [
            query["sql"] for query in queries.captured_queries if '"posthog_messagetemplate"' in query["sql"]
        ]
        self.assertTrue(template_queries)
        self.assertFalse(
            [sql for sql in template_queries if '"content"' in sql or '"draft_content"' in sql], template_queries
        )
        self.assertEqual(
            len([sql for sql in template_queries if sql.startswith("SELECT") and "FOR UPDATE" in sql]),
            template_locks,
            template_queries,
        )

    def test_a_folder_delete_reads_the_team_row_no_more_often_for_more_templates(self) -> None:
        def team_reads_for_a_folder_of(count: int, folder_path: str) -> int:
            folder = FileSystem.objects.create(team=self.team, path=folder_path, depth=1, type="folder")
            for index in range(count):
                self.client.post(
                    f"/api/projects/{self.team.id}/messaging_templates/",
                    {"name": f"Email {index}", "type": "email", "_create_in_folder": folder_path},
                    format="json",
                )
            with CaptureQueriesContext(connection) as queries:
                response = self.client.delete(f"/api/projects/{self.team.id}/file_system/{folder.id}/?recursive=true")
            self.assertEqual(response.status_code, 200, response.content)
            return len([query for query in queries.captured_queries if 'FROM "posthog_team"' in query["sql"]])

        self.assertEqual(team_reads_for_a_folder_of(3, "Many"), team_reads_for_a_folder_of(1, "One"))

    @parameterized.expand(
        [
            ("template_too_deep", "messaging_templates", "/".join(["Level"] * 51)),
            ("template_too_long", "messaging_templates", "a" * 4001),
            ("template_name_past_the_depth", "messaging_templates", "/".join(["Level"] * 50)),
            ("template_name_past_the_length", "messaging_templates", "a" * 4000),
        ]
    )
    def test_create_in_folder_rejects_paths_past_the_tree_limits(
        self, _name: str, resource: str, folder: str, name: str | None = "Bounded"
    ) -> None:
        payload = {"name": name, "type": "email"}

        created = self.client.post(
            f"/api/projects/{self.team.id}/{resource}/", {**payload, "_create_in_folder": folder}, format="json"
        )

        self.assertEqual(created.status_code, 400, created.content)
        self.assertEqual(created.json()["attr"], "_create_in_folder")
        self.assertFalse(FileSystem.objects.filter(team=self.team, type="folder").exists())

    def test_filing_a_template_without_renaming_it_checks_the_path_with_its_stored_name(self) -> None:
        templates_url = f"/api/projects/{self.team.id}/messaging_templates/"
        template = self.client.post(templates_url, {"name": "n" * 400, "type": "email"}, format="json").json()

        filed = self.client.patch(f"{templates_url}{template['id']}/", {"_create_in_folder": "a" * 3990}, format="json")

        self.assertEqual(filed.status_code, 400, filed.content)
        self.assertEqual(filed.json()["attr"], "_create_in_folder")

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

    @parameterized.expand([("list_v2_on", True), ("list_v2_off", False)])
    def test_a_template_placement_is_its_own_file_whether_or_not_the_tree_shows_it(self, _name, enabled) -> None:
        templates_url = f"/api/projects/{self.team.id}/messaging_templates/"
        filed = self.client.post(
            templates_url, {"name": "Synthetic email", "type": "email", "_create_in_folder": "Campaigns"}, format="json"
        ).json()
        FileSystem.objects.create(
            id=UUID(int=0),
            team=self.team,
            path="Shortcuts/Synthetic email",
            depth=2,
            type="message_template",
            ref=filed["id"],
            shortcut=True,
        )
        unfiled = self.client.post(templates_url, {"name": "Synthetic draft", "type": "email"}, format="json").json()
        FileSystem.objects.filter(team=self.team, type="message_template", ref=unfiled["id"]).delete()

        with patch("posthoganalytics.feature_enabled", return_value=enabled):
            placements = [
                self.client.get(f"{templates_url}{template['id']}/placement/") for template in (filed, unfiled)
            ]

        self.assertEqual([response.status_code for response in placements], [200, 200])
        self.assertEqual(
            [response.json() for response in placements], [{"path": "Campaigns/Synthetic email"}, {"path": None}]
        )

    @parameterized.expand([("root", "Synthetic email"), ("escaped_folder", "Spring\\/Summer/Synthetic email")])
    def test_undoing_a_template_delete_with_the_flag_off_puts_it_back_at_its_placement(self, _name, path) -> None:
        templates_url = f"/api/projects/{self.team.id}/messaging_templates/"
        template_id = self.client.post(
            templates_url, {"name": "Synthetic email", "type": "email"}, format="json"
        ).json()["id"]
        FileSystem.objects.filter(team=self.team, type="message_template", ref=template_id).update(
            path=path, depth=len(path.replace("\\/", "").split("/"))
        )

        with patch("posthoganalytics.feature_enabled", return_value=False):
            placement = self.client.get(f"{templates_url}{template_id}/placement/").json()["path"]
            deleted = self.client.patch(f"{templates_url}{template_id}/", {"deleted": True}, format="json")
            restored = self.client.post(
                f"/api/projects/{self.team.id}/file_system/undo_delete/",
                {"items": [{"type": "message_template", "ref": template_id, "path": placement}]},
                format="json",
            )

        self.assertEqual([deleted.status_code, restored.status_code], [200, 200], [deleted.content, restored.content])
        self.assertEqual(
            list(
                FileSystem.objects.filter(team=self.team, type="message_template", ref=template_id).values_list(
                    "path", "depth"
                )
            ),
            [(path, len(path.replace("\\/", "").split("/")))],
        )

    @parameterized.expand([("hog_flow_read", ["hog_flow:read"], 200), ("other_scope", ["feature_flag:read"], 403)])
    def test_a_template_placement_reads_with_a_key_that_holds_the_workflow_read_scope(
        self, _name, scopes, expected_status
    ) -> None:
        templates_url = f"/api/projects/{self.team.id}/messaging_templates/"
        filed = self.client.post(
            templates_url, {"name": "Synthetic email", "type": "email", "_create_in_folder": "Campaigns"}, format="json"
        ).json()
        key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()

        response = self.client.get(f"{templates_url}{filed['id']}/placement/", HTTP_AUTHORIZATION=f"Bearer {key}")

        self.assertEqual(response.status_code, expected_status, response.content)
        if expected_status == 200:
            self.assertEqual(response.json(), {"path": "Campaigns/Synthetic email"})

    def test_a_folder_delete_lists_the_team_surfaces_once_however_many_types_it_holds(self) -> None:
        templates_url = f"/api/projects/{self.team.id}/messaging_templates/"

        def surface_reads_deleting(folder: str, with_workflow: bool) -> int:
            self.client.post(
                templates_url, {"name": f"{folder} email", "type": "email", "_create_in_folder": folder}, format="json"
            )
            if with_workflow:
                workflow = HogFlow.objects.create(
                    team=self.team, name=f"{folder} flow", status=HogFlow.State.ARCHIVED, created_by=self.user
                )
                FileSystem.objects.filter(team=self.team, type="hog_flow", ref=str(workflow.id)).update(
                    path=f"{folder}/{workflow.name}", depth=2
                )
            entry = FileSystem.objects.create(team=self.team, path=folder, depth=1, type="folder")
            with CaptureQueriesContext(connection) as queries:
                response = self.client.delete(f"/api/projects/{self.team.id}/file_system/{entry.id}/")
            self.assertEqual(response.status_code, 200, response.content)
            self.assertFalse(FileSystem.objects.filter(team=self.team, path__startswith=f"{folder}/").exists())
            return sum(
                '"posthog_filesystem"."surface" IS NOT NULL' in query["sql"] for query in queries.captured_queries
            )

        self.assertEqual(surface_reads_deleting("Mixed", True), surface_reads_deleting("Single", False))

    @parameterized.expand(
        [
            (
                "template_file_system_scopes_only",
                "messaging_templates",
                ["file_system:read", "file_system:write"],
                403,
                200,
            ),
            ("template_with_write_scope", "messaging_templates", ["file_system:write", "hog_flow:write"], 200, 404),
        ]
    )
    def test_tree_delete_of_a_workflow_object_needs_the_workflow_write_scope(
        self, _name: str, endpoint: str, scopes: list[str], delete_status: int, object_status: int
    ) -> None:
        object_id = self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/",
            {"name": "Scoped email", "type": "email"},
            format="json",
        ).json()["id"]
        file = self.client.get(
            f"/api/projects/{self.team.id}/file_system/", {"type": "message_template", "ref": object_id}
        ).json()["results"][0]
        key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()

        deleted = self.client.delete(
            f"/api/projects/{self.team.id}/file_system/{file['id']}/", HTTP_AUTHORIZATION=f"Bearer {key}"
        )

        self.assertEqual(deleted.status_code, delete_status, deleted.content)
        self.client.force_login(self.user)
        stored = self.client.get(f"/api/projects/{self.team.id}/{endpoint}/{object_id}/")
        self.assertEqual(stored.status_code, object_status, stored.content)

    @parameterized.expand(
        [
            ("list", "get", "file_system/?type=message_template", None, 200),
            ("starred", "get", "file_system_shortcut/", None, 200),
            ("delete", "delete", "file_system/{file_id}/", None, 404),
            ("move", "post", "file_system/{file_id}/move/", {"new_path": "Moved/Sibling email"}, 404),
            ("retype", "patch", "file_system/{folder_id}/", {"type": "message_template", "ref": "{template_id}"}, 403),
        ]
    )
    def test_a_key_scoped_to_one_environment_reaches_only_its_own_template_files(
        self, _name: str, method: str, path: str, payload: dict | None, expected_status: int
    ) -> None:
        sibling_team = Team.objects.create(organization=self.organization, project=self.team.project)
        template_id = self.client.post(
            f"/api/projects/{sibling_team.id}/messaging_templates/",
            {"name": "Sibling email", "type": "email"},
            format="json",
        ).json()["id"]
        file = FileSystem.objects.get(team=sibling_team, type="message_template", ref=template_id)
        original_path = file.path
        FileSystemShortcut.objects.create(
            team=sibling_team, user=self.user, path="Sibling email", type="message_template", ref=template_id
        )
        folder = FileSystem.objects.create(team=sibling_team, path="Sibling folder", depth=1, type="folder")
        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Scoped key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["file_system:read", "file_system:write", "file_system_shortcut:read", "hog_flow:write"],
            scoped_teams=[self.team.id],
        )
        self.client.logout()

        response = getattr(self.client, method)(
            f"/api/projects/{self.team.id}/{path.format(file_id=file.id, folder_id=folder.id)}",
            {key: value.format(template_id=template_id) for key, value in payload.items()} if payload else None,
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )

        self.assertEqual(response.status_code, expected_status, response.content)
        self.assertNotIn(template_id, response.content.decode())
        file.refresh_from_db()
        self.assertEqual(file.path, original_path)
        self.assertEqual(FileSystem.objects.filter(team=sibling_team, type="message_template").count(), 1)
        self.client.force_login(self.user)
        stored = self.client.get(f"/api/projects/{sibling_team.id}/messaging_templates/{template_id}/")
        self.assertEqual(stored.status_code, 200, stored.content)

    @parameterized.expand(
        [
            (
                "file",
                "post",
                "file_system/",
                {"path": "Filed email", "type": "message_template", "ref": "{template_id}"},
            ),
            ("unlink", "delete", "file_system/{file_id}/", None),
            ("move", "post", "file_system/{file_id}/move/", {"new_path": "Moved/Welcome"}),
        ]
    )
    def test_a_key_without_the_workflow_write_scope_cannot_change_template_files(
        self, _name: str, method: str, path: str, payload: dict | None
    ) -> None:
        template_id = self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/", {"name": "Welcome", "type": "email"}, format="json"
        ).json()["id"]
        file = FileSystem.objects.get(team=self.team, type="message_template", ref=template_id)
        original_path = file.path
        FileSystem.objects.create(team=self.team, path="Copy email", depth=1, type="message_template", ref=template_id)
        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="File system key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["file_system:read", "file_system:write"],
        )
        self.client.logout()

        response = getattr(self.client, method)(
            f"/api/projects/{self.team.id}/{path.format(file_id=file.id)}",
            {key: value.format(template_id=template_id) for key, value in payload.items()} if payload else None,
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )

        self.assertEqual(response.status_code, 403, response.content)
        file.refresh_from_db()
        self.assertEqual(file.path, original_path)
        self.assertEqual(FileSystem.objects.filter(team=self.team, type="message_template", ref=template_id).count(), 2)

    @parameterized.expand(
        [
            ("file_system_scopes_only", ["file_system:read", "file_system:write"], 403, 404),
            ("with_write_scope", ["file_system:write", "hog_flow:write"], 200, 200),
        ]
    )
    def test_tree_restore_of_a_template_needs_the_workflow_write_scope(
        self, _name: str, scopes: list[str], restore_status: int, template_status: int
    ) -> None:
        template_id = self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/",
            {"name": "Restored email", "type": "email"},
            format="json",
        ).json()["id"]
        files_url = f"/api/projects/{self.team.id}/file_system/"
        file = self.client.get(files_url, {"type": "message_template", "ref": template_id}).json()["results"][0]
        self.assertEqual(self.client.delete(f"{files_url}{file['id']}/").status_code, 200)
        key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()

        restored = self.client.post(
            f"{files_url}undo_delete/",
            {"items": [{"type": "message_template", "ref": template_id}]},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {key}",
        )

        self.assertEqual(restored.status_code, restore_status, restored.content)
        self.client.force_login(self.user)
        template = self.client.get(f"/api/projects/{self.team.id}/messaging_templates/{template_id}/")
        self.assertEqual(template.status_code, template_status, template.content)

    @parameterized.expand([("flag_on", True), ("local_evaluation_inconclusive", None)])
    def test_email_template_can_be_created_and_moved_in_the_project_tree(self, _name: str, local: bool | None) -> None:
        self._local_flag_answer(local)
        created = self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/",
            {"name": "Welcome email", "type": "email", "_create_in_folder": "Campaigns"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        self._local_flag_answer(True)
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
            ("tree", "file_system/", {}),
            ("search", "file_system/", {"search": "Synthetic"}),
            ("recents", "file_system/", {"order_by": "-last_viewed_at"}),
            ("frequent", "file_system/frequent/", {}),
            ("unfiled", "file_system/unfiled/", {}),
            ("shortcuts", "file_system_shortcut/", {}),
        ]
    )
    def test_file_reads_never_wait_on_remote_flag_evaluation(self, _name: str, path: str, params: dict) -> None:
        filed = HogFlow.objects.create(team=self.team, name="Synthetic filed", created_by=self.user)
        unfiled = HogFlow.objects.create(team=self.team, name="Synthetic unfiled", created_by=self.user)
        FileSystem.objects.filter(team=self.team, type="hog_flow", ref=str(unfiled.id)).delete()
        FileSystemShortcut.objects.create(
            team=self.team, user=self.user, path="Synthetic filed", type="hog_flow", ref=str(filed.id)
        )
        remote_requests = self._local_flag_answer(None)

        response = self.client.get(f"/api/projects/{self.team.id}/{path}", params)

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        rows = body.get("results", []) if isinstance(body, dict) else body
        self.assertFalse({str(filed.id), str(unfiled.id)} & {row.get("ref") for row in rows})
        self.assertFalse(FileSystem.objects.filter(team=self.team, type="hog_flow", ref=str(unfiled.id)).exists())
        self.assertNotIn("workflows-list-v2", remote_requests)

    @parameterized.expand(
        [
            ("recents", "file_system/", {"order_by": "-last_viewed_at"}),
            ("frequent", "file_system/frequent/", {}),
            ("one_item_listing", "file_system/", {"type": "message_template", "limit": 1}),
            ("one_item_listing_by_an_admin_of_shared_files", "file_system/", {"type": "message_template", "limit": 1}),
        ]
    )
    def test_file_reads_resolve_access_without_reading_every_template_file(self, name, path, params) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        templates_url = f"/api/projects/{self.team.id}/messaging_templates/"
        viewed, *unviewed = [
            self.client.post(templates_url, {"name": f"Synthetic email {i}", "type": "email"}, format="json").json()[
                "id"
            ]
            for i in range(11)
        ]
        if name.endswith("admin_of_shared_files"):
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()
            for template_id in unviewed:
                create_access_control(
                    team_id=self.team.id, resource="hog_flow", resource_id=template_id, access_level="viewer"
                )
        self.client.post(
            f"/api/projects/{self.team.id}/file_system/log_view/",
            {"type": "message_template", "ref": viewed},
            format="json",
        )
        file_rows_read: list[int] = []

        def count_file_rows(execute: Any, sql: str, params: Any, many: bool, context: dict[str, Any]) -> Any:
            result = execute(sql, params, many, context)
            if 'FROM "posthog_filesystem"' in sql:
                file_rows_read.append(context["cursor"].rowcount)
            return result

        with connection.execute_wrapper(count_file_rows):
            response = self.client.get(f"/api/projects/{self.team.id}/{path}", params)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertLess(max(file_rows_read), len(unviewed), file_rows_read)


class TestWorkflowFilesUnderRealTransactions(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        flag = patch("posthoganalytics.feature_enabled", return_value=True)
        flag.start()
        self.addCleanup(flag.stop)
        self.client = APIClient()
        self.client.force_login(self.user)

    def _refuse_file_rows(self, operation: str = "INSERT") -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE FUNCTION refuse_file_row() RETURNS trigger LANGUAGE plpgsql AS "
                "$$ BEGIN RAISE EXCEPTION 'file row refused'; END $$"
            )
            cursor.execute(
                f"CREATE TRIGGER refuse_file_row BEFORE {operation} ON posthog_filesystem "
                "FOR EACH ROW EXECUTE FUNCTION refuse_file_row()"
            )

        def drop() -> None:
            with connection.cursor() as cursor:
                cursor.execute("DROP TRIGGER IF EXISTS refuse_file_row ON posthog_filesystem")
                cursor.execute("DROP FUNCTION IF EXISTS refuse_file_row()")

        self.addCleanup(drop)

    def _wait_for_blocked_backends(self, count: int) -> None:
        for _ in range(200):
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND cardinality(pg_blocking_pids(pid)) > 0"
                )
                if cursor.fetchone()[0] >= count:
                    return
            Event().wait(0.05)
        self.fail(f"expected {count} blocked backends")

    @parameterized.expand([("create",), ("update",), ("restore",)])
    def test_filing_a_template_into_a_folder_asks_the_flag_service_before_taking_any_lock(self, operation: str) -> None:
        remote_answers_in_a_transaction: list[bool] = []

        def answer(key: str, *args: Any, only_evaluate_locally: bool = False, **kwargs: Any) -> bool | None:
            if only_evaluate_locally:
                return None
            remote_answers_in_a_transaction.append(connection.in_atomic_block)
            return True

        flag = patch("posthoganalytics.feature_enabled", side_effect=answer)
        flag.start()
        self.addCleanup(flag.stop)
        templates_url = f"/api/projects/{self.team.id}/messaging_templates/"
        filed = {"name": "Folder email", "type": "email", "_create_in_folder": "Campaigns"}
        if operation == "create":
            response = self.client.post(templates_url, filed, format="json")
            template_id = response.json()["id"]
        else:
            template_id = self.client.post(
                templates_url, {"name": "Folder email", "type": "email"}, format="json"
            ).json()["id"]
            FileSystem.objects.filter(team=self.team, type="message_template", ref=template_id).delete()
            remote_answers_in_a_transaction.clear()
            if operation == "update":
                response = self.client.patch(f"{templates_url}{template_id}/", filed, format="json")
            else:
                self.client.patch(f"{templates_url}{template_id}/", {"deleted": True}, format="json")
                remote_answers_in_a_transaction.clear()
                response = self.client.post(
                    f"/api/projects/{self.team.id}/file_system/undo_delete/",
                    {"items": [{"type": "message_template", "ref": template_id, "path": "Campaigns/Folder email"}]},
                    format="json",
                )

        self.assertIn(response.status_code, (200, 201), response.content)
        paths = FileSystem.objects.filter(team=self.team, type="message_template", ref=template_id).values_list(
            "path", flat=True
        )
        self.assertEqual(list(paths), ["Campaigns/Folder email"])
        self.assertTrue(remote_answers_in_a_transaction)
        self.assertNotIn(True, remote_answers_in_a_transaction)

    def test_a_folder_move_and_a_file_sync_of_the_same_object_both_finish(self) -> None:
        dashboard_id = str(
            self.client.post(f"/api/projects/{self.team.id}/dashboards/", {"name": "Report"}).json()["id"]
        )
        FileSystem.objects.filter(team=self.team, type="dashboard", ref=dashboard_id).delete()
        folder = FileSystem.objects.create(team=self.team, path="Inbox", depth=1, type="folder")
        rows = sorted(
            (
                FileSystem.objects.create(team=self.team, path="Inbox/x", depth=2, type="dashboard", ref=dashboard_id)
                for _ in range(3)
            ),
            key=lambda row: row.id,
        )
        for row, path in zip(rows, ["Inbox/c", "Inbox/b", "Inbox/a"]):
            FileSystem.objects.filter(pk=row.pk).update(path=path)
        middle_locked = Event()
        release_middle = Event()

        def hold_the_middle_row() -> None:
            close_old_connections()
            try:
                with transaction.atomic(), connection.cursor() as cursor:
                    cursor.execute("SELECT id FROM posthog_filesystem WHERE id = %s FOR UPDATE", [rows[1].id])
                    middle_locked.set()
                    release_middle.wait(timeout=10)
            finally:
                close_old_connections()

        def sync_the_files() -> None:
            close_old_connections()
            try:
                with transaction.atomic():
                    create_or_update_file(
                        team=self.team,
                        base_folder="Unfiled/Dashboards",
                        name="Report v2",
                        file_type="dashboard",
                        ref=dashboard_id,
                        href=f"/dashboard/{dashboard_id}",
                        meta={},
                    )
            finally:
                close_old_connections()

        def move_the_folder() -> Any:
            close_old_connections()
            try:
                return self.client.post(
                    f"/api/projects/{self.team.id}/file_system/{folder.id}/move/",
                    {"new_path": "Archive/Inbox"},
                    format="json",
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=3) as executor:
            holder = executor.submit(hold_the_middle_row)
            self.assertTrue(middle_locked.wait(timeout=5))
            try:
                sync = executor.submit(sync_the_files)
                self._wait_for_blocked_backends(1)
                move = executor.submit(move_the_folder)
                self._wait_for_blocked_backends(2)
            finally:
                release_middle.set()
            holder.result(timeout=15)
            sync.result(timeout=15)
            moved = move.result(timeout=15)

        self.assertEqual(moved.status_code, 200, moved.content)
        self.assertEqual(
            sorted(
                FileSystem.objects.filter(team=self.team, type="dashboard", ref=dashboard_id).values_list(
                    "path", flat=True
                )
            ),
            ["Archive/Inbox/Report v2"] * 3,
        )

    def test_a_folder_move_leaves_its_team_free_for_new_rows(self) -> None:
        folder = FileSystem.objects.create(team=self.team, path="Inbox", depth=1, type="folder")
        FileSystem.objects.create(team=self.team, path="Inbox/Reports", depth=2, type="folder")
        outcomes: list[str] = []

        def file_a_row_in_the_same_team() -> str:
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '500ms'")
                    FileSystem.objects.create(team=self.team, path="Other", depth=1, type="folder")
                return "filed"
            except DatabaseError:
                return "blocked"
            finally:
                close_old_connections()

        def file_during_the_move(execute: Any, sql: str, params: Any, many: bool, context: dict[str, Any]) -> Any:
            result = execute(sql, params, many, context)
            if not outcomes and sql.startswith('UPDATE "posthog_filesystem"'):
                with ThreadPoolExecutor(max_workers=1) as executor:
                    outcomes.append(executor.submit(file_a_row_in_the_same_team).result(timeout=10))
            return result

        with connection.execute_wrapper(file_during_the_move):
            moved = self.client.post(
                f"/api/projects/{self.team.id}/file_system/{folder.id}/move/",
                {"new_path": "Archive/Inbox"},
                format="json",
            )

        self.assertEqual(moved.status_code, 200, moved.content)
        self.assertEqual(outcomes, ["filed"])

    def test_a_failed_file_row_keeps_the_created_template(self) -> None:
        self._refuse_file_rows()
        templates_url = f"/api/projects/{self.team.id}/messaging_templates/"

        created = self.client.post(templates_url, {"name": "Welcome", "type": "email"}, format="json")

        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(self.client.get(f"{templates_url}{created.json()['id']}/").status_code, 200)

    @parameterized.expand(
        [
            (
                "template",
                "message_template",
                "SELECT 1 FROM posthog_messagetemplate WHERE id = %s FOR UPDATE",
                "This template is being saved. Try again in a moment.",
            ),
        ]
    )
    def test_tree_delete_refuses_while_a_save_holds_the_object(
        self, _name: str, file_type: str, lock_row: str, busy_detail: str
    ) -> None:
        if file_type == "hog_flow":
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
            object_url = f"/api/projects/{self.team.id}/hog_flows/{created.json()['id']}/"
            HogFlow.objects.filter(id=created.json()["id"]).update(status=HogFlow.State.ARCHIVED)
        else:
            created = self.client.post(
                f"/api/projects/{self.team.id}/messaging_templates/",
                {"name": "Welcome", "type": "email"},
                format="json",
            )
            self.assertEqual(created.status_code, 201, created.content)
            object_url = f"/api/projects/{self.team.id}/messaging_templates/{created.json()['id']}/"
        object_id = created.json()["id"]
        files_url = f"/api/projects/{self.team.id}/file_system/"
        file_id = self.client.get(files_url, {"type": file_type, "ref": object_id}).json()["results"][0]["id"]
        locked = Event()
        release = Event()

        def hold_the_row_like_a_save() -> None:
            close_old_connections()
            try:
                with transaction.atomic(), connection.cursor() as cursor:
                    cursor.execute(lock_row, [object_id])
                    locked.set()
                    release.wait(timeout=10)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as executor:
            holder = executor.submit(hold_the_row_like_a_save)
            self.assertTrue(locked.wait(timeout=5))
            try:
                refused = self.client.delete(f"{files_url}{file_id}/")
            finally:
                release.set()
            holder.result(timeout=15)

        self.assertEqual(refused.status_code, 409, refused.content)
        self.assertEqual(refused.json()["detail"], busy_detail)
        self.assertEqual(self.client.get(f"{files_url}{file_id}/").status_code, 200)

        deleted = self.client.delete(f"{files_url}{file_id}/")
        self.assertEqual(deleted.status_code, 200, deleted.content)
        self.assertEqual(self.client.get(object_url).status_code, 404)

    def test_a_template_tree_delete_reports_a_database_failure_as_an_error_not_a_busy_template(self) -> None:
        template_id = self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/", {"name": "Welcome", "type": "email"}, format="json"
        ).json()["id"]
        files_url = f"/api/projects/{self.team.id}/file_system/"
        file_id = self.client.get(files_url, {"type": "message_template", "ref": template_id}).json()["results"][0][
            "id"
        ]

        def lose_the_connection_on_the_lock(
            execute: Any, sql: str, params: Any, many: bool, context: dict[str, Any]
        ) -> Any:
            if 'FROM "posthog_messagetemplate"' in sql and "FOR UPDATE NOWAIT" in sql:
                raise OperationalError("server closed the connection unexpectedly")
            return execute(sql, params, many, context)

        with connection.execute_wrapper(lose_the_connection_on_the_lock):
            deleted = self.client.delete(f"{files_url}{file_id}/")

        self.assertEqual(deleted.status_code, 500, deleted.content)

    def test_template_tree_delete_keeps_a_save_that_commits_after_the_delete_read_the_template(self) -> None:
        created = self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/", {"name": "Welcome", "type": "email"}, format="json"
        )
        self.assertEqual(created.status_code, 201, created.content)
        template_id = created.json()["id"]
        files_url = f"/api/projects/{self.team.id}/file_system/"
        file_id = self.client.get(files_url, {"type": "message_template", "ref": template_id}).json()["results"][0][
            "id"
        ]
        saves: list[str] = []

        def save_from_another_connection() -> None:
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE posthog_messagetemplate SET name = %s WHERE id = %s", ["Welcome v2", template_id]
                    )
            finally:
                close_old_connections()

        def commit_a_save_after_the_first_template_read(
            execute: Any, sql: str, params: Any, many: bool, context: Any
        ) -> Any:
            result = execute(sql, params, many, context)
            if not saves and sql.startswith('SELECT "posthog_messagetemplate"."id"') and "FOR UPDATE" not in sql:
                saves.append(sql)
                with ThreadPoolExecutor(max_workers=1) as executor:
                    executor.submit(save_from_another_connection).result(timeout=10)
            return result

        with connection.execute_wrapper(commit_a_save_after_the_first_template_read):
            deleted = self.client.delete(f"{files_url}{file_id}/")

        self.assertEqual(deleted.status_code, 200, deleted.content)
        with connection.cursor() as cursor:
            cursor.execute("SELECT name, deleted FROM posthog_messagetemplate WHERE id = %s", [template_id])
            self.assertEqual(cursor.fetchone(), ("Welcome v2", True))

    def test_two_deletes_of_files_for_the_same_object_both_finish(self) -> None:
        dashboard_id = str(
            self.client.post(f"/api/projects/{self.team.id}/dashboards/", {"name": "Report"}).json()["id"]
        )
        FileSystem.objects.filter(team=self.team, type="dashboard", ref=dashboard_id).delete()
        first, second = sorted(
            (
                FileSystem.objects.create(
                    team=self.team, path=path, depth=1, type="dashboard", ref=dashboard_id, shortcut=False
                )
                for path in ["Report", "Report copy"]
            ),
            key=lambda row: row.id,
        )
        first_locked = Event()
        release_first = Event()

        def hold_the_first_row() -> None:
            close_old_connections()
            try:
                with transaction.atomic(), connection.cursor() as cursor:
                    cursor.execute("SELECT id FROM posthog_filesystem WHERE id = %s FOR UPDATE", [first.id])
                    first_locked.set()
                    release_first.wait(timeout=10)
            finally:
                close_old_connections()

        def delete(row: FileSystem) -> Any:
            close_old_connections()
            try:
                return self.client.delete(f"/api/projects/{self.team.id}/file_system/{row.id}/")
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=3) as executor:
            holder = executor.submit(hold_the_first_row)
            self.assertTrue(first_locked.wait(timeout=5))
            try:
                deleting_first = executor.submit(delete, first)
                self._wait_for_blocked_backends(1)
                deleting_second = executor.submit(delete, second)
                self._wait_for_blocked_backends(2)
            finally:
                release_first.set()
            holder.result(timeout=15)
            statuses = sorted(
                [deleting_first.result(timeout=15).status_code, deleting_second.result(timeout=15).status_code]
            )

        self.assertEqual(statuses, [200, 204])
        self.assertFalse(FileSystem.objects.filter(team=self.team, type="dashboard", ref=dashboard_id).exists())

    @parameterized.expand([("move_and_folder_delete",), ("parent_and_child_folder_delete",)])
    def test_two_folder_writes_that_share_rows_both_finish(self, scenario: str) -> None:
        dashboard_ids = sorted(
            (
                str(self.client.post(f"/api/projects/{self.team.id}/dashboards/", {"name": name}).json()["id"])
                for name in ["X", "Y", "Z"]
            ),
        )
        for dashboard_id in dashboard_ids:
            FileSystem.objects.filter(team=self.team, type="dashboard", ref=dashboard_id).delete()
        first_ref, middle_ref, last_ref = dashboard_ids

        def file_row(path: str, ref: str) -> FileSystem:
            return FileSystem.objects.create(
                team=self.team, path=path, depth=path.count("/") + 1, type="dashboard", ref=ref, shortcut=False
            )

        first: tuple[str, str, dict[str, str] | None]
        second: tuple[str, str, dict[str, str] | None]
        if scenario == "move_and_folder_delete":
            moved = FileSystem.objects.create(team=self.team, path="Move", depth=1, type="folder")
            low, middle, high = sorted((file_row(f"Move/{n}", first_ref) for n in "abc"), key=lambda row: row.id)
            for row, ref in [(low, last_ref), (middle, middle_ref), (high, first_ref)]:
                FileSystem.objects.filter(pk=row.pk).update(ref=ref)
            deleted = FileSystem.objects.create(team=self.team, path="Delete", depth=1, type="folder")
            for ref in dashboard_ids:
                file_row(f"Delete/{ref}", ref)
            held = middle
            first = ("post", f"{moved.id}/move/", {"new_path": "Archive/Move"})
            second = ("delete", f"{deleted.id}/?recursive=true", None)
        else:
            parent = FileSystem.objects.create(team=self.team, path="Parent", depth=1, type="folder")
            child = FileSystem.objects.create(team=self.team, path="Parent/Child", depth=2, type="folder")
            held = file_row("Parent/Child/Report", first_ref)
            first = ("delete", f"{parent.id}/?recursive=true", None)
            second = ("delete", f"{child.id}/?recursive=true", None)
        held_locked = Event()
        release_held = Event()

        def hold_the_shared_row() -> None:
            close_old_connections()
            try:
                with transaction.atomic(), connection.cursor() as cursor:
                    cursor.execute("SELECT id FROM posthog_filesystem WHERE id = %s FOR UPDATE", [held.id])
                    held_locked.set()
                    release_held.wait(timeout=10)
            finally:
                close_old_connections()

        def send(request: tuple[str, str, dict | None]) -> Any:
            close_old_connections()
            try:
                method, suffix, payload = request
                return getattr(self.client, method)(
                    f"/api/projects/{self.team.id}/file_system/{suffix}", payload, format="json"
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=3) as executor:
            holder = executor.submit(hold_the_shared_row)
            self.assertTrue(held_locked.wait(timeout=5))
            try:
                sending_first = executor.submit(send, first)
                self._wait_for_blocked_backends(1)
                sending_second = executor.submit(send, second)
                self._wait_for_blocked_backends(2)
            finally:
                release_held.set()
            holder.result(timeout=15)
            statuses = [sending_first.result(timeout=15).status_code, sending_second.result(timeout=15).status_code]

        if scenario == "move_and_folder_delete":
            self.assertEqual(statuses, [200, 204])
            self.assertEqual(
                sorted(FileSystem.objects.filter(team=self.team, type="dashboard").values_list("path", flat=True)),
                ["Archive/Move/a", "Archive/Move/b", "Archive/Move/c"],
            )
        else:
            self.assertEqual(statuses, [200, 404])
            self.assertFalse(FileSystem.objects.filter(team=self.team, path__startswith="Parent").exists())
