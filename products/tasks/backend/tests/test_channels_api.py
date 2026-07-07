from unittest.mock import patch

from django.test import TestCase

from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import Organization, OrganizationMembership, Team, User

from products.tasks.backend.models import Channel, Task, TaskRun, TaskThreadMessage


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

    def _channels_url(self) -> str:
        return f"/api/projects/{self.team.id}/task_channels/"

    def _tasks_url(self) -> str:
        return f"/api/projects/{self.team.id}/tasks/"

    def test_list_provisions_personal_channel(self):
        response = self.client.get(self._channels_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        personal = [c for c in response.json() if c["channel_type"] == "personal"]
        self.assertEqual(len(personal), 1)
        self.assertEqual(personal[0]["name"], "me")
        self.assertEqual(personal[0]["created_by"]["id"], self.user.id)

        # Listing again reuses the same personal channel
        again = self.client.get(self._channels_url()).json()
        self.assertEqual(
            [c["id"] for c in again if c["channel_type"] == "personal"],
            [personal[0]["id"]],
        )

    def test_personal_channels_are_per_user(self):
        mine = self.client.get(self._channels_url()).json()
        other_client = APIClient()
        other_client.force_authenticate(self.other_user)
        theirs = other_client.get(self._channels_url()).json()

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
        self.client.get(self._channels_url())
        # Direct ORM reads in tests bypass the DRF-set team context, so opt out
        # of the fail-closed scoping explicitly (see test_presence.py).
        personal = Channel.objects.unscoped().get(team=self.team, channel_type=Channel.ChannelType.PERSONAL)
        rename = self.client.patch(f"{self._channels_url()}{personal.id}/", {"name": "not-me"})
        self.assertEqual(rename.status_code, status.HTTP_403_FORBIDDEN)
        delete = self.client.delete(f"{self._channels_url()}{personal.id}/")
        self.assertEqual(delete.status_code, status.HTTP_403_FORBIDDEN)

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

    def test_task_in_personal_channel_stays_private(self):
        self.client.get(self._channels_url())
        personal = Channel.objects.unscoped().get(team=self.team, channel_type=Channel.ChannelType.PERSONAL)
        created = self.client.post(
            self._tasks_url(),
            {"title": "Secret", "description": "mine", "channel": str(personal.id)},
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.content)

        other_client = APIClient()
        other_client.force_authenticate(self.other_user)
        listed = other_client.get(self._tasks_url(), {"channel": str(personal.id)}).json()["results"]
        self.assertEqual(listed, [])

    def test_cannot_file_task_into_someone_elses_personal_channel(self):
        self.client.get(self._channels_url())
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

    def test_unparseable_since_is_a_400(self):
        response = self.peer_client.get(self._mentions_url(), {"since": "not-a-date"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_mention_on_invisible_task_is_hidden(self):
        private_task = Task.objects.create(
            team=self.team,
            created_by=self.author,
            title="Private",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        self._post_message(self.author_client, "fyi @[Bob](peer@example.com)", task=private_task)
        self.assertEqual(self.peer_client.get(self._mentions_url()).json(), [])

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
