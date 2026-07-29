from typing import ClassVar

from django.test import TestCase

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.models.user import User

from products.tasks.backend.facade import api as facade
from products.tasks.backend.models import Channel, Task


class TestGetTaskLinkPreview(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Test Team")
        cls.user = User.objects.create(
            email="creator@test.com", distinct_id="creator", first_name="Ada", last_name="Lovelace"
        )

    def _make_channel(self, **kwargs) -> Channel:
        defaults = {"team": self.team, "name": "growth", "created_by": self.user}
        defaults.update(kwargs)
        channel = Channel(**defaults)
        channel.save()
        return channel

    def _make_task(self, channel: Channel | None, **kwargs) -> Task:
        defaults = {
            "team": self.team,
            "title": "Fix the login redirect",
            "description": "desc",
            "origin_product": Task.OriginProduct.USER_CREATED,
            "created_by": self.user,
            "channel": channel,
        }
        defaults.update(kwargs)
        return Task.objects.create(**defaults)

    def test_returns_title_channel_and_creator(self):
        channel = self._make_channel()
        task = self._make_task(channel)

        preview = facade.get_task_link_preview(channel.id, task.id)

        assert preview is not None
        self.assertEqual(preview.task_title, "Fix the login redirect")
        self.assertEqual(preview.channel_name, "growth")
        self.assertEqual(preview.creator_name, "Ada Lovelace")

    def test_creator_name_is_none_without_creator(self):
        channel = self._make_channel(created_by=None)
        task = self._make_task(channel, created_by=None)

        preview = facade.get_task_link_preview(channel.id, task.id)

        assert preview is not None
        self.assertIsNone(preview.creator_name)

    def test_task_in_a_different_channel_does_not_resolve(self):
        # The two ids must belong together — a valid task id under the wrong channel id
        # must not leak a preview.
        channel = self._make_channel()
        other_channel = self._make_channel(name="support")
        task = self._make_task(channel)

        self.assertIsNone(facade.get_task_link_preview(other_channel.id, task.id))

    @parameterized.expand(
        [
            ("malformed_channel_id", "not-a-uuid", None),
            ("malformed_task_id", None, "not-a-uuid"),
        ]
    )
    def test_malformed_ids_return_none(self, _name, channel_id, task_id):
        channel = self._make_channel()
        task = self._make_task(channel)

        self.assertIsNone(facade.get_task_link_preview(channel_id or channel.id, task_id or task.id))

    def test_soft_deleted_task_does_not_resolve(self):
        channel = self._make_channel()
        task = self._make_task(channel, deleted=True)

        self.assertIsNone(facade.get_task_link_preview(channel.id, task.id))

    def test_deleted_channel_does_not_resolve(self):
        channel = self._make_channel(deleted=True)
        task = self._make_task(channel)

        self.assertIsNone(facade.get_task_link_preview(channel.id, task.id))

    def test_internal_task_does_not_resolve(self):
        # `internal` tasks are system-generated and "not exposed to end users".
        channel = self._make_channel()
        task = self._make_task(channel, internal=True)

        self.assertIsNone(facade.get_task_link_preview(channel.id, task.id))

    def test_task_in_personal_channel_does_not_resolve(self):
        # A user's private `#me` feed is not a shareable artifact.
        channel = self._make_channel(name="me", channel_type=Channel.ChannelType.PERSONAL)
        task = self._make_task(channel)

        self.assertIsNone(facade.get_task_link_preview(channel.id, task.id))


class TestCodeChannelTaskLinkPage(TestCase):
    """Wiring guard: the public `/code/channel/.../tasks/...` route renders OG tags and
    escapes the (user-controlled) task title into the meta attribute."""

    organization: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Test Team")
        cls.user = User.objects.create(email="pager@test.com", distinct_id="pager", first_name="Grace")

    def _url(self, channel_id, task_id) -> str:
        return f"/code/channel/{channel_id}/tasks/{task_id}"

    def test_renders_og_title_for_existing_task(self):
        channel = Channel(team=self.team, name="growth", created_by=self.user)
        channel.save()
        task = Task.objects.create(
            team=self.team,
            title="Fix the login redirect",
            description="desc",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
            channel=channel,
        )

        response = self.client.get(self._url(channel.id, task.id))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('property="og:title" content="Fix the login redirect"', content)
        self.assertIn('property="og:description" content="Task in #growth, created by Grace"', content)
        self.assertIn('name="robots" content="noindex"', content)

    def test_escapes_malicious_title(self):
        channel = Channel(team=self.team, name="growth", created_by=self.user)
        channel.save()
        task = Task.objects.create(
            team=self.team,
            title='pwn"><script>alert(1)</script>',
            description="desc",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
            channel=channel,
        )

        content = self.client.get(self._url(channel.id, task.id)).content.decode()

        self.assertNotIn("<script>alert(1)</script>", content)
        self.assertIn("&lt;script&gt;", content)

    def test_missing_task_renders_app_without_og_tags(self):
        channel = Channel(team=self.team, name="growth", created_by=self.user)
        channel.save()
        # A well-formed but non-existent task id: the SPA still loads, but no OG tags leak.
        response = self.client.get(self._url(channel.id, "0e5947d9-11d5-41a7-b9b0-25d102bbf4f8"))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('property="og:title"', response.content.decode())
