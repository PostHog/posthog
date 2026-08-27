from datetime import datetime, timedelta
from uuid import uuid4

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone as django_timezone

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import Integration, Organization, OrganizationMembership, PersonalAPIKey, Team, User
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal

from products.tasks.backend.exceptions import ComputeBillingLimitError
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.onboarding_canvas import TeachingCanvas
from products.tasks.backend.models import Channel, ChannelFeedMessage, Task, TaskActivity, TaskRun, TaskThreadMessage
from products.tasks.backend.push_dispatcher import (
    notify_task_run_awaiting_input,
    notify_task_run_completed,
    notify_task_run_turn_completed,
)


class ChannelsAPITestCase(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Growth Team")
        self.user = User.objects.create_user(email="author@example.com", first_name="Ann", password="password")
        self.other_user = User.objects.create_user(email="peer@example.com", first_name="Bob", password="password")
        for user in (self.user, self.other_user):
            self.organization.members.add(user)
            OrganizationMembership.objects.filter(user=user, organization=self.organization).update(
                level=OrganizationMembership.Level.ADMIN
            )

        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _provision(self, client=None) -> dict:
        response = (client or self.client).post(f"{self._channels_url()}provision_defaults/")
        assert response.status_code == status.HTTP_200_OK, response.content
        return response.json()

    def _channels_url(self) -> str:
        return f"/api/projects/{self.team.id}/task_channels/"

    def _tasks_url(self) -> str:
        return f"/api/projects/{self.team.id}/tasks/"

    def test_provision_creates_personal_channel(self):
        provisioned = self._provision()
        self.assertTrue(provisioned["personal_created"])
        personal = [c for c in provisioned["channels"] if c["channel_type"] == "personal"]
        self.assertEqual(len(personal), 1)
        self.assertEqual(personal[0]["name"], "me")
        self.assertEqual(personal[0]["created_by"]["id"], self.user.id)

        again = self._provision()
        self.assertFalse(again["personal_created"])
        self.assertEqual(
            [c["id"] for c in again["channels"] if c["channel_type"] == "personal"],
            [personal[0]["id"]],
        )

    @parameterized.expand(
        [
            ("write_scope", "task:write", status.HTTP_200_OK),
            ("read_scope", "task:read", status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_provisioning_over_a_scoped_token_needs_task_write(self, _name, scope, expected_status):
        # Desktop authenticates with an OAuth bearer token, so an action missing from the
        # write-scope list is refused before its scopes are even read.
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user, label=f"provisioning {scope}", secure_value=hash_key_value(key), scopes=[scope]
        )

        response = APIClient().post(
            f"{self._channels_url()}provision_defaults/", headers={"authorization": f"Bearer {key}"}
        )
        self.assertEqual(response.status_code, expected_status, response.content)

    def test_list_does_not_provision(self):
        response = self.client.get(self._channels_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), [])
        self.assertFalse(Channel.objects.for_team(self.team.id).exists())

    def test_personal_channels_are_per_user(self):
        mine = self._provision()["channels"]
        other_client = APIClient()
        other_client.force_authenticate(self.other_user)
        theirs = self._provision(other_client)["channels"]

        my_personal = [c["id"] for c in mine if c["channel_type"] == "personal"]
        their_personal = [c["id"] for c in theirs if c["channel_type"] == "personal"]
        self.assertNotEqual(my_personal, their_personal)
        self.assertNotIn(my_personal[0], [c["id"] for c in theirs])

    def test_resolve_or_create_public_channel(self):
        first = self.client.post(self._channels_url(), {"name": "Growth Ideas"})
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(first.json()["name"], "growth-ideas")
        second = self.client.post(self._channels_url(), {"name": "growth ideas"})
        self.assertEqual(second.json()["id"], first.json()["id"])

    def test_personal_channel_cannot_be_renamed_or_deleted(self):
        self._provision()
        # Direct ORM reads in tests bypass the DRF-set team context, so opt out
        # of the fail-closed scoping explicitly (see test_presence.py).
        personal = Channel.objects.unscoped().get(team=self.team, channel_type=Channel.ChannelType.PERSONAL)
        rename = self.client.patch(f"{self._channels_url()}{personal.id}/", {"name": "not-me"})
        self.assertEqual(rename.status_code, status.HTTP_403_FORBIDDEN)
        delete = self.client.delete(f"{self._channels_url()}{personal.id}/")
        self.assertEqual(delete.status_code, status.HTTP_403_FORBIDDEN)

    def test_provision_creates_general_channel_once(self):
        first = self._provision()
        self.assertTrue(first["general_created"])
        general = [c for c in first["channels"] if c["system_role"] == "general"]
        self.assertEqual(len(general), 1)
        self.assertEqual(general[0]["name"], "general")
        self.assertEqual(general[0]["channel_type"], "public")
        self.assertFalse(general[0]["starred"])

        other_client = APIClient()
        other_client.force_authenticate(self.other_user)
        again = self._provision(other_client)
        self.assertFalse(again["general_created"])
        self.assertEqual(
            [c["id"] for c in again["channels"] if c["system_role"] == "general"],
            [general[0]["id"]],
        )

    @patch("products.tasks.backend.presentation.views.channels_api.onboarding_test_tools_enabled", return_value=False)
    def test_onboarding_test_tools_require_the_feature_flag(self, _enabled):
        for action in ("onboarding_session_test", "teaching_canvas_test"):
            response = self.client.post(f"{self._channels_url()}{action}/", {}, format="json")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("products.tasks.backend.presentation.views.channels_api.onboarding_test_tools_enabled", return_value=True)
    def test_flagged_user_can_create_test_onboarding_artifacts(self, _enabled):
        personal_id = next(
            channel["id"] for channel in self._provision()["channels"] if channel["system_role"] == "personal"
        )
        task_id = uuid4()
        canvas_id = uuid4()

        with patch(
            "products.tasks.backend.presentation.views.channels_api.start_onboarding_test_session", return_value=task_id
        ) as start:
            response = self.client.post(
                f"{self._channels_url()}onboarding_session_test/",
                {"joining_existing_organization": True, "other_members": ["Max"], "has_events": True},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.json(), {"task_id": str(task_id), "channel_id": personal_id})
        self.assertTrue(start.call_args.kwargs["joining_existing_organization"])
        self.assertEqual(start.call_args.kwargs["other_members"], ["Max"])

        teaching = TeachingCanvas(channel_id=uuid4(), canvas_id=canvas_id)
        with patch(
            "products.tasks.backend.presentation.views.channels_api.ensure_teaching_canvas", return_value=teaching
        ):
            response = self.client.post(f"{self._channels_url()}teaching_canvas_test/", {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.json(), {"canvas_id": str(canvas_id), "channel_id": str(teaching.channel_id)})

    @parameterized.expand(
        [
            ("rename", lambda client, url: client.patch(url, {"name": "not-general"})),
            ("delete", lambda client, url: client.delete(url)),
        ]
    )
    def test_general_channel_cannot_be_renamed_or_deleted(self, _name, act):
        self._provision()
        general = Channel.objects.unscoped().get(team=self.team, system_role=Channel.SystemRole.GENERAL)
        response = act(self.client, f"{self._channels_url()}{general.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_legacy_personal_channel_is_stamped_with_system_role_on_provision(self):
        # A row from before the role existed is identified by channel_type alone.
        legacy = Channel.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            created_by=self.user,
            name=Channel.PERSONAL_CHANNEL_NAME,
            channel_type=Channel.ChannelType.PERSONAL,
        )

        provisioned = self._provision()
        self.assertFalse(provisioned["personal_created"])
        personal = [c for c in provisioned["channels"] if c["channel_type"] == "personal"]
        self.assertEqual([c["id"] for c in personal], [str(legacy.id)])
        self.assertEqual(personal[0]["system_role"], "personal")

        legacy.refresh_from_db()
        self.assertEqual(legacy.system_role, Channel.SystemRole.PERSONAL)

    def test_legacy_general_channel_is_adopted_and_stamped_on_provision(self):
        legacy = Channel.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            created_by=self.user,
            name=Channel.GENERAL_CHANNEL_NAME,
            channel_type=Channel.ChannelType.PUBLIC,
        )

        provisioned = self._provision()
        self.assertFalse(provisioned["general_created"])
        general = [c for c in provisioned["channels"] if c["system_role"] == "general"]
        self.assertEqual([c["id"] for c in general], [str(legacy.id)])

        legacy.refresh_from_db()
        self.assertEqual(legacy.system_role, Channel.SystemRole.GENERAL)

    @parameterized.expand(
        [
            ("hash_prefix", "#growth", "growth"),
            ("spaces", "Growth Ideas", "growth-ideas"),
            ("punctuation", "team.core!", "team-core"),
            ("surrounding_separators", "  --growth--  ", "growth"),
        ]
    )
    def test_a_created_space_takes_the_name_desktop_showed(self, _name, sent, stored):
        # The field normalizes as the user types, so the server has to agree with it.
        response = self.client.post(self._channels_url(), {"name": sent})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.json()["name"], stored)

    def test_a_name_with_nothing_usable_in_it_is_rejected(self):
        response = self.client.post(self._channels_url(), {"name": "###"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_finding_the_general_space_never_provisions_one(self):
        # Products that file work into #general gate on it existing, so a lookup that
        # created one would put a space in every team that never asked for Desktop.
        self.assertIsNone(tasks_facade.find_general_channel_id(self.team.id))

        provisioned = self._provision()
        general = next(c for c in provisioned["channels"] if c["system_role"] == "general")
        self.assertEqual(str(tasks_facade.find_general_channel_id(self.team.id)), general["id"])

    def test_finding_the_general_space_matches_an_unstamped_row(self):
        legacy = Channel.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            created_by=self.user,
            name=Channel.GENERAL_CHANNEL_NAME,
            channel_type=Channel.ChannelType.PUBLIC,
        )

        self.assertEqual(tasks_facade.find_general_channel_id(self.team.id), legacy.id)

    def test_creating_a_space_named_general_resolves_the_system_space(self):
        created = self.client.post(self._channels_url(), {"name": "General"})
        self.assertEqual(created.status_code, status.HTTP_200_OK)
        self.assertEqual(created.json()["system_role"], "general")

        provisioned = self._provision()
        self.assertFalse(provisioned["general_created"])
        self.assertEqual(
            [c["id"] for c in provisioned["channels"] if c["system_role"] == "general"],
            [created.json()["id"]],
        )

    @parameterized.expand([("stored_name", "Me"), ("display_label", " personal ")])
    def test_a_shared_space_cannot_claim_a_personal_space_name(self, _name, name):
        response = self.client.post(self._channels_url(), {"name": name})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand([("personal_name", "me"), ("personal_label", "personal"), ("general", "General")])
    def test_a_space_cannot_be_renamed_to_a_reserved_name(self, _name, name):
        channel_id = self.client.post(self._channels_url(), {"name": "growth"}).json()["id"]

        response = self.client.patch(f"{self._channels_url()}{channel_id}/", {"name": name})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand(
        [
            ("rename", lambda client, url: client.patch(url, {"name": "not-general"})),
            ("delete", lambda client, url: client.delete(url)),
        ]
    )
    def test_unstamped_general_channel_cannot_be_renamed_or_deleted(self, _name, act):
        # Desktop reads an unstamped row named "general" as the team's general space, so
        # the server has to protect it on the same terms.
        legacy = Channel.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            created_by=self.user,
            name=Channel.GENERAL_CHANNEL_NAME,
            channel_type=Channel.ChannelType.PUBLIC,
        )

        response = act(self.client, f"{self._channels_url()}{legacy.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("posthog.models.integration.github.GitHubIntegration.list_all_cached_repositories")
    def test_cannot_configure_someone_elses_personal_channel_repositories(self, list_repositories):
        list_repositories.return_value = [{"full_name": "posthog/posthog"}]
        integration = Integration.objects.create(team=self.team, kind="github", integration_id="1", config={})
        self._provision()
        personal = Channel.objects.unscoped().get(team=self.team, channel_type=Channel.ChannelType.PERSONAL)

        other_client = APIClient()
        other_client.force_authenticate(self.other_user)
        sneaky = other_client.patch(
            f"{self._channels_url()}{personal.id}/",
            {"github_integration": integration.id, "repositories": ["posthog/posthog"]},
            format="json",
        )
        self.assertEqual(sneaky.status_code, status.HTTP_404_NOT_FOUND)
        personal.refresh_from_db()
        self.assertEqual(personal.repositories, [])

        owned = self.client.patch(
            f"{self._channels_url()}{personal.id}/",
            {"github_integration": integration.id, "repositories": ["posthog/posthog"]},
            format="json",
        )
        self.assertEqual(owned.status_code, status.HTTP_200_OK, owned.content)
        self.assertEqual(owned.json()["repositories"], ["posthog/posthog"])

    def test_task_created_in_public_channel_is_team_visible(self):
        channel_id = self.client.post(self._channels_url(), {"name": "growth"}).json()["id"]
        created = self.client.post(
            self._tasks_url(),
            {"title": "Ship it", "description": "Do the thing", "channel": channel_id},
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.content)
        self.assertEqual(created.json()["channel"], channel_id)

        other_client = APIClient()
        other_client.force_authenticate(self.other_user)
        listed = other_client.get(self._tasks_url(), {"channel": channel_id}).json()["results"]
        self.assertEqual([t["id"] for t in listed], [created.json()["id"]])

    def test_deleting_github_integration_clears_channel_repositories(self):
        integration = Integration.objects.create(team=self.team, kind="github", integration_id="1", config={})
        channel = Channel.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            name="growth",
            github_integration=integration,
            repositories=["posthog/posthog"],
        )

        Integration.objects.filter(id=integration.id).delete()

        channel.refresh_from_db()
        self.assertIsNone(channel.github_integration_id)
        self.assertEqual(channel.repositories, [])

    @patch("posthog.models.integration.github.GitHubIntegration.list_all_cached_repositories")
    def test_new_tasks_inherit_channel_repositories(self, list_repositories):
        list_repositories.return_value = [
            {"full_name": "posthog/posthog"},
            {"full_name": "posthog/posthog-js"},
        ]
        integration = Integration.objects.create(team=self.team, kind="github", integration_id="1", config={})
        channel_id = self.client.post(self._channels_url(), {"name": "growth"}).json()["id"]
        configured = self.client.patch(
            f"{self._channels_url()}{channel_id}/",
            {
                "github_integration": integration.id,
                "repositories": ["posthog/posthog", "posthog/posthog-js"],
            },
            format="json",
        )
        self.assertEqual(configured.status_code, status.HTTP_200_OK, configured.content)

        created = self.client.post(
            self._tasks_url(),
            {"title": "Ship it", "description": "Do the thing", "channel": channel_id},
        )

        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.content)
        self.assertEqual(created.json()["repositories"], ["posthog/posthog", "posthog/posthog-js"])
        self.assertEqual(created.json()["github_integration"], integration.id)

    @patch("posthog.models.integration.github.GitHubIntegration.list_all_cached_repositories")
    def test_project_member_can_configure_or_rename_public_channel(self, list_repositories):
        list_repositories.return_value = [{"full_name": "posthog/posthog"}]
        integration = Integration.objects.create(team=self.team, kind="github", integration_id="1", config={})
        channel_id = self.client.post(self._channels_url(), {"name": "growth"}).json()["id"]

        other_client = APIClient()
        other_client.force_authenticate(self.other_user)
        response = other_client.patch(
            f"{self._channels_url()}{channel_id}/",
            {"github_integration": integration.id, "repositories": ["posthog/posthog"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        channel = Channel.objects.unscoped().get(id=channel_id)
        self.assertEqual(channel.repositories, ["posthog/posthog"])
        self.assertEqual(channel.github_integration_id, integration.id)

        renamed = other_client.patch(f"{self._channels_url()}{channel_id}/", {"name": "renamed"}, format="json")
        self.assertEqual(renamed.status_code, status.HTTP_200_OK, renamed.content)
        self.assertEqual(Channel.objects.unscoped().get(id=channel_id).name, "renamed")

    def test_public_channel_task_is_readable_but_not_controllable_by_teammates(self):
        channel_id = self.client.post(self._channels_url(), {"name": "growth"}).json()["id"]
        created = self.client.post(
            self._tasks_url(),
            {"title": "Ship it", "description": "d", "channel": channel_id},
        )
        task_id = created.json()["id"]

        other_client = APIClient()
        other_client.force_authenticate(self.other_user)
        # Channel visibility grants reads: detail and the runs list.
        self.assertEqual(other_client.get(f"{self._tasks_url()}{task_id}/").status_code, status.HTTP_200_OK)
        self.assertEqual(other_client.get(f"{self._tasks_url()}{task_id}/runs/").status_code, status.HTTP_200_OK)
        # But never control: edits, deletes, and run creation stay author-only.
        self.assertEqual(
            other_client.patch(f"{self._tasks_url()}{task_id}/", {"title": "hijack"}).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            other_client.delete(f"{self._tasks_url()}{task_id}/").status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            other_client.post(f"{self._tasks_url()}{task_id}/runs/", {}).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    @parameterized.expand(
        [
            ("explicit", True),
            ("default", False),
        ]
    )
    def test_task_in_private_space_stays_private(self, _name: str, select_channel: bool):
        self._provision()
        personal = Channel.objects.unscoped().get(team=self.team, channel_type=Channel.ChannelType.PERSONAL)
        payload = {"title": "Secret", "description": "mine"}
        if select_channel:
            payload["channel"] = str(personal.id)
        created = self.client.post(self._tasks_url(), payload)
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.content)
        self.assertEqual(created.json()["channel"], str(personal.id))

        other_client = APIClient()
        other_client.force_authenticate(self.other_user)
        listed = other_client.get(self._tasks_url(), {"channel": str(personal.id)}).json()["results"]
        self.assertEqual(listed, [])
        self.assertEqual(
            other_client.get(f"{self._tasks_url()}{created.json()['id']}/").status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_team_readable_origin_does_not_widen_private_space(self):
        self._provision()
        personal = Channel.objects.unscoped().get(team=self.team, channel_type=Channel.ChannelType.PERSONAL)
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            channel=personal,
            title="Private signal task",
            description="private",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
        )

        other_client = APIClient()
        other_client.force_authenticate(self.other_user)

        self.assertEqual(
            other_client.get(f"{self._tasks_url()}{task.id}/").status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_task_controller_can_move_task_between_public_spaces(self):
        first = self.client.post(self._channels_url(), {"name": "first"}).json()["id"]
        second = self.client.post(self._channels_url(), {"name": "second"}).json()["id"]
        task = self.client.post(
            self._tasks_url(),
            {"title": "Move me", "description": "d", "channel": first},
        ).json()

        response = self.client.patch(f"{self._tasks_url()}{task['id']}/", {"channel": second}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(str(Task.objects.get(id=task["id"]).channel_id), second)

    def test_task_controller_can_move_public_task_to_private_space(self):
        public_space_id = self.client.post(self._channels_url(), {"name": "shared"}).json()["id"]
        private_space_id = next(
            space["id"] for space in self._provision()["channels"] if space["channel_type"] == "personal"
        )
        task = self.client.post(
            self._tasks_url(),
            {"title": "Move private", "description": "d", "channel": public_space_id},
        ).json()

        moved = self.client.patch(
            f"{self._tasks_url()}{task['id']}/",
            {"channel": private_space_id},
            format="json",
        )
        other_client = APIClient()
        other_client.force_authenticate(self.other_user)

        self.assertEqual(moved.status_code, status.HTTP_200_OK, moved.content)
        self.assertEqual(moved.json()["channel"], private_space_id)
        self.assertEqual(
            other_client.get(f"{self._tasks_url()}{task['id']}/").status_code,
            status.HTTP_404_NOT_FOUND,
        )

        clear = self.client.patch(f"{self._tasks_url()}{task['id']}/", {"channel": None}, format="json")
        self.assertEqual(clear.status_code, status.HTTP_200_OK)
        self.assertIsNone(Task.objects.get(id=task["id"]).channel_id)

    def test_project_member_can_delete_an_empty_public_space(self):
        channel_id = self.client.post(self._channels_url(), {"name": "empty"}).json()["id"]
        other_client = APIClient()
        other_client.force_authenticate(self.other_user)

        self.assertEqual(
            other_client.delete(f"{self._channels_url()}{channel_id}/").status_code,
            status.HTTP_204_NO_CONTENT,
        )

    def test_non_empty_public_space_cannot_be_deleted(self):
        channel_id = self.client.post(self._channels_url(), {"name": "active"}).json()["id"]
        self.client.post(
            self._tasks_url(),
            {"title": "Keep me", "description": "d", "channel": channel_id},
        )

        response = self.client.delete(f"{self._channels_url()}{channel_id}/")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertFalse(Channel.objects.unscoped().get(id=channel_id).deleted)

    def test_space_holding_only_archived_tasks_can_be_deleted(self):
        channel_id = self.client.post(self._channels_url(), {"name": "wrapped-up"}).json()["id"]
        task_id = self.client.post(
            self._tasks_url(),
            {"title": "Done with this", "description": "d", "channel": channel_id},
        ).json()["id"]
        self.client.patch(f"{self._tasks_url()}{task_id}/", {"archived": True}, format="json")

        response = self.client.delete(f"{self._channels_url()}{channel_id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT, response.content)
        self.assertTrue(Channel.objects.unscoped().get(id=channel_id).deleted)
        self.assertIsNone(Task.objects.get(id=task_id).channel_id)
        listed = self.client.get(f"{self._tasks_url()}?archived=true").json()["results"]
        self.assertEqual([task["id"] for task in listed], [task_id])

    def test_cannot_file_task_into_someone_elses_personal_channel(self):
        self._provision()
        personal = Channel.objects.unscoped().get(team=self.team, channel_type=Channel.ChannelType.PERSONAL)
        other_client = APIClient()
        other_client.force_authenticate(self.other_user)
        response = other_client.post(
            self._tasks_url(),
            {"title": "Sneaky", "description": "nope", "channel": str(personal.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class ChannelTaskAPITestCase(TestCase):
    """Shared fixture: an org with two members, a public channel, and a task in it."""

    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Growth Team")
        self.author = User.objects.create_user(email="author@example.com", first_name="Ann", password="password")
        self.peer = User.objects.create_user(email="peer@example.com", first_name="Bob", password="password")
        for user in (self.author, self.peer):
            self.organization.members.add(user)
            OrganizationMembership.objects.filter(user=user, organization=self.organization).update(
                level=OrganizationMembership.Level.ADMIN
            )

        # Direct instantiation sidesteps the fail-closed TeamScopedManager so
        # setUp doesn't need a team_scope wrapper (see test_presence.py).
        self.channel = Channel(team=self.team, name="growth", created_by=self.author)
        self.channel.save()
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.author,
            channel=self.channel,
            title="A Task",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

        self.author_client = APIClient()
        self.author_client.force_authenticate(self.author)
        self.peer_client = APIClient()
        self.peer_client.force_authenticate(self.peer)


class ThreadMessagesAPITestCase(ChannelTaskAPITestCase):
    def _thread_url(self) -> str:
        return f"/api/projects/{self.team.id}/tasks/{self.task.id}/thread_messages/"

    def test_post_and_list_thread_messages(self):
        posted = self.peer_client.post(self._thread_url(), {"content": "What about mobile?"})
        self.assertEqual(posted.status_code, status.HTTP_201_CREATED, posted.content)
        self.assertEqual(posted.json()["author"]["id"], self.peer.id)
        self.assertIsNone(posted.json()["forwarded_to_agent_at"])

        listed = self.author_client.get(self._thread_url()).json()
        self.assertEqual([m["content"] for m in listed], ["What about mobile?"])

    def test_delete_is_author_only(self):
        message_id = self.peer_client.post(self._thread_url(), {"content": "mine"}).json()["id"]
        forbidden = self.author_client.delete(f"{self._thread_url()}{message_id}/")
        self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)
        allowed = self.peer_client.delete(f"{self._thread_url()}{message_id}/")
        self.assertEqual(allowed.status_code, status.HTTP_204_NO_CONTENT)

    def test_send_to_agent_is_task_author_only(self):
        message_id = self.peer_client.post(self._thread_url(), {"content": "try X"}).json()["id"]
        response = self.peer_client.post(f"{self._thread_url()}{message_id}/send_to_agent/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_send_to_agent_requires_live_run(self):
        message_id = self.peer_client.post(self._thread_url(), {"content": "try X"}).json()["id"]
        response = self.author_client.post(f"{self._thread_url()}{message_id}/send_to_agent/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_send_to_agent_forwards_and_stamps(self):
        run = TaskRun.objects.create(task=self.task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        message_id = self.peer_client.post(self._thread_url(), {"content": "try X"}).json()["id"]

        with patch("products.tasks.backend.facade.api.signal_task_run_user_message", return_value=True) as signal:
            response = self.author_client.post(f"{self._thread_url()}{message_id}/send_to_agent/")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertIsNotNone(response.json()["forwarded_to_agent_at"])
        self.assertEqual(response.json()["forwarded_by"]["id"], self.author.id)
        signal.assert_called_once()
        self.assertIn("Bob", signal.call_args.kwargs["content"])
        self.assertIn("try X", signal.call_args.kwargs["content"])
        self.assertEqual(
            TaskThreadMessage.objects.unscoped().get(id=message_id).forwarded_run_id,
            run.id,
        )

        again = self.author_client.post(f"{self._thread_url()}{message_id}/send_to_agent/")
        self.assertEqual(again.status_code, status.HTTP_400_BAD_REQUEST)

    def test_send_to_agent_returns_structured_compute_quota_denial(self):
        TaskRun.objects.create(task=self.task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        message_id = self.peer_client.post(self._thread_url(), {"content": "try X"}).json()["id"]

        with patch(
            "products.tasks.backend.facade.api.signal_task_run_user_message",
            side_effect=ComputeBillingLimitError({"team_id": self.team.id}),
        ):
            response = self.author_client.post(f"{self._thread_url()}{message_id}/send_to_agent/")

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.json()["code"], "posthog_code_billing_limit_exceeded")
        self.assertIsNone(TaskThreadMessage.objects.unscoped().get(id=message_id).forwarded_to_agent_at)

    def test_thread_hidden_when_task_not_visible(self):
        private_task = Task.objects.create(
            team=self.team,
            created_by=self.author,
            title="Private",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        url = f"/api/projects/{self.team.id}/tasks/{private_task.id}/thread_messages/"
        response = self.peer_client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TaskMentionsAPITestCase(ChannelTaskAPITestCase):
    def _mentions_url(self) -> str:
        return f"/api/projects/{self.team.id}/task_mentions/"

    def _thread_url(self, task) -> str:
        return f"/api/projects/{self.team.id}/tasks/{task.id}/thread_messages/"

    def _post_message(self, client, content: str, task=None) -> dict:
        response = client.post(self._thread_url(task or self.task), {"content": content})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        return response.json()

    def test_mention_appears_in_mentioned_users_feed(self):
        message = self._post_message(self.author_client, "ping @[Bob](peer@example.com), thoughts?")

        mentions = self.peer_client.get(self._mentions_url()).json()
        self.assertEqual(len(mentions), 1)
        self.assertEqual(mentions[0]["message_id"], message["id"])
        self.assertEqual(mentions[0]["task_id"], str(self.task.id))
        self.assertEqual(mentions[0]["task_title"], "A Task")
        self.assertEqual(mentions[0]["channel_id"], str(self.channel.id))
        self.assertEqual(mentions[0]["channel_name"], "growth")
        self.assertEqual(mentions[0]["author"]["id"], self.author.id)
        self.assertEqual(mentions[0]["content"], "ping @[Bob](peer@example.com), thoughts?")
        # The author wasn't mentioned, so their own feed stays empty.
        self.assertEqual(self.author_client.get(self._mentions_url()).json(), [])

    @patch("products.tasks.backend.push_dispatcher.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    def test_thread_message_notifies_creator_and_mentions_only(self, mock_delay, _flag):
        mentioned = User.objects.create_user(email="mentioned@example.com", first_name="Mina", password="password")
        unmentioned = User.objects.create_user(email="other@example.com", first_name="Other", password="password")
        self.organization.members.add(mentioned, unmentioned)

        with self.captureOnCommitCallbacks(execute=True):
            message = self._post_message(self.peer_client, "ping @[Mina](mentioned@example.com)")

        calls_by_user_id = {call.args[0]: call.args for call in mock_delay.call_args_list}
        self.assertEqual(set(calls_by_user_id), {self.author.id, mentioned.id})
        self.assertEqual(calls_by_user_id[self.author.id][3]["messageId"], message["id"])
        self.assertIn("replied", calls_by_user_id[self.author.id][2])
        self.assertIn("mentioned you", calls_by_user_id[mentioned.id][2])

    @patch("products.tasks.backend.push_dispatcher._enqueue_user")
    def test_thread_message_recipient_failures_are_isolated(self, mock_enqueue):
        mentioned = User.objects.create_user(email="mentioned@example.com", first_name="Mina", password="password")
        self.organization.members.add(mentioned)
        mock_enqueue.side_effect = [RuntimeError("redis is down"), None]

        self._post_message(self.peer_client, "ping @[Mina](mentioned@example.com)")

        self.assertEqual(mock_enqueue.call_count, 2)

    @patch("products.tasks.backend.facade.api.TaskActivity.record", side_effect=RuntimeError("db is down"))
    @patch("products.tasks.backend.push_dispatcher.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    def test_mention_activity_failure_does_not_discard_push_recipients(self, mock_delay, _flag, _record):
        mentioned = User.objects.create_user(email="mentioned@example.com", first_name="Mina", password="password")
        self.organization.members.add(mentioned)

        with self.captureOnCommitCallbacks(execute=True):
            self._post_message(self.peer_client, "ping @[Mina](mentioned@example.com)")

        self.assertEqual({call.args[0] for call in mock_delay.call_args_list}, {self.author.id, mentioned.id})

    def test_mentions_resolve_case_insensitively(self):
        self._post_message(self.author_client, "cc @[Bob](Peer@Example.COM)")
        self.assertEqual(len(self.peer_client.get(self._mentions_url()).json()), 1)

    def test_self_mentions_and_non_members_are_not_indexed(self):
        self._post_message(self.peer_client, "note to self @[Bob](peer@example.com)")
        self._post_message(self.author_client, "ask @[Sam](sam@other-org.example.com)")
        self.assertEqual(self.peer_client.get(self._mentions_url()).json(), [])
        self.assertEqual(self.author_client.get(self._mentions_url()).json(), [])

    def test_since_filters_by_created_at(self):
        self._post_message(self.author_client, "hey @[Bob](peer@example.com)")
        created_at = self.peer_client.get(self._mentions_url()).json()[0]["created_at"]

        after = self.peer_client.get(self._mentions_url(), {"since": created_at}).json()
        self.assertEqual(after, [])
        before = self.peer_client.get(self._mentions_url(), {"since": "2020-01-01T00:00:00Z"}).json()
        self.assertEqual(len(before), 1)

    def test_mentions_are_newest_first(self):
        first = self._post_message(self.author_client, "one @[Bob](peer@example.com)")
        second = self._post_message(self.author_client, "two @[Bob](peer@example.com)")
        ids = [m["message_id"] for m in self.peer_client.get(self._mentions_url()).json()]
        self.assertEqual(ids, [second["id"], first["id"]])

        limited = self.peer_client.get(self._mentions_url(), {"limit": 1}).json()
        self.assertEqual([m["message_id"] for m in limited], [second["id"]])

    def test_unparseable_since_is_a_400(self):
        response = self.peer_client.get(self._mentions_url(), {"since": "not-a-date"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("products.tasks.backend.push_dispatcher.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    def test_mention_on_invisible_task_is_hidden(self, mock_delay, _flag):
        private_task = Task.objects.create(
            team=self.team,
            created_by=self.author,
            title="Private",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        with self.captureOnCommitCallbacks(execute=True):
            self._post_message(self.author_client, "fyi @[Bob](peer@example.com)", task=private_task)
        self.assertEqual(self.peer_client.get(self._mentions_url()).json(), [])
        mock_delay.assert_not_called()

    def test_mentions_are_team_scoped(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_channel = Channel(team=other_team, name="growth", created_by=self.author)
        other_channel.save()
        other_task = Task.objects.create(
            team=other_team,
            created_by=self.author,
            channel=other_channel,
            title="Elsewhere",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        response = self.author_client.post(
            f"/api/projects/{other_team.id}/tasks/{other_task.id}/thread_messages/",
            {"content": "over here @[Bob](peer@example.com)"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)

        self.assertEqual(self.peer_client.get(self._mentions_url()).json(), [])
        other_team_mentions = self.peer_client.get(f"/api/projects/{other_team.id}/task_mentions/").json()
        self.assertEqual(len(other_team_mentions), 1)


class TaskActivityAPITestCase(ChannelTaskAPITestCase):
    def _activity_url(self) -> str:
        return f"/api/projects/{self.team.id}/task_activity/"

    def _thread_url(self, task=None) -> str:
        return f"/api/projects/{self.team.id}/tasks/{(task or self.task).id}/thread_messages/"

    def _post_message(self, client, content: str, task=None) -> dict:
        response = client.post(self._thread_url(task), {"content": content})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        return response.json()

    def _mark_read(self, client, activities) -> dict:
        response = client.post(self._activity_url() + "mark_read/", {"activities": activities}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        return response.json()

    def _rows(self, client) -> list[dict]:
        return client.get(self._activity_url()).json()["results"]

    def _row_for(self, client, task) -> dict:
        rows = [row for row in self._rows(client) if row["task_id"] == str(task.id)]
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    def _awaiting_input(self, task=None) -> None:
        run = TaskRun.objects.create(team=self.team, task=task or self.task, status=TaskRun.Status.IN_PROGRESS)
        # Go through the real notifier so the feed stays wired to whatever the product
        # treats as "the agent is waiting", but leave the push side (flag, cooldown,
        # Expo call) out of it.
        with patch("products.tasks.backend.push_dispatcher._enqueue"):
            notify_task_run_awaiting_input(run)

    def test_creator_sees_the_task_they_created(self):
        row = self._row_for(self.author_client, self.task)
        self.assertEqual(row["activity_kind"], "created")
        self.assertEqual(row["snippet"], "")
        self.assertEqual(row["channel_name"], "growth")
        # A teammate with no relationship to the task sees nothing.
        self.assertEqual(self._rows(self.peer_client), [])

    @parameterized.expand(
        [
            ("internal", {"internal": True}),
            ("archived", {"archived": True}),
        ]
    )
    def test_hidden_tasks_are_excluded_from_activity(self, _name, task_updates):
        Task.objects.filter(id=self.task.id).update(**task_updates)
        self._awaiting_input()

        page = self.author_client.get(self._activity_url()).json()

        self.assertEqual(page["results"], [])
        self.assertEqual(page["unread_count"], 0)

    def test_authored_message_shows_as_message_with_snippet(self):
        self._post_message(self.peer_client, "looking into this")
        row = self._row_for(self.peer_client, self.task)
        self.assertEqual(row["activity_kind"], "message")
        self.assertEqual(row["snippet"], "looking into this")
        self.assertEqual(row["latest_author"]["id"], self.peer.id)

    def test_agent_message_is_unread_for_the_task_creator(self):
        tasks_facade._create_agent_thread_message(self.task, "Hello!", event="agent_message")

        row = self._row_for(self.author_client, self.task)
        self.assertEqual(row["activity_kind"], "message")
        self.assertEqual(row["snippet"], "Hello!")
        self.assertIsNone(row["latest_author"])
        self.assertTrue(row["is_unread"])

    def test_mention_shows_as_mention_with_snippet(self):
        self._post_message(self.author_client, "cc @[Bob](peer@example.com) please look")
        row = self._row_for(self.peer_client, self.task)
        self.assertEqual(row["activity_kind"], "mention")
        self.assertEqual(row["snippet"], "cc @[Bob](peer@example.com) please look")
        self.assertEqual(row["latest_author"]["id"], self.author.id)

    def test_awaiting_input_projects_from_the_run_awaiting_notification(self):
        self._awaiting_input()
        row = self._row_for(self.author_client, self.task)
        self.assertEqual(row["activity_kind"], "awaiting_input")
        self.assertTrue(row["is_unread"])
        # Only the task's creator is being waited on.
        self.assertEqual(self._rows(self.peer_client), [])

    def test_completed_run_replaces_awaiting_input_activity(self):
        run = TaskRun.objects.create(team=self.team, task=self.task, status=TaskRun.Status.IN_PROGRESS)
        with patch("products.tasks.backend.push_dispatcher._enqueue"):
            notify_task_run_awaiting_input(run)
            notify_task_run_completed(run)

        row = self._row_for(self.author_client, self.task)
        self.assertEqual(row["activity_kind"], "completed")
        self.assertTrue(row["is_unread"])

    def test_completed_turn_is_unread_for_the_task_creator(self):
        run = TaskRun.objects.create(
            team=self.team,
            task=self.task,
            state={"mode": "interactive"},
            status=TaskRun.Status.IN_PROGRESS,
        )
        with patch("products.tasks.backend.push_dispatcher._enqueue"):
            notify_task_run_turn_completed(run)

        row = self._row_for(self.author_client, self.task)
        self.assertEqual(row["activity_kind"], "completed")
        self.assertTrue(row["is_unread"])

    def test_multiple_signals_collapse_to_one_row_with_the_newest_winning(self):
        self._post_message(self.author_client, "cc @[Bob](peer@example.com)")
        self._post_message(self.peer_client, "on it")
        row = self._row_for(self.peer_client, self.task)
        self.assertEqual(row["activity_kind"], "message")
        self.assertEqual(row["snippet"], "on it")

    def test_out_of_order_projection_does_not_move_the_row_backwards(self):
        self._awaiting_input()
        latest = self._row_for(self.author_client, self.task)["activity_at"]
        # A retried write replaying an older event must not overwrite newer activity.
        TaskActivity.record(
            team_id=self.team.id,
            user_id=self.author.id,
            task_id=self.task.id,
            kind=TaskActivity.Kind.CREATED,
            activity_at=django_timezone.now() - timedelta(hours=1),
        )
        row = self._row_for(self.author_client, self.task)
        self.assertEqual(row["activity_kind"], "awaiting_input")
        self.assertEqual(row["activity_at"], latest)

    @parameterized.expand(
        [
            ("own_task_creation", None),
            ("own_reply", "just thinking out loud"),
        ]
    )
    def test_activity_the_user_caused_themselves_is_never_unread(self, _name, own_message):
        if own_message is not None:
            self._post_message(self.author_client, own_message)
        page = self.author_client.get(self._activity_url()).json()
        self.assertEqual(page["unread_count"], 0)
        self.assertFalse(page["results"][0]["is_unread"])

    @parameterized.expand(
        [
            ("mention", lambda self: self._post_message(self.author_client, "@[Bob](peer@example.com) ping")),
            ("awaiting_input", lambda self: self._awaiting_input()),
        ]
    )
    def test_activity_someone_else_caused_is_unread(self, name, trigger):
        trigger(self)
        client = self.peer_client if name == "mention" else self.author_client
        page = client.get(self._activity_url()).json()
        self.assertEqual(page["unread_count"], 1)
        self.assertTrue(self._row_for(client, self.task)["is_unread"])

    def test_mark_read_clears_only_the_named_tasks(self):
        second = Task.objects.create(
            team=self.team,
            created_by=self.author,
            channel=self.channel,
            title="Second",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        self._awaiting_input()
        self._awaiting_input(second)
        self.assertEqual(self.author_client.get(self._activity_url()).json()["unread_count"], 2)

        row = self._row_for(self.author_client, self.task)
        body = self._mark_read(
            self.author_client,
            [{"task_id": str(self.task.id), "seen_before": row["activity_at"]}],
        )
        self.assertEqual(body, {"marked_read": 1, "unread_count": 1})
        self.assertFalse(self._row_for(self.author_client, self.task)["is_unread"])
        self.assertTrue(self._row_for(self.author_client, second)["is_unread"])

    def test_reading_the_thread_does_not_mutate_activity(self):
        self._awaiting_input()
        self.assertTrue(self._row_for(self.author_client, self.task)["is_unread"])
        self.assertEqual(self.author_client.get(self._thread_url()).status_code, status.HTTP_200_OK)
        self.assertTrue(self._row_for(self.author_client, self.task)["is_unread"])

    def test_mark_read_does_not_clear_newer_activity(self):
        self._awaiting_input()
        listed = self._row_for(self.author_client, self.task)
        TaskActivity.record(
            team_id=self.team.id,
            user_id=self.author.id,
            task_id=self.task.id,
            kind=TaskActivity.Kind.MENTION,
            activity_at=django_timezone.now() + timedelta(seconds=1),
        )

        body = self._mark_read(
            self.author_client,
            [{"task_id": str(self.task.id), "seen_before": listed["activity_at"]}],
        )

        self.assertEqual(body["marked_read"], 0)
        self.assertTrue(self._row_for(self.author_client, self.task)["is_unread"])

    def test_replaying_the_same_activity_preserves_read_state(self):
        self._awaiting_input()
        listed = self._row_for(self.author_client, self.task)
        self._mark_read(
            self.author_client,
            [{"task_id": str(self.task.id), "seen_before": listed["activity_at"]}],
        )

        TaskActivity.record(
            team_id=self.team.id,
            user_id=self.author.id,
            task_id=self.task.id,
            kind=TaskActivity.Kind.AWAITING_INPUT,
            activity_at=datetime.fromisoformat(listed["activity_at"]),
        )

        self.assertFalse(self._row_for(self.author_client, self.task)["is_unread"])

    def test_unread_count_covers_the_whole_feed_not_just_the_page(self):
        for index in range(2):
            task = Task.objects.create(
                team=self.team,
                created_by=self.author,
                channel=self.channel,
                title=f"Extra {index}",
                description="d",
                origin_product=Task.OriginProduct.USER_CREATED,
            )
            self._awaiting_input(task)
        self._awaiting_input()
        page = self.author_client.get(self._activity_url(), {"limit": 1}).json()
        self.assertEqual(len(page["results"]), 1)
        self.assertEqual(page["unread_count"], 3)

    def test_newest_activity_first_and_limit_applies(self):
        second = Task.objects.create(
            team=self.team,
            created_by=self.author,
            channel=self.channel,
            title="Second",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        # A fresh message makes `second` the most recently active task.
        self._post_message(self.author_client, "kickoff", task=second)
        rows = self._rows(self.author_client)
        self.assertEqual([row["task_id"] for row in rows], [str(second.id), str(self.task.id)])
        first_page = self.author_client.get(self._activity_url(), {"limit": 1}).json()
        self.assertEqual([row["task_id"] for row in first_page["results"]], [str(second.id)])
        second_page = self.author_client.get(
            self._activity_url(),
            {
                "limit": 1,
                "before": first_page["next_before"],
                "before_id": first_page["next_before_id"],
            },
        ).json()
        self.assertEqual([row["task_id"] for row in second_page["results"]], [str(self.task.id)])
        self.assertIsNone(second_page["next_before"])
        self.assertIsNone(second_page["next_before_id"])

    def test_mark_read_rejects_an_empty_task_list(self):
        response = self.author_client.post(self._activity_url() + "mark_read/", {"activities": []}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)

    def test_activity_projection_failure_does_not_fail_message_creation(self):
        with patch.object(TaskActivity, "record", side_effect=RuntimeError("projection unavailable")):
            response = self.author_client.post(self._thread_url(), {"content": "still persisted"})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        self.assertEqual(
            TaskThreadMessage.objects.for_team(self.team.id).filter(task=self.task, content="still persisted").count(),
            1,
        )


class ChannelFeedMessageAPITestCase(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Feed Org")
        self.team = Team.objects.create(organization=self.organization, name="Feed Team")
        self.user = User.objects.create_user(email="owner@example.com", first_name="Ann", password="password")
        self.other_user = User.objects.create_user(email="peer@example.com", first_name="Bob", password="password")
        for user in (self.user, self.other_user):
            self.organization.members.add(user)
            OrganizationMembership.objects.filter(user=user, organization=self.organization).update(
                level=OrganizationMembership.Level.ADMIN
            )

        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.other_client = APIClient()
        self.other_client.force_authenticate(self.other_user)

    def _channels_url(self) -> str:
        return f"/api/projects/{self.team.id}/task_channels/"

    def _feed_url(self, channel_id) -> str:
        return f"/api/projects/{self.team.id}/task_channels/{channel_id}/feed/"

    def _public_channel(self) -> str:
        return self.client.post(self._channels_url(), {"name": "mobile"}).json()["id"]

    def test_post_and_list_feed_message(self):
        channel_id = self._public_channel()
        response = self.client.post(
            self._feed_url(channel_id),
            {"event": "context_created", "payload": {"context_name": "mobile"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        body = response.json()
        self.assertEqual(body["event"], "context_created")
        # Client posts are marked human-authored; system/agent kinds are reserved
        # for server-side writers so a member can't forge trusted rows.
        self.assertEqual(body["author_kind"], "human")
        self.assertEqual(body["author"]["id"], self.user.id)
        self.assertEqual(body["payload"], {"context_name": "mobile"})

        listing = self.client.get(self._feed_url(channel_id)).json()
        # Creating the channel auto-emits a channel_created row, so the feed holds
        # both that and the posted context_created.
        self.assertEqual([m["event"] for m in listing], ["channel_created", "context_created"])
        self.assertIn(body["id"], [m["id"] for m in listing])

    def test_feed_message_is_visible_to_the_team(self):
        channel_id = self._public_channel()
        self.client.post(
            self._feed_url(channel_id),
            {"event": "context_md_building", "payload": {"context_name": "mobile"}},
            format="json",
        )
        peer_listing = self.other_client.get(self._feed_url(channel_id)).json()
        events = [m["event"] for m in peer_listing]
        # The peer sees the team-visible feed: the auto channel_created + the post.
        self.assertEqual(events, ["channel_created", "context_md_building"])

    def test_invalid_event_is_rejected(self):
        channel_id = self._public_channel()
        response = self.client.post(self._feed_url(channel_id), {"event": "nope"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_channel_is_404(self):
        response = self.client.get(self._feed_url("00000000-0000-0000-0000-000000000000"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_personal_channel_feed_is_owner_only(self):
        mine = self.client.post(f"{self._channels_url()}provision_defaults/").json()
        personal_id = next(c["id"] for c in mine["channels"] if c["channel_type"] == "personal")
        self.client.post(
            self._feed_url(personal_id),
            {"event": "context_created", "payload": {"context_name": "me"}},
            format="json",
        )
        # A peer cannot read someone else's personal channel feed.
        peer = self.other_client.get(self._feed_url(personal_id))
        self.assertEqual(peer.status_code, status.HTTP_404_NOT_FOUND)

    def test_channel_creation_emits_channel_created(self):
        channel_id = self._public_channel()
        feed = self.client.get(self._feed_url(channel_id)).json()
        created = [m for m in feed if m["event"] == "channel_created"]
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["author_kind"], "system")
        self.assertEqual(created[0]["author"]["id"], self.user.id)
        self.assertEqual(created[0]["payload"], {"channel_name": "mobile"})

    def test_resolving_existing_channel_does_not_reemit(self):
        channel_id = self._public_channel()
        # Resolve the same name again — must not add a second channel_created.
        self.client.post(self._channels_url(), {"name": "mobile"})
        feed = self.client.get(self._feed_url(channel_id)).json()
        self.assertEqual(len([m for m in feed if m["event"] == "channel_created"]), 1)

    def test_client_created_at_orders_a_burst(self):
        channel_id = self._public_channel()
        now = django_timezone.now()
        # Post out of order with explicit timestamps; the feed must sort by created_at.
        second = (now + timedelta(seconds=2)).isoformat()
        first = (now + timedelta(seconds=1)).isoformat()
        self.client.post(
            self._feed_url(channel_id),
            {"event": "context_md_building", "payload": {}, "created_at": second},
            format="json",
        )
        self.client.post(
            self._feed_url(channel_id),
            {"event": "context_created", "payload": {}, "created_at": first},
            format="json",
        )
        events = [m["event"] for m in self.client.get(self._feed_url(channel_id)).json()]
        self.assertEqual(events, ["channel_created", "context_created", "context_md_building"])

    def test_created_at_outside_window_is_rejected(self):
        channel_id = self._public_channel()
        for delta in (timedelta(hours=-1), timedelta(hours=1)):
            stamp = (django_timezone.now() + delta).isoformat()
            response = self.client.post(
                self._feed_url(channel_id),
                {"event": "context_created", "created_at": stamp},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, stamp)

    def test_oversized_payload_is_rejected(self):
        channel_id = self._public_channel()
        response = self.client.post(
            self._feed_url(channel_id),
            {"event": "context_created", "payload": {"context_name": "x" * 9000}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_post_to_full_feed_is_rejected(self):
        channel_id = self._public_channel()
        # channel_created already occupies one slot; a cap of 2 leaves room for one post.
        with patch("products.tasks.backend.facade.api.CHANNEL_FEED_MAX_MESSAGES", 2):
            ok = self.client.post(self._feed_url(channel_id), {"event": "context_created"}, format="json")
            self.assertEqual(ok.status_code, status.HTTP_201_CREATED)
            full = self.client.post(self._feed_url(channel_id), {"event": "context_md_building"}, format="json")
            self.assertEqual(full.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_returns_newest_rows_ascending_when_over_cap(self):
        channel_id = self._public_channel()
        now = django_timezone.now()
        for i, event in enumerate(["context_created", "context_md_building"]):
            ChannelFeedMessage(
                team=self.team, channel_id=channel_id, event=event, created_at=now + timedelta(seconds=i + 1)
            ).save()
        with patch("products.tasks.backend.facade.api.CHANNEL_FEED_MAX_MESSAGES", 2):
            events = [m["event"] for m in self.client.get(self._feed_url(channel_id)).json()]
        # Three rows, cap 2: the oldest (channel_created) drops, newest two stay ascending.
        self.assertEqual(events, ["context_created", "context_md_building"])

    def test_feed_is_team_scoped(self):
        channel_id = self._public_channel()
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        # Same org, wrong team in the URL — the channel must not resolve.
        response = self.client.get(f"/api/projects/{other_team.id}/task_channels/{channel_id}/feed/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
