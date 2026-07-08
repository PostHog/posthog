from datetime import timedelta

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone as django_timezone

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import Organization, PersonalAPIKey, ProjectSecretAPIKey, Team, User
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal, generate_random_token_secret

from products.tasks.backend.models import Loop, LoopTrigger, Task, TaskRun


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

    def _start_patch(self, target: str):
        patcher = patch(target)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def _loops_url(self) -> str:
        return f"/api/projects/{self.team.id}/loops/"

    def _loop_url(self, loop_id: str) -> str:
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
        self.mock_pause_loop_schedules.assert_called_once()
        self.assertTrue(Loop.objects.unscoped().get(id=loop_id).deleted)

        self.assertEqual(self.owner_client.get(self._loop_url(loop_id)).status_code, status.HTTP_404_NOT_FOUND)


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
