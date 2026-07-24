import io
import base64
import hashlib
import zipfile
from contextlib import nullcontext
from datetime import timedelta
from uuid import UUID

import pytest
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone as django_timezone

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.constants import AvailableFeature

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass

from posthog.models import (
    FileSystem,
    Organization,
    OrganizationMembership,
    PersonalAPIKey,
    ProjectSecretAPIKey,
    Team,
    User,
)
from posthog.models.integration import Integration
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal, generate_random_token_secret

from products.tasks.backend.facade import loops as loops_facade
from products.tasks.backend.models import Loop, LoopTrigger, Task, TaskRun
from products.tasks.backend.presentation.views.loops import MAX_LOOP_TRIGGER_PAYLOAD_BYTES


class LoopsAPITestCase(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.owner = User.objects.create_user(email="owner@example.com", first_name="Owner", password="password")
        self.peer = User.objects.create_user(email="peer@example.com", first_name="Peer", password="password")
        # Default membership level (MEMBER, not ADMIN): loop visibility rules must hold for an
        # ordinary teammate, not rely on the separate admin kill-switch override.
        self.organization.members.add(self.owner)
        self.organization.members.add(self.peer)

        self.owner_client = APIClient()
        self.owner_client.force_authenticate(self.owner)
        self.peer_client = APIClient()
        self.peer_client.force_authenticate(self.peer)

        self.mock_feature_flag = self._start_patch("posthoganalytics.feature_enabled")
        self.mock_feature_flag.side_effect = lambda flag_name, *args, **kwargs: flag_name in ("tasks", "loops")

        self.mock_sync_loop_trigger_schedule = self._start_patch(
            "products.tasks.backend.facade.loops.loop_service.sync_loop_trigger_schedule"
        )
        self.mock_delete_loop_trigger_schedule = self._start_patch(
            "products.tasks.backend.facade.loops.loop_service.delete_loop_trigger_schedule"
        )
        self.mock_pause_loop_schedules = self._start_patch(
            "products.tasks.backend.facade.loops.loop_service.pause_loop_schedules"
        )
        self.mock_resume_loop_schedules = self._start_patch(
            "products.tasks.backend.facade.loops.loop_service.resume_loop_schedules"
        )
        self.mock_delete_loop_schedules = self._start_patch(
            "products.tasks.backend.facade.loops.loop_service.delete_loop_schedules"
        )

    def _start_patch(self, target: str):
        patcher = patch(target)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def _loops_url(self) -> str:
        return f"/api/projects/{self.team.id}/loops/"

    def _loop_url(self, loop_id: str | UUID) -> str:
        return f"{self._loops_url()}{loop_id}/"

    def _valid_loop_payload(self, **overrides) -> dict:
        payload = {
            "name": "Daily digest",
            "description": "",
            "visibility": "personal",
            "instructions": "Summarize open PRs",
            "runtime_adapter": "claude",
            "model": "claude-sonnet-5",
            "reasoning_effort": "medium",
        }
        payload.update(overrides)
        return payload

    def _create_loop(
        self, client: APIClient, *, visibility: str = "personal", triggers: list | None = None, **overrides
    ) -> dict:
        payload = self._valid_loop_payload(visibility=visibility, **overrides)
        if triggers is not None:
            payload["triggers"] = triggers
        response = client.post(self._loops_url(), payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        return response.json()


class LoopCRUDAPITest(LoopsAPITestCase):
    @parameterized.expand(
        [
            ("blank_model_with_effort_the_default_supports", "claude", "", "high", status.HTTP_201_CREATED),
            ("blank_model_with_effort_the_default_rejects", "codex", "", "xhigh", status.HTTP_400_BAD_REQUEST),
            ("pinned_glm_with_supported_effort", "claude", "@cf/zai-org/glm-5.2", "max", status.HTTP_201_CREATED),
            (
                "pinned_glm_with_unsupported_effort",
                "claude",
                "@cf/zai-org/glm-5.2",
                "medium",
                status.HTTP_400_BAD_REQUEST,
            ),
            ("model_outside_the_adapter_catalog", "claude", "openai/gpt-5.6-sol", None, status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_create_validates_model_and_reasoning_effort(
        self, _name, runtime_adapter, model, reasoning_effort, expected_status
    ):
        payload = self._valid_loop_payload(
            runtime_adapter=runtime_adapter, model=model, reasoning_effort=reasoning_effort
        )

        response = self.owner_client.post(self._loops_url(), payload, format="json")

        self.assertEqual(response.status_code, expected_status, response.content)

    def test_create_list_retrieve_update_delete_loop(self):
        payload = self._valid_loop_payload(
            name="Weekly digest",
            description="Summarizes the week",
            instructions="Summarize the week's shipped PRs",
            triggers=[{"type": "schedule", "config": {"cron_expression": "0 9 * * MON", "timezone": "UTC"}}],
        )

        created = self.owner_client.post(self._loops_url(), payload, format="json")
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.content)
        body = created.json()
        self.assertEqual(body["name"], "Weekly digest")
        self.assertEqual(body["visibility"], "personal")
        self.assertEqual(body["created_by_id"], self.owner.id)
        self.assertEqual(len(body["triggers"]), 1)
        self.assertEqual(body["triggers"][0]["type"], "schedule")
        loop_id = body["id"]

        listed = self.owner_client.get(self._loops_url())
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertIn(loop_id, [loop["id"] for loop in listed.json()["results"]])

        retrieved = self.owner_client.get(self._loop_url(loop_id))
        self.assertEqual(retrieved.status_code, status.HTTP_200_OK)
        self.assertEqual(retrieved.json()["name"], "Weekly digest")

        updated = self.owner_client.patch(self._loop_url(loop_id), {"name": "Renamed digest"}, format="json")
        self.assertEqual(updated.status_code, status.HTTP_200_OK, updated.content)
        self.assertEqual(updated.json()["name"], "Renamed digest")

        deleted = self.owner_client.delete(self._loop_url(loop_id))
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)
        # Deleting a loop must delete its Temporal Schedules, not merely pause them, or the spent
        # schedules leak in Temporal forever.
        self.mock_delete_loop_schedules.assert_called_once()
        self.mock_pause_loop_schedules.assert_not_called()
        self.assertTrue(Loop.objects.unscoped().get(id=loop_id).deleted)

        self.assertEqual(self.owner_client.get(self._loop_url(loop_id)).status_code, status.HTTP_404_NOT_FOUND)


class LoopBehaviorsAPITest(LoopsAPITestCase):
    def test_behaviors_persist_through_create_retrieve_and_update(self):
        behaviors = {"create_prs": True, "watch_ci": True, "fix_review_comments": True, "max_fix_iterations": 3}
        loop_id = self._create_loop(self.owner_client, behaviors=behaviors)["id"]

        self.assertEqual(Loop.objects.unscoped().get(id=loop_id).behaviors, behaviors)
        retrieved = self.owner_client.get(self._loop_url(loop_id))
        self.assertEqual(retrieved.json()["behaviors"], behaviors)

        toggled_off = {**behaviors, "watch_ci": False, "fix_review_comments": False}
        updated = self.owner_client.patch(self._loop_url(loop_id), {"behaviors": toggled_off}, format="json")
        self.assertEqual(updated.status_code, status.HTTP_200_OK, updated.content)
        self.assertEqual(Loop.objects.unscoped().get(id=loop_id).behaviors, toggled_off)


class LoopPartialUpdateAPITest(LoopsAPITestCase):
    def test_partial_behaviors_patch_preserves_unsent_subfields(self):
        # DRF drops omitted nested subfields on a PATCH, so a naive setattr would wipe them. The facade
        # deep-merges, so sending one behavior toggle must not reset the siblings the client didn't send.
        loop_id = self._create_loop(
            self.owner_client,
            behaviors={"create_prs": True, "watch_ci": True, "fix_review_comments": True, "max_fix_iterations": 5},
        )["id"]

        updated = self.owner_client.patch(self._loop_url(loop_id), {"behaviors": {"create_prs": False}}, format="json")

        self.assertEqual(updated.status_code, status.HTTP_200_OK, updated.content)
        behaviors = Loop.objects.unscoped().get(id=loop_id).behaviors
        self.assertEqual(behaviors["create_prs"], False)
        self.assertEqual(behaviors["watch_ci"], True)
        self.assertEqual(behaviors["fix_review_comments"], True)
        self.assertEqual(behaviors["max_fix_iterations"], 5)

    def test_resent_trigger_without_type_is_rejected_as_400(self):
        created = self._create_loop(
            self.owner_client,
            triggers=[{"type": "schedule", "config": {"cron_expression": "0 9 * * *", "timezone": "UTC"}}],
        )
        trigger_id = created["triggers"][0]["id"]

        # Omitting the required `type` on a resent trigger must be a clean 400, not a KeyError 500.
        response = self.owner_client.patch(
            self._loop_url(created["id"]),
            {"triggers": [{"id": trigger_id, "enabled": False}]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)

    def test_resent_trigger_without_enabled_keeps_its_current_value(self):
        created = self._create_loop(
            self.owner_client,
            triggers=[
                {
                    "type": "schedule",
                    "config": {"cron_expression": "0 9 * * *", "timezone": "UTC"},
                    "enabled": False,
                }
            ],
        )
        trigger_id = created["triggers"][0]["id"]

        # Resend the trigger changing only its config; omitting `enabled` must not silently re-enable it.
        response = self.owner_client.patch(
            self._loop_url(created["id"]),
            {
                "triggers": [
                    {
                        "id": trigger_id,
                        "type": "schedule",
                        "config": {"cron_expression": "0 10 * * *", "timezone": "UTC"},
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertFalse(response.json()["triggers"][0]["enabled"])


class LoopSkillBundlesAPITest(LoopsAPITestCase):
    def _skill_bundles_url(self, loop_id: str) -> str:
        return f"{self._loop_url(loop_id)}skill_bundles/"

    def _zip_bytes(self, files: dict[str, str] | None = None) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for entry_name, entry_content in (files or {"SKILL.md": "body"}).items():
                archive.writestr(entry_name, entry_content)
        return buffer.getvalue()

    def _bundle_payload(self, name: str = "my-skill", content: bytes | None = None) -> dict:
        content_bytes = content if content is not None else self._zip_bytes()
        return {
            "file_name": f"{name}.zip",
            "skill_name": name,
            "skill_source": "user",
            "content_sha256": hashlib.sha256(content_bytes).hexdigest(),
            "bundle_format": "zip",
            "content_base64": base64.b64encode(content_bytes).decode("ascii"),
        }

    @patch("posthog.storage.object_storage.delete_objects")
    @patch("posthog.storage.object_storage.tag")
    @patch("posthog.storage.object_storage.write")
    def test_owner_replaces_and_clears_skill_bundles(self, mock_write, mock_tag, mock_delete):
        loop = self._create_loop(self.owner_client)
        content = self._zip_bytes()

        replaced = self.owner_client.put(
            self._skill_bundles_url(loop["id"]),
            {"bundles": [self._bundle_payload(content=content)]},
            format="json",
        )

        self.assertEqual(replaced.status_code, status.HTTP_200_OK, replaced.content)
        bundles = replaced.json()["skill_bundles"]
        self.assertEqual(len(bundles), 1)
        self.assertEqual(bundles[0]["skill_name"], "my-skill")
        self.assertEqual(bundles[0]["skill_source"], "user")
        self.assertEqual(bundles[0]["size"], len(content))
        self.assertEqual(bundles[0]["content_sha256"], hashlib.sha256(content).hexdigest())
        mock_write.assert_called_once()

        row = Loop.objects.unscoped().get(id=loop["id"])
        stored = row.skill_bundles[0]
        self.assertEqual(stored["type"], "skill_bundle")
        self.assertTrue(stored["storage_path"].startswith(row.get_skill_bundle_s3_prefix()))
        self.assertEqual(stored["metadata"]["skill_name"], "my-skill")
        first_storage_path = stored["storage_path"]

        retrieved = self.owner_client.get(self._loop_url(loop["id"]))
        self.assertEqual(retrieved.status_code, status.HTTP_200_OK)
        self.assertEqual(len(retrieved.json()["skill_bundles"]), 1)

        cleared = self.owner_client.put(self._skill_bundles_url(loop["id"]), {"bundles": []}, format="json")
        self.assertEqual(cleared.status_code, status.HTTP_200_OK, cleared.content)
        self.assertEqual(cleared.json()["skill_bundles"], [])
        self.assertEqual(Loop.objects.unscoped().get(id=loop["id"]).skill_bundles, [])
        # Superseded objects are expired via a grace-period tag, not deleted outright —
        # an in-flight fire may still be copying from them.
        mock_delete.assert_not_called()
        mock_tag.assert_any_call(first_storage_path, {"ttl_days": "1", "team_id": str(self.team.id)})

    @patch("posthog.storage.object_storage.write")
    def test_replace_rejects_a_sha_mismatch(self, mock_write):
        loop = self._create_loop(self.owner_client)
        payload = self._bundle_payload()
        payload["content_sha256"] = "0" * 64

        response = self.owner_client.put(self._skill_bundles_url(loop["id"]), {"bundles": [payload]}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.assertIn("sha256", response.json()["detail"])
        mock_write.assert_not_called()

    def test_replace_rejects_too_many_bundles(self):
        loop = self._create_loop(self.owner_client)
        bundles = [self._bundle_payload(name=f"skill-{index}") for index in range(11)]

        response = self.owner_client.put(self._skill_bundles_url(loop["id"]), {"bundles": bundles}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)

    @patch("posthog.storage.object_storage.write")
    def test_a_later_invalid_bundle_prevents_any_write(self, mock_write):
        loop = self._create_loop(self.owner_client)
        valid = self._bundle_payload(name="first")
        invalid = self._bundle_payload(name="second")
        invalid["content_sha256"] = "0" * 64

        response = self.owner_client.put(
            self._skill_bundles_url(loop["id"]), {"bundles": [valid, invalid]}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        mock_write.assert_not_called()
        self.assertEqual(Loop.objects.unscoped().get(id=loop["id"]).skill_bundles, [])

    @patch("posthog.storage.object_storage.delete_objects")
    @patch("posthog.storage.object_storage.tag")
    @patch("posthog.storage.object_storage.write")
    def test_a_failed_write_deletes_the_bundles_already_written(self, mock_write, mock_tag, mock_delete):
        loop = self._create_loop(self.owner_client)
        mock_write.side_effect = [None, RuntimeError("s3 down")]

        response = self.owner_client.put(
            self._skill_bundles_url(loop["id"]),
            {"bundles": [self._bundle_payload(name="first"), self._bundle_payload(name="second")]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR, response.content)
        mock_delete.assert_called_once()
        deleted_paths = mock_delete.call_args.args[0]
        self.assertEqual(len(deleted_paths), 1)
        self.assertIn("first", deleted_paths[0])
        self.assertEqual(Loop.objects.unscoped().get(id=loop["id"]).skill_bundles, [])

    @patch("posthog.storage.object_storage.write")
    def test_replace_rejects_a_non_zip_bundle(self, mock_write):
        loop = self._create_loop(self.owner_client)
        payload = self._bundle_payload(content=b"not a zip archive")

        response = self.owner_client.put(self._skill_bundles_url(loop["id"]), {"bundles": [payload]}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.assertIn("not a valid zip archive", response.json()["detail"])
        mock_write.assert_not_called()

    @patch("products.tasks.backend.facade.loops.MAX_LOOP_SKILL_BUNDLE_UNCOMPRESSED_BYTES", 64)
    @patch("posthog.storage.object_storage.write")
    def test_replace_rejects_a_bundle_that_expands_past_the_cap(self, mock_write):
        loop = self._create_loop(self.owner_client)
        payload = self._bundle_payload(content=self._zip_bytes({"SKILL.md": "x" * 1024}))

        response = self.owner_client.put(self._skill_bundles_url(loop["id"]), {"bundles": [payload]}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.assertIn("expands to more than", response.json()["detail"])
        mock_write.assert_not_called()

    @patch("products.tasks.backend.facade.loops.MAX_LOOP_SKILL_BUNDLE_FILES", 1)
    @patch("posthog.storage.object_storage.write")
    def test_replace_rejects_a_bundle_with_too_many_entries(self, mock_write):
        loop = self._create_loop(self.owner_client)
        payload = self._bundle_payload(content=self._zip_bytes({"SKILL.md": "body", "extra.md": "more"}))

        response = self.owner_client.put(self._skill_bundles_url(loop["id"]), {"bundles": [payload]}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.assertIn("contains more than", response.json()["detail"])
        mock_write.assert_not_called()

    @patch("products.tasks.backend.facade.loops.MAX_LOOP_SKILL_BUNDLES_TOTAL_UNCOMPRESSED_BYTES", 1500)
    @patch("posthog.storage.object_storage.write")
    def test_replace_rejects_bundles_that_together_expand_past_the_cap(self, mock_write):
        loop = self._create_loop(self.owner_client)
        bundles = [
            self._bundle_payload(name="first", content=self._zip_bytes({"SKILL.md": "x" * 1024})),
            self._bundle_payload(name="second", content=self._zip_bytes({"SKILL.md": "y" * 1024})),
        ]

        response = self.owner_client.put(self._skill_bundles_url(loop["id"]), {"bundles": bundles}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.assertIn("together expand", response.json()["detail"])
        mock_write.assert_not_called()

    @patch("products.tasks.backend.facade.loops.MAX_LOOP_SKILL_BUNDLE_CENTRAL_DIR_BYTES", 10)
    @patch("posthog.storage.object_storage.write")
    def test_replace_rejects_an_oversized_central_directory(self, mock_write):
        loop = self._create_loop(self.owner_client)

        response = self.owner_client.put(
            self._skill_bundles_url(loop["id"]), {"bundles": [self._bundle_payload()]}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        mock_write.assert_not_called()

    @patch("products.tasks.backend.facade.loops.MAX_LOOP_SKILL_BUNDLE_FILES", 1)
    @patch("posthog.storage.object_storage.write")
    def test_a_lying_trailer_count_is_caught_after_parse(self, mock_write):
        # The trailer's entry count is attacker-controlled; forging it low shaves the
        # fast-fail but the parsed entry list must still trip the cap.
        content = bytearray(self._zip_bytes({"SKILL.md": "body", "extra.md": "more"}))
        eocd = content.rfind(b"PK\x05\x06")
        content[eocd + 8 : eocd + 12] = (1).to_bytes(2, "little") * 2
        loop = self._create_loop(self.owner_client)
        payload = self._bundle_payload(content=bytes(content))

        response = self.owner_client.put(self._skill_bundles_url(loop["id"]), {"bundles": [payload]}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.assertIn("contains more than", response.json()["detail"])
        mock_write.assert_not_called()

    def test_replace_requires_a_declared_content_length(self):
        loop = self._create_loop(self.owner_client)

        response = self.owner_client.put(self._skill_bundles_url(loop["id"]), CONTENT_LENGTH="0")

        self.assertEqual(response.status_code, status.HTTP_411_LENGTH_REQUIRED, response.content)

    @patch("products.tasks.backend.presentation.views.loops.MAX_LOOP_SKILL_BUNDLE_REQUEST_BYTES", 10)
    def test_replace_rejects_an_oversized_request_up_front(self):
        loop = self._create_loop(self.owner_client)

        response = self.owner_client.put(
            self._skill_bundles_url(loop["id"]), {"bundles": [self._bundle_payload()]}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, response.content)

    @patch("posthog.storage.object_storage.delete_objects")
    @patch("posthog.storage.object_storage.tag")
    @patch("posthog.storage.object_storage.write")
    def test_replace_racing_an_ownership_takeover_is_denied(self, mock_write, mock_tag, mock_delete):
        # Ownership moves to a teammate while the former owner's replace is mid-upload;
        # the swap must re-authorize under the lock, discard its uploads and 403 rather
        # than landing the former owner's skill on the taken-over loop.
        loop = self._create_loop(self.owner_client, visibility="team")

        def take_ownership_mid_request(*args, **kwargs):
            Loop.objects.unscoped().filter(id=loop["id"]).update(created_by=self.peer)

        mock_write.side_effect = take_ownership_mid_request

        response = self.owner_client.put(
            self._skill_bundles_url(loop["id"]), {"bundles": [self._bundle_payload()]}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)
        mock_delete.assert_called_once()
        discarded_paths = mock_delete.call_args.args[0]
        self.assertEqual(len(discarded_paths), 1)
        self.assertEqual(Loop.objects.unscoped().get(id=loop["id"]).skill_bundles, [])

    @patch("posthog.storage.object_storage.delete_objects")
    @patch("posthog.storage.object_storage.tag")
    @patch("posthog.storage.object_storage.write")
    def test_replace_racing_a_delete_discards_its_uploads(self, mock_write, mock_tag, mock_delete):
        # The soft delete commits between this request's fetch and its manifest swap; the
        # swap must notice the deleted row and discard its own fresh uploads, not
        # resurrect bundles on a deleted loop.
        loop = self._create_loop(self.owner_client)

        def soft_delete_mid_request(*args, **kwargs):
            Loop.objects.unscoped().filter(id=loop["id"]).update(deleted=True)

        mock_write.side_effect = soft_delete_mid_request

        response = self.owner_client.put(
            self._skill_bundles_url(loop["id"]), {"bundles": [self._bundle_payload()]}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.content)
        mock_delete.assert_called_once()
        discarded_paths = mock_delete.call_args.args[0]
        self.assertEqual(len(discarded_paths), 1)
        self.assertEqual(Loop.objects.unscoped().get(id=loop["id"]).skill_bundles, [])

    @patch("posthog.storage.object_storage.delete_objects")
    @patch("posthog.storage.object_storage.tag")
    @patch("posthog.storage.object_storage.write")
    def test_deleting_a_loop_releases_its_bundle_objects(self, mock_write, mock_tag, mock_delete):
        loop = self._create_loop(self.owner_client)
        replaced = self.owner_client.put(
            self._skill_bundles_url(loop["id"]), {"bundles": [self._bundle_payload()]}, format="json"
        )
        self.assertEqual(replaced.status_code, status.HTTP_200_OK, replaced.content)
        stored_path = Loop.objects.unscoped().get(id=loop["id"]).skill_bundles[0]["storage_path"]

        deleted = self.owner_client.delete(self._loop_url(loop["id"]))

        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT, deleted.content)
        mock_delete.assert_not_called()
        mock_tag.assert_any_call(stored_path, {"ttl_days": "1", "team_id": str(self.team.id)})
        row = Loop.objects.unscoped().get(id=loop["id"])
        self.assertTrue(row.deleted)
        self.assertEqual(row.skill_bundles, [])

    @patch("posthog.storage.object_storage.tag")
    @patch("posthog.storage.object_storage.write")
    def test_replace_is_owner_gated_on_a_team_loop(self, mock_write, mock_tag):
        loop = self._create_loop(self.owner_client, visibility="team")

        denied = self.peer_client.put(
            self._skill_bundles_url(loop["id"]), {"bundles": [self._bundle_payload()]}, format="json"
        )
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN, denied.content)

        allowed = self.owner_client.put(
            self._skill_bundles_url(loop["id"]), {"bundles": [self._bundle_payload()]}, format="json"
        )
        self.assertEqual(allowed.status_code, status.HTTP_200_OK, allowed.content)

    def test_replace_on_someone_elses_personal_loop_is_a_404(self):
        loop = self._create_loop(self.owner_client, visibility="personal")

        response = self.peer_client.put(
            self._skill_bundles_url(loop["id"]), {"bundles": [self._bundle_payload()]}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.content)


class LoopSafetyLimitAPITest(LoopsAPITestCase):
    def test_too_many_triggers_rejected(self):
        triggers = [
            {"type": "schedule", "config": {"cron_expression": "0 9 * * *", "timezone": "UTC"}}
            for _ in range(loops_facade.MAX_TRIGGERS_PER_LOOP + 1)
        ]
        response = self.owner_client.post(self._loops_url(), self._valid_loop_payload(triggers=triggers), format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        body = response.json()
        self.assertEqual(body["code"], "max_length")
        self.assertIn("triggers", body["attr"])
        # No schedules should have been minted for a rejected create.
        self.mock_sync_loop_trigger_schedule.assert_not_called()

    def test_loops_per_team_cap_returns_structured_429(self):
        with patch("products.tasks.backend.facade.loops.MAX_LOOPS_PER_TEAM", 2):
            self._create_loop(self.owner_client)
            self._create_loop(self.owner_client)
            blocked = self.owner_client.post(self._loops_url(), self._valid_loop_payload(), format="json")

        self.assertEqual(blocked.status_code, status.HTTP_429_TOO_MANY_REQUESTS, blocked.content)
        body = blocked.json()
        self.assertEqual(body["error"], "loop_safety_limit")
        self.assertEqual(body["code"], "max_loops_per_team")
        self.assertEqual(body["limit"], 2)
        self.assertEqual(Loop.objects.unscoped().filter(team=self.team, deleted=False).count(), 2)

    def test_list_reports_the_cap_and_authoritative_team_wide_usage(self):
        # The owner sees only their own personal loop, but the cap counts every non-deleted loop in
        # the project — including the peer's personal loop the owner can't see. The frontend gates
        # creation against this authoritative total, so it must not be the caller's visible count.
        self._create_loop(self.owner_client)
        self._create_loop(self.peer_client)

        body = self.owner_client.get(self._loops_url()).json()
        self.assertEqual(len(body["results"]), 1)
        self.assertEqual(body["max_loops_per_team"], loops_facade.MAX_LOOPS_PER_TEAM)
        self.assertEqual(body["total_loop_count"], 2)

    def test_soft_deleted_loops_do_not_count_toward_cap(self):
        with patch("products.tasks.backend.facade.loops.MAX_LOOPS_PER_TEAM", 1):
            first = self._create_loop(self.owner_client)["id"]
            self.owner_client.delete(self._loop_url(first))
            # The freed slot lets a new loop through.
            allowed = self.owner_client.post(self._loops_url(), self._valid_loop_payload(), format="json")
        self.assertEqual(allowed.status_code, status.HTTP_201_CREATED, allowed.content)


class LoopInternalAndProvenanceAPITest(LoopsAPITestCase):
    def test_api_created_loop_is_user_facing_and_attributed_to_the_person(self):
        body = self._create_loop(self.owner_client)
        self.assertFalse(body["internal"])
        self.assertEqual(body["origin_product"], "user_created")
        loop = Loop.objects.unscoped().get(id=body["id"])
        self.assertFalse(loop.internal)
        self.assertEqual(loop.origin_product, "user_created")

    def test_internal_and_origin_product_cannot_be_set_through_the_api(self):
        # A caller must not be able to hide a loop from the UI or forge its provenance.
        payload = self._valid_loop_payload(internal=True, origin_product="error_tracking")
        response = self.owner_client.post(self._loops_url(), payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        loop = Loop.objects.unscoped().get(id=response.json()["id"])
        self.assertFalse(loop.internal)
        self.assertEqual(loop.origin_product, "user_created")

    def test_internal_loops_are_invisible_and_unreachable_through_the_api(self):
        # A backend-created internal loop: attached to the team/owner, but never surfaced.
        internal_loop = Loop.objects.unscoped().create(
            team=self.team,
            created_by=self.owner,
            name="Signals backfill",
            instructions="internal",
            runtime_adapter="claude",
            model="",
            internal=True,
            origin_product=Task.OriginProduct.ERROR_TRACKING,
        )

        listed = self.owner_client.get(self._loops_url())
        self.assertNotIn(str(internal_loop.id), [loop["id"] for loop in listed.json()["results"]])
        self.assertEqual(self.owner_client.get(self._loop_url(internal_loop.id)).status_code, status.HTTP_404_NOT_FOUND)
        # And it can't be mutated or deleted through the user-facing API either.
        patched = self.owner_client.patch(self._loop_url(internal_loop.id), {"name": "x"}, format="json")
        self.assertEqual(patched.status_code, status.HTTP_404_NOT_FOUND)
        deleted = self.owner_client.delete(self._loop_url(internal_loop.id))
        self.assertEqual(deleted.status_code, status.HTTP_404_NOT_FOUND)


class LoopVisibilityAPITest(LoopsAPITestCase):
    def test_personal_loop_hidden_and_immutable_to_teammate(self):
        loop_id = self._create_loop(self.owner_client, visibility="personal")["id"]

        listed = self.peer_client.get(self._loops_url())
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertNotIn(loop_id, [loop["id"] for loop in listed.json()["results"]])

        self.assertEqual(self.peer_client.get(self._loop_url(loop_id)).status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            self.peer_client.patch(self._loop_url(loop_id), {"name": "hijacked"}, format="json").status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(self.peer_client.delete(self._loop_url(loop_id)).status_code, status.HTTP_404_NOT_FOUND)

        # Owner keeps full access throughout.
        owner_view = self.owner_client.get(self._loop_url(loop_id))
        self.assertEqual(owner_view.status_code, status.HTTP_200_OK)
        self.assertEqual(owner_view.json()["name"], "Daily digest")

    def test_team_loop_viewable_by_any_member(self):
        loop_id = self._create_loop(self.owner_client, visibility="team")["id"]
        response = self.peer_client.get(self._loop_url(loop_id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], loop_id)

    @parameterized.expand(
        [
            ("name", "Renamed by teammate", status.HTTP_200_OK),
            ("instructions", "Unauthorized new instructions", status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_team_loop_identity_field_edit_is_owner_only(self, field, new_value, expected_status):
        loop_id = self._create_loop(self.owner_client, visibility="team")["id"]

        response = self.peer_client.patch(self._loop_url(loop_id), {field: new_value}, format="json")
        self.assertEqual(response.status_code, expected_status, response.content)

        current = self.owner_client.get(self._loop_url(loop_id)).json()
        if expected_status == status.HTTP_200_OK:
            self.assertEqual(current[field], new_value)
        else:
            self.assertNotEqual(current[field], new_value)

    def test_take_ownership_lets_a_member_edit_a_team_loops_identity_config(self):
        loop_id = self._create_loop(self.owner_client, visibility="team")["id"]

        # Without takeover, the identity edit is rejected.
        rejected = self.peer_client.patch(self._loop_url(loop_id), {"instructions": "new plan"}, format="json")
        self.assertEqual(rejected.status_code, status.HTTP_403_FORBIDDEN, rejected.content)

        # Claiming ownership in the same request lets it through and transfers ownership.
        response = self.peer_client.patch(
            self._loop_url(loop_id), {"instructions": "new plan", "take_ownership": True}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.json()["instructions"], "new plan")
        self.assertEqual(response.json()["created_by_id"], self.peer.id)

    def test_take_ownership_cannot_privatize_a_shared_team_loop(self):
        # The hijack: a member takes ownership AND flips visibility=personal in one PATCH, privatizing
        # a shared team loop out from under the team. Takeover must not double as a visibility change.
        loop_id = self._create_loop(self.owner_client, visibility="team")["id"]

        response = self.peer_client.patch(
            self._loop_url(loop_id),
            {"take_ownership": True, "visibility": "personal"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)
        loop = Loop.objects.unscoped().get(id=loop_id)
        self.assertEqual(loop.visibility, "team")
        self.assertEqual(loop.created_by_id, self.owner.id)

    def test_member_cannot_privatize_a_team_loop_after_taking_ownership(self):
        # The two-request version of the hijack: take ownership (allowed, so a member can edit a
        # teammate's loop), then privatize as the new owner in a second request. Un-sharing a team
        # loop is admin-only, so it must still fail.
        loop_id = self._create_loop(self.owner_client, visibility="team")["id"]
        taken = self.peer_client.patch(
            self._loop_url(loop_id), {"instructions": "mine now", "take_ownership": True}, format="json"
        )
        self.assertEqual(taken.status_code, status.HTTP_200_OK, taken.content)

        response = self.peer_client.patch(self._loop_url(loop_id), {"visibility": "personal"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)
        self.assertEqual(Loop.objects.unscoped().get(id=loop_id).visibility, "team")

    def test_member_cannot_delete_a_team_loop_after_taking_ownership(self):
        loop_id = self._create_loop(self.owner_client, visibility="team")["id"]
        self.peer_client.patch(
            self._loop_url(loop_id), {"instructions": "mine now", "take_ownership": True}, format="json"
        )

        response = self.peer_client.delete(self._loop_url(loop_id))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)
        self.assertFalse(Loop.objects.unscoped().get(id=loop_id).deleted)

    def test_admin_may_privatize_a_team_loop(self):
        OrganizationMembership.objects.filter(user=self.peer, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )
        loop_id = self._create_loop(self.owner_client, visibility="team")["id"]

        response = self.peer_client.patch(self._loop_url(loop_id), {"visibility": "personal"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(Loop.objects.unscoped().get(id=loop_id).visibility, "personal")


class LoopContextVisibilityAPITest(LoopsAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.folder = FileSystem.objects.create(team=self.team, path="Growth Team", type="folder", surface="desktop")

    def _context_target(self) -> dict:
        return {"folder_id": str(self.folder.id), "name": "Growth Team", "outputs": {"post_to_feed": True}}

    @parameterized.expand(
        [
            ("personal", status.HTTP_400_BAD_REQUEST),
            ("team", status.HTTP_201_CREATED),
        ]
    )
    def test_create_with_context_requires_team_visibility(self, visibility, expected_status):
        response = self.owner_client.post(
            self._loops_url(),
            self._valid_loop_payload(visibility=visibility, context_target=self._context_target()),
            format="json",
        )
        self.assertEqual(response.status_code, expected_status, response.content)

    @parameterized.expand(
        [
            ("attach_only", {}, status.HTTP_400_BAD_REQUEST),
            ("attach_and_upgrade", {"visibility": "team"}, status.HTTP_200_OK),
        ]
    )
    def test_attaching_context_to_personal_loop(self, _name, extra_fields, expected_status):
        loop_id = self._create_loop(self.owner_client, visibility="personal")["id"]

        response = self.owner_client.patch(
            self._loop_url(loop_id), {"context_target": self._context_target(), **extra_fields}, format="json"
        )
        self.assertEqual(response.status_code, expected_status, response.content)

        current = self.owner_client.get(self._loop_url(loop_id)).json()
        if expected_status == status.HTTP_200_OK:
            self.assertEqual(current["context_target"]["folder_id"], str(self.folder.id))
        else:
            self.assertIsNone(current["context_target"])

    @parameterized.expand(
        [
            ("downgrade_only", {}, status.HTTP_400_BAD_REQUEST),
            ("downgrade_and_detach", {"context_target": None}, status.HTTP_200_OK),
        ]
    )
    def test_downgrading_attached_team_loop(self, _name, extra_fields, expected_status):
        loop_id = self._create_loop(self.owner_client, visibility="team", context_target=self._context_target())["id"]

        response = self.owner_client.patch(
            self._loop_url(loop_id), {"visibility": "personal", **extra_fields}, format="json"
        )
        self.assertEqual(response.status_code, expected_status, response.content)

        current = self.owner_client.get(self._loop_url(loop_id)).json()
        if expected_status == status.HTTP_200_OK:
            self.assertEqual(current["visibility"], "personal")
            self.assertIsNone(current["context_target"])
        else:
            self.assertEqual(current["visibility"], "team")


class LoopTriggerSyncAPITest(LoopsAPITestCase):
    def test_trigger_update_is_id_stable(self):
        created = self._create_loop(
            self.owner_client,
            triggers=[
                {"type": "schedule", "config": {"cron_expression": "0 9 * * *", "timezone": "UTC"}},
                {"type": "schedule", "config": {"cron_expression": "0 18 * * *", "timezone": "UTC"}},
            ],
        )
        kept_trigger_id, dropped_trigger_id = (trigger["id"] for trigger in created["triggers"])

        patch_response = self.owner_client.patch(
            self._loop_url(created["id"]),
            {
                "triggers": [
                    {
                        "id": kept_trigger_id,
                        "type": "schedule",
                        "config": {"cron_expression": "0 10 * * *", "timezone": "UTC"},
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK, patch_response.content)

        triggers = patch_response.json()["triggers"]
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["id"], kept_trigger_id)
        self.assertEqual(triggers[0]["config"]["cron_expression"], "0 10 * * *")

        self.assertTrue(LoopTrigger.objects.unscoped().filter(id=kept_trigger_id).exists())
        self.assertFalse(LoopTrigger.objects.unscoped().filter(id=dropped_trigger_id).exists())

    def test_partial_update_without_triggers_key_leaves_triggers_untouched(self):
        created = self._create_loop(
            self.owner_client,
            triggers=[{"type": "schedule", "config": {"cron_expression": "0 9 * * *", "timezone": "UTC"}}],
        )
        trigger_id = created["triggers"][0]["id"]

        response = self.owner_client.patch(self._loop_url(created["id"]), {"name": "renamed"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual([trigger["id"] for trigger in response.json()["triggers"]], [trigger_id])

    def test_changing_a_trigger_type_tears_down_its_old_schedule(self):
        # Repointing a schedule trigger to github/api must delete the old Temporal Schedule, or
        # it keeps firing forever and no later delete can reach it (delete keys off current type).
        created = self._create_loop(
            self.owner_client,
            triggers=[{"type": "schedule", "config": {"cron_expression": "0 9 * * *", "timezone": "UTC"}}],
        )
        trigger_id = created["triggers"][0]["id"]
        self.mock_delete_loop_trigger_schedule.reset_mock()

        response = self.owner_client.patch(
            self._loop_url(created["id"]),
            {"triggers": [{"id": trigger_id, "type": "api", "config": {}}]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.json()["triggers"][0]["type"], "api")
        deleted_ids = {str(call.args[0].id) for call in self.mock_delete_loop_trigger_schedule.call_args_list}
        self.assertIn(trigger_id, deleted_ids)


class LoopEnableToggleAPITest(LoopsAPITestCase):
    def test_re_enabling_a_loop_resumes_its_temporal_schedule(self):
        # Re-enabling after an auto-pause is the documented recovery: it must resume the schedule,
        # not just flip the row, or the loop silently never fires again.
        created = self._create_loop(
            self.owner_client,
            enabled=False,
            triggers=[{"type": "schedule", "config": {"cron_expression": "0 9 * * *", "timezone": "UTC"}}],
        )
        self.mock_resume_loop_schedules.reset_mock()
        self.mock_pause_loop_schedules.reset_mock()

        response = self.owner_client.patch(self._loop_url(created["id"]), {"enabled": True}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertTrue(response.json()["enabled"])
        self.mock_resume_loop_schedules.assert_called_once()
        self.mock_pause_loop_schedules.assert_not_called()

    def test_pausing_a_loop_pauses_its_temporal_schedule(self):
        created = self._create_loop(
            self.owner_client,
            enabled=True,
            triggers=[{"type": "schedule", "config": {"cron_expression": "0 9 * * *", "timezone": "UTC"}}],
        )
        self.mock_resume_loop_schedules.reset_mock()
        self.mock_pause_loop_schedules.reset_mock()

        response = self.owner_client.patch(self._loop_url(created["id"]), {"enabled": False}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertFalse(response.json()["enabled"])
        self.mock_pause_loop_schedules.assert_called_once()
        self.mock_resume_loop_schedules.assert_not_called()

    def test_re_enabling_clears_a_lifecycle_disabled_reason(self):
        created = self._create_loop(self.owner_client, enabled=True)
        loop = Loop.objects.unscoped().get(id=created["id"])
        loop.enabled = False
        loop.disabled_reason = "owner_deactivated"
        loop.save(update_fields=["enabled", "disabled_reason"])

        response = self.owner_client.patch(self._loop_url(created["id"]), {"enabled": True}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertIsNone(response.json()["disabled_reason"])


class LoopScheduleTriggerValidationAPITest(LoopsAPITestCase):
    @parameterized.expand(
        [
            ("offset_aware_future", "2099-01-01T00:00:00+00:00", status.HTTP_201_CREATED),
            # A naive (offset-less) datetime must be treated as UTC, not crash the comparison with a 500.
            ("naive_future", "2099-01-01T00:00:00", status.HTTP_201_CREATED),
            ("naive_past", "2000-01-01T00:00:00", status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_run_at_datetime_handling(self, _name, run_at, expected_status):
        response = self.owner_client.post(
            self._loops_url(),
            self._valid_loop_payload(triggers=[{"type": "schedule", "config": {"run_at": run_at}}]),
            format="json",
        )
        self.assertEqual(response.status_code, expected_status, response.content)


class LoopGithubTriggerValidationAPITest(LoopsAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.integration = Integration.objects.create(team=self.team, kind="github", integration_id="1", config={})
        mock_github = self._start_patch("products.tasks.backend.facade.loops.GitHubIntegration")
        mock_github.return_value.list_all_cached_repositories.return_value = [{"full_name": "acme/repo"}]

    def _github_trigger(self, events: list, filters: dict | None = None) -> dict:
        config: dict = {"github_integration_id": self.integration.id, "repository": "acme/repo", "events": events}
        if filters is not None:
            config["filters"] = filters
        return {"type": "github", "config": config}

    @parameterized.expand(
        [
            ("bare_event", ["issues"], None, ["issues"], {}),
            ("bare_event_with_action_filter", ["issues"], {"actions": ["opened"]}, ["issues"], {"actions": ["opened"]}),
            ("singular_action_alias", ["issues"], {"action": "opened"}, ["issues"], {"actions": ["opened"]}),
            ("dotted_shorthand", ["issues.opened"], None, ["issues"], {"actions": ["opened"]}),
            (
                "dotted_shorthand_duplicates",
                ["issues.opened", "issues.opened"],
                None,
                ["issues"],
                {"actions": ["opened"]},
            ),
            (
                "dotted_shorthand_multiple_actions",
                ["issues.opened", "issues.reopened"],
                None,
                ["issues"],
                {"actions": ["opened", "reopened"]},
            ),
            (
                "dotted_shorthand_merges_with_explicit_actions",
                ["pull_request.opened"],
                {"actions": ["synchronize"]},
                ["pull_request"],
                {"actions": ["synchronize", "opened"]},
            ),
        ]
    )
    def test_event_shorthand_normalization(self, _name, events, filters, expected_events, expected_filters):
        created = self._create_loop(self.owner_client, triggers=[self._github_trigger(events, filters)])
        config = created["triggers"][0]["config"]
        self.assertEqual(config["events"], expected_events)
        self.assertEqual(config["filters"], expected_filters)

    @parameterized.expand(
        [
            ("unknown_event", ["nonsense"]),
            ("unknown_dotted_event", ["nonsense.opened"]),
            ("dotted_event_with_empty_action", ["issues."]),
            # Shorthand mixed with a bare event is ambiguous: the folded actions filter would
            # silently apply to the bare event too.
            ("shorthand_mixed_with_bare_event", ["issues.opened", "push"]),
            ("shorthand_mixed_with_its_own_bare_event", ["issues.opened", "issues"]),
            # Cross-event shorthand would flatten into a cartesian product: pull_request.opened
            # would fire here even though only pull_request.synchronize was requested.
            ("shorthand_spanning_multiple_events", ["issues.opened", "pull_request.synchronize"]),
        ]
    )
    def test_invalid_events_are_rejected(self, _name, events):
        response = self.owner_client.post(
            self._loops_url(),
            self._valid_loop_payload(triggers=[self._github_trigger(events)]),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)


class LoopServiceReadbackAPITest(LoopsAPITestCase):
    def _psak(self, scopes) -> str:
        raw_token = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="loop service key",
            secure_value=hash_key_value(raw_token),
            scopes=scopes,
            mask_value=f"{raw_token[:4]}...{raw_token[-4:]}",
        )
        return raw_token

    def test_psak_can_read_back_runs_of_a_loop_it_can_trigger(self):
        # A service that fires a loop needs a documented way to poll the outcome. A PSAK with
        # loop:read reads run history project-wide, without the personal-visibility filter.
        loop_id = self._create_loop(self.owner_client, visibility="personal", triggers=[{"type": "api", "config": {}}])[
            "id"
        ]
        token = self._psak(["loop:read", "loop:write"])

        response = APIClient().get(f"{self._loop_url(loop_id)}runs/", headers={"authorization": f"Bearer {token}"})

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertIn("results", response.json())


class LoopScopeAPITest(LoopsAPITestCase):
    @parameterized.expand(
        [
            (None, "GET", status.HTTP_403_FORBIDDEN),
            # Loops deliberately use their own scope object rather than reusing `task`, so a
            # task-scoped key must never grant loop access (see products/tasks/docs/LOOPS.md).
            ("task:write", "GET", status.HTTP_403_FORBIDDEN),
            ("loop:read", "GET", status.HTTP_200_OK),
            ("loop:read", "POST", status.HTTP_403_FORBIDDEN),
            ("loop:write", "POST", status.HTTP_201_CREATED),
        ]
    )
    def test_personal_api_key_scope_enforcement(self, scope, method, expected_status):
        scopes = [scope] if scope else []
        api_key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.owner,
            label=f"Test key - {scope}",
            secure_value=hash_key_value(api_key_value),
            scopes=scopes,
        )
        self.owner_client.force_authenticate(None)
        headers = {"authorization": f"Bearer {api_key_value}"}

        if method == "GET":
            response = self.owner_client.get(self._loops_url(), headers=headers)
        else:
            response = self.owner_client.post(
                self._loops_url(), self._valid_loop_payload(), format="json", headers=headers
            )

        self.assertEqual(response.status_code, expected_status, response.content)


class LoopRunsAPITest(LoopsAPITestCase):
    def test_runs_listing_paginates_newest_first(self):
        loop_id = self._create_loop(self.owner_client)["id"]

        base_time = django_timezone.now()
        created_run_ids = []
        for i in range(5):
            task = Task.objects.create(
                team=self.team,
                created_by=self.owner,
                title=f"Loop run {i}",
                description="d",
                origin_product=Task.OriginProduct.LOOP,
                internal=True,
            )
            run = TaskRun.objects.create(
                task=task,
                team=self.team,
                status=TaskRun.Status.COMPLETED,
                state={"loop_id": loop_id},
                created_at=base_time + timedelta(seconds=i),
            )
            created_run_ids.append(str(run.id))

        runs_url = f"{self._loop_url(loop_id)}runs/"
        collected_ids: list[str] = []
        cursor = None
        for _ in range(len(created_run_ids) + 1):
            params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
            response = self.owner_client.get(runs_url, params)
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
            body = response.json()
            self.assertLessEqual(len(body["results"]), 2)
            collected_ids.extend(run["id"] for run in body["results"])
            cursor = body["next_cursor"]
            if cursor is None:
                break

        self.assertEqual(collected_ids, list(reversed(created_run_ids)))

    def test_runs_listing_is_invisible_for_personal_loop_of_another_member(self):
        loop_id = self._create_loop(self.owner_client, visibility="personal")["id"]
        response = self.peer_client.get(f"{self._loop_url(loop_id)}runs/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class LoopPreviewAPITest(LoopsAPITestCase):
    @parameterized.expand(
        [
            ("schedule", {}, "Trigger: schedule"),
            ("api", {"payload": {"pr_number": 42}}, "Trigger: api"),
        ]
    )
    def test_preview_renders_context_without_creating_a_task(self, trigger_type, extra_payload, expected_header):
        loop = self._create_loop(self.owner_client, instructions="Summarize open PRs")
        preview_url = f"{self._loop_url(loop['id'])}preview/"

        response = self.owner_client.post(preview_url, {"trigger_type": trigger_type, **extra_payload}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

        body = response.json()
        self.assertEqual(body["instructions"], "Summarize open PRs")
        self.assertIn(expected_header, body["trigger_context"])

        self.assertEqual(Task.objects.filter(team=self.team).count(), 0)
        self.assertEqual(TaskRun.objects.filter(team=self.team).count(), 0)


class LoopFeatureGateAPITest(LoopsAPITestCase):
    def _disable_loops_flag(self) -> None:
        self.mock_feature_flag.side_effect = lambda flag_name, *args, **kwargs: flag_name == "tasks"

    def test_disabled_loops_flag_blocks_session_authenticated_actions(self):
        self._disable_loops_flag()

        response = self.owner_client.get(self._loops_url())

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_disabled_loops_flag_does_not_block_psak_authenticated_trigger(self):
        # The `trigger` action authenticates a project-scoped service credential, not a
        # real user, so the person-targeted `loops` flag must not gate it (see
        # HasLoopsAccess.has_permission).
        loop_id = self._create_loop(self.owner_client, triggers=[{"type": "api", "config": {}}])["id"]
        raw_token = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="loop trigger key",
            secure_value=hash_key_value(raw_token),
            scopes=["loop:write"],
            mask_value=f"{raw_token[:4]}...{raw_token[-4:]}",
        )
        self._disable_loops_flag()

        response = APIClient().post(
            f"{self._loop_url(loop_id)}trigger/",
            {},
            format="json",
            headers={"authorization": f"Bearer {raw_token}"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)


class LoopInternalFacadeTest(LoopsAPITestCase):
    def _make_internal_loop(self, **overrides) -> Loop:
        defaults = {
            "team": self.team,
            "created_by": self.owner,
            "name": "Signals follow-up",
            "instructions": "Check the fix landed",
            "runtime_adapter": "claude",
            "model": "claude-sonnet-5",
            "internal": True,
            "origin_product": Task.OriginProduct.ERROR_TRACKING,
        }
        defaults.update(overrides)
        return Loop.objects.unscoped().create(**defaults)

    def test_internal_loops_are_reachable_through_the_internal_facade(self):
        from products.tasks.backend.facade import loops as loops_facade

        loop = self._make_internal_loop()

        fetched = loops_facade.get_internal_loop(loop.id, self.team.id)
        assert fetched is not None
        self.assertEqual(fetched.id, loop.id)
        listed = loops_facade.list_internal_loops(self.team.id, origin_product=Task.OriginProduct.ERROR_TRACKING)
        self.assertIn(loop.id, [item.id for item in listed])

        self.assertTrue(loops_facade.delete_internal_loop(loop.id, self.team.id))
        loop.refresh_from_db()
        self.assertTrue(loop.deleted)
        self.assertIsNone(loops_facade.get_internal_loop(loop.id, self.team.id))

    def test_internal_facade_does_not_reach_user_facing_loops(self):
        from products.tasks.backend.facade import loops as loops_facade

        user_loop_id = self._create_loop(self.owner_client)["id"]
        self.assertIsNone(loops_facade.get_internal_loop(user_loop_id, self.team.id))
        self.assertFalse(loops_facade.delete_internal_loop(user_loop_id, self.team.id))

    def test_create_loop_rejects_a_cross_team_github_integration(self):
        from products.tasks.backend.facade import loops as loops_facade
        from products.tasks.backend.facade.loops import LoopValidationError

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        foreign_integration = Integration.objects.create(
            team=other_team, kind="github", integration_id="999", config={}
        )

        with self.assertRaises(LoopValidationError):
            loops_facade.create_loop(
                self.team.id,
                self.owner,
                {
                    "name": "x",
                    "instructions": "y",
                    "runtime_adapter": "claude",
                    "model": "claude-sonnet-5",
                    "repositories": [{"github_integration_id": foreign_integration.id, "full_name": "acme/repo"}],
                },
            )

    @patch("products.tasks.backend.facade.loops.GitHubIntegration")
    def test_repository_access_requires_an_exact_cache_match(self, mock_github):
        integration = Integration.objects.create(team=self.team, kind="github", integration_id="1", config={})
        mock_github.return_value.list_all_cached_repositories.return_value = [{"full_name": "acme/allowed"}]

        self.assertTrue(
            loops_facade.repository_accessible_via_integration(self.team.id, integration.id, "acme/allowed")
        )
        self.assertFalse(loops_facade.repository_accessible_via_integration(self.team.id, integration.id, "acme/other"))

    @patch("products.tasks.backend.facade.loops.GitHubIntegration")
    def test_repository_access_fails_closed_when_the_repo_list_is_unavailable(self, mock_github):
        # A cold or invalidated cache that can't be refreshed must reject, not authorize: otherwise a
        # member could point a loop at another project's private repo reachable by the shared install.
        integration = Integration.objects.create(team=self.team, kind="github", integration_id="1", config={})
        mock_github.return_value.list_all_cached_repositories.side_effect = Exception("github unavailable")

        self.assertFalse(
            loops_facade.repository_accessible_via_integration(self.team.id, integration.id, "acme/allowed")
        )

    def test_malformed_behaviors_row_does_not_break_the_loop_list(self):
        # A facade-bypass or backfill could leave a malformed behaviors shape; one bad row must not
        # 500 the whole list read.
        self._make_internal_loop(internal=False, visibility="team", behaviors={"max_fix_iterations": "not-an-int"})

        response = self.owner_client.get(self._loops_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)


@pytest.mark.ee
class LoopObjectAccessControlAPITest(LoopsAPITestCase):
    """Object-level RBAC (`AccessControl` rows with resource="loop"). The viewset never calls
    `check_object_permissions` (the facade owns object loading), so `AccessControlPermission.
    has_permission` admits anyone with a grant on ANY loop and the facade must enforce which one."""

    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.loop_a = self._create_loop(self.owner_client, visibility="team")
        self.loop_b = self._create_loop(self.owner_client, visibility="team")

    def _grant(self, user: User, resource_id: str | None, access_level: str) -> None:
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="loop",
            resource_id=resource_id,
            access_level=access_level,
            organization_member=membership,
        )

    def test_a_specific_grant_does_not_open_other_loops(self):
        AccessControl.objects.create(team=self.team, resource="loop", resource_id=None, access_level="none")
        self._grant(self.peer, self.loop_a["id"], "viewer")

        list_response = self.peer_client.get(self._loops_url())
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual({row["id"] for row in list_response.json()["results"]}, {self.loop_a["id"]})

        self.assertEqual(self.peer_client.get(self._loop_url(self.loop_a["id"])).status_code, status.HTTP_200_OK)
        loop_b_url = self._loop_url(self.loop_b["id"])
        self.assertEqual(self.peer_client.get(loop_b_url).status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.peer_client.get(f"{loop_b_url}runs/").status_code, status.HTTP_404_NOT_FOUND)
        preview = self.peer_client.post(f"{loop_b_url}preview/", {"trigger_type": "schedule"}, format="json")
        self.assertEqual(preview.status_code, status.HTTP_404_NOT_FOUND)

    def test_an_editor_grant_on_one_loop_does_not_let_writes_reach_another(self):
        AccessControl.objects.create(team=self.team, resource="loop", resource_id=None, access_level="none")
        self._grant(self.peer, self.loop_a["id"], "editor")

        allowed = self.peer_client.patch(self._loop_url(self.loop_a["id"]), {"name": "renamed"}, format="json")
        self.assertEqual(allowed.status_code, status.HTTP_200_OK, allowed.content)

        loop_b_url = self._loop_url(self.loop_b["id"])
        self.assertEqual(
            self.peer_client.patch(loop_b_url, {"name": "x"}, format="json").status_code, status.HTTP_404_NOT_FOUND
        )
        self.assertEqual(
            self.peer_client.post(f"{loop_b_url}run/", {}, format="json").status_code, status.HTTP_404_NOT_FOUND
        )

    def test_a_loop_pinned_to_viewer_blocks_member_writes_but_not_reads(self):
        AccessControl.objects.create(
            team=self.team, resource="loop", resource_id=self.loop_a["id"], access_level="viewer"
        )
        loop_a_url = self._loop_url(self.loop_a["id"])

        self.assertEqual(self.peer_client.get(loop_a_url).status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.peer_client.patch(loop_a_url, {"name": "x"}, format="json").status_code, status.HTTP_403_FORBIDDEN
        )
        self.assertEqual(
            self.peer_client.post(f"{loop_a_url}run/", {}, format="json").status_code, status.HTTP_403_FORBIDDEN
        )
        # The owner keeps editing their own loop via the RBAC creator precheck.
        owner_patch = self.owner_client.patch(loop_a_url, {"name": "mine"}, format="json")
        self.assertEqual(owner_patch.status_code, status.HTTP_200_OK, owner_patch.content)

    def test_activity_log_restriction_honors_loop_rbac(self):
        # A loop hidden from the list must not leak its config history through the activity feed.
        from posthog.api.advanced_activity_logs.viewset import restrict_loop_activity
        from posthog.models.activity_logging.activity_log import ActivityLog

        AccessControl.objects.create(team=self.team, resource="loop", resource_id=None, access_level="none")
        self._grant(self.peer, self.loop_a["id"], "viewer")

        base = ActivityLog.objects.filter(team_id=self.team.id, scope="Loop")
        peer_ids = {row.item_id for row in restrict_loop_activity(base, self.team.id, self.peer)}

        self.assertIn(self.loop_a["id"], peer_ids)
        self.assertNotIn(self.loop_b["id"], peer_ids)


class LoopActivityLogVisibilityAPITest(LoopsAPITestCase):
    def test_personal_loop_activity_is_hidden_from_a_teammate(self):
        from posthog.api.advanced_activity_logs.viewset import restrict_loop_activity
        from posthog.models.activity_logging.activity_log import ActivityLog

        personal = self._create_loop(self.owner_client, visibility="personal")
        team = self._create_loop(self.owner_client, visibility="team")

        base = ActivityLog.objects.filter(team_id=self.team.id, scope="Loop")
        owner_ids = {row.item_id for row in restrict_loop_activity(base, self.team.id, self.owner)}
        peer_ids = {row.item_id for row in restrict_loop_activity(base, self.team.id, self.peer)}

        self.assertIn(personal["id"], owner_ids)
        self.assertIn(team["id"], owner_ids)
        self.assertNotIn(personal["id"], peer_ids)
        self.assertIn(team["id"], peer_ids)

    def test_deleted_personal_loop_activity_stays_hidden_org_wide(self):
        # ActivityLog outlives its loop: project deletion cascades the Loop row away while the log
        # keeps plain team/org ids, so the org route must judge rows by their persisted context
        # (visibility + owner snapshotted at log time), not by live loop rows.
        from posthog.api.advanced_activity_logs.viewset import restrict_loop_activity_for_org
        from posthog.models.activity_logging.activity_log import ActivityLog

        personal = self._create_loop(self.owner_client, visibility="personal")
        Loop.objects.unscoped().filter(pk=personal["id"]).delete()

        base = ActivityLog.objects.filter(scope="Loop")
        owner_ids = {row.item_id for row in restrict_loop_activity_for_org(base, self.organization.id, self.owner)}
        peer_ids = {row.item_id for row in restrict_loop_activity_for_org(base, self.organization.id, self.peer)}

        self.assertIn(personal["id"], owner_ids)
        self.assertNotIn(personal["id"], peer_ids)


class LoopTriggerPayloadCapAPITest(LoopsAPITestCase):
    def _psak_trigger(self, loop_id: str, payload: dict):
        raw_token = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="loop trigger key",
            secure_value=hash_key_value(raw_token),
            scopes=["loop:write"],
            mask_value=f"{raw_token[:4]}...{raw_token[-4:]}",
        )
        return APIClient().post(
            f"{self._loop_url(loop_id)}trigger/",
            payload,
            format="json",
            headers={"authorization": f"Bearer {raw_token}"},
        )

    @parameterized.expand(
        [
            # Declared oversize length is rejected as 413 before the body is parsed.
            ("header_reports_true_size", False, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE),
            # A missing length (chunked/ASGI) can't be bounded pre-parse, so it's refused as 411
            # rather than allowed to stream up to the global upload limit.
            ("header_absent_requires_length", True, status.HTTP_411_LENGTH_REQUIRED),
        ]
    )
    def test_oversized_trigger_payload_is_rejected_without_creating_a_task(
        self, _name, simulate_missing_header, expected_status
    ):
        loop_id = self._create_loop(self.owner_client, triggers=[{"type": "api", "config": {}}])["id"]
        oversized = {"context": "x" * MAX_LOOP_TRIGGER_PAYLOAD_BYTES}
        # The WSGI test client always sends an accurate Content-Length; the header-absent condition
        # is simulated by zeroing the header read.
        header_ctx = (
            patch("products.tasks.backend.presentation.views.loops._content_length", return_value=0)
            if simulate_missing_header
            else nullcontext()
        )

        with header_ctx:
            response = self._psak_trigger(loop_id, oversized)

        self.assertEqual(response.status_code, expected_status)
        self.assertEqual(Task.objects.count(), 0)


class LoopTriggerAuthAPITest(LoopsAPITestCase):
    def test_teammate_cannot_fire_another_members_personal_loop_via_session(self):
        # The trigger endpoint also accepts session/PAT/OAuth auth, but firing must then respect the
        # personal/team visibility split — a PSAK's project-wide bypass is only for the service
        # credential. Without the split, a teammate with a personal loop's UUID could start a run
        # under its owner's OAuth/GitHub/MCP authority.
        loop_id = self._create_loop(self.owner_client, visibility="personal", triggers=[{"type": "api", "config": {}}])[
            "id"
        ]

        response = self.peer_client.post(f"{self._loop_url(loop_id)}trigger/", {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(Task.objects.count(), 0)

    def test_owner_can_fire_their_own_personal_loop_via_session(self):
        # Over-block guard: scoping the non-PSAK trigger path must not break the legitimate case of
        # a user firing a loop they can see.
        loop_id = self._create_loop(self.owner_client, visibility="personal", triggers=[{"type": "api", "config": {}}])[
            "id"
        ]

        response = self.owner_client.post(f"{self._loop_url(loop_id)}trigger/", {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(Task.objects.filter(team=self.team, origin_product=Task.OriginProduct.LOOP).count(), 1)

    def test_teammate_cannot_trigger_a_team_loop_with_a_payload(self):
        # The trigger payload becomes agent prompt content and the run executes as the loop owner, so
        # a non-owner member must not trigger a team loop by API — that would run their injected
        # instructions under the owner's credentials. They can still fire it as themselves via `run`.
        loop_id = self._create_loop(self.owner_client, visibility="team", triggers=[{"type": "api", "config": {}}])[
            "id"
        ]

        response = self.peer_client.post(
            f"{self._loop_url(loop_id)}trigger/", {"context": "exfiltrate secrets"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(Task.objects.filter(team=self.team, origin_product=Task.OriginProduct.LOOP).count(), 0)
