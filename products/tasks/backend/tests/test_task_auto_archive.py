from datetime import timedelta

from django.test import TestCase
from django.utils import timezone as django_timezone

from posthog.models import Organization, Team, User, UserPushToken

from products.tasks.backend.models import Channel, Task, TaskPin, TaskPresence, TaskRun
from products.tasks.backend.task_auto_archive import sweep_inactive_tasks


class TestTaskAutoArchive(TestCase):
    def setUp(self) -> None:
        organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=organization, name="Test Team")
        self.user = User.objects.create_user(email="author@example.com", first_name="Author", password="password")
        self.now = django_timezone.now()

    def _channel(self, *, name: str, inactivity_days: int | None) -> Channel:
        return Channel.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            created_by=self.user,
            name=name,
            auto_archive_after_days=inactivity_days,
        )

    def _task(self, *, channel: Channel, age_days: int) -> Task:
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            channel=channel,
            title="Test task",
            description="Test description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        Task.objects.filter(id=task.id).update(last_activity_at=self.now - timedelta(days=age_days))
        task.refresh_from_db()
        return task

    def test_sweep_uses_each_space_threshold(self) -> None:
        enabled = self._channel(name="enabled", inactivity_days=3)
        disabled = self._channel(name="disabled", inactivity_days=None)
        stale = self._task(channel=enabled, age_days=4)
        recent = self._task(channel=enabled, age_days=2)
        disabled_stale = self._task(channel=disabled, age_days=30)

        self.assertEqual(sweep_inactive_tasks(at=self.now), 1)

        stale.refresh_from_db()
        recent.refresh_from_db()
        disabled_stale.refresh_from_db()
        self.assertTrue(stale.archived)
        self.assertEqual(stale.archived_at, self.now)
        self.assertFalse(recent.archived)
        self.assertFalse(disabled_stale.archived)

    def test_sweep_keeps_active_and_pinned_tasks(self) -> None:
        channel = self._channel(name="protected", inactivity_days=1)
        active = self._task(channel=channel, age_days=3)
        pinned = self._task(channel=channel, age_days=3)
        TaskRun.objects.create(task=active, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        Task.objects.filter(id=active.id).update(last_activity_at=self.now - timedelta(days=3))
        TaskPin.objects.create(user=self.user, task=pinned)

        self.assertEqual(sweep_inactive_tasks(at=self.now), 0)

        active.refresh_from_db()
        pinned.refresh_from_db()
        self.assertFalse(active.archived)
        self.assertFalse(pinned.archived)

    def test_sweep_keeps_task_with_active_presence(self) -> None:
        channel = self._channel(name="protected", inactivity_days=1)
        viewed = self._task(channel=channel, age_days=3)
        no_longer_viewed = self._task(channel=channel, age_days=3)
        push_token = UserPushToken.objects.create(
            user=self.user,
            token="ExponentPushToken[auto-archive-test]",
            platform=UserPushToken.Platform.IOS,
        )
        TaskPresence.objects.unscoped().create(
            team=self.team,
            task=viewed,
            user=self.user,
            push_token=push_token,
            expires_at=self.now + timedelta(minutes=1),
        )
        TaskPresence.objects.unscoped().create(
            team=self.team,
            task=no_longer_viewed,
            user=self.user,
            push_token=push_token,
            expires_at=self.now - timedelta(minutes=1),
        )

        self.assertEqual(sweep_inactive_tasks(at=self.now), 1)

        viewed.refresh_from_db()
        no_longer_viewed.refresh_from_db()
        self.assertFalse(viewed.archived)
        self.assertTrue(no_longer_viewed.archived)

    def test_sweep_scopes_protection_checks_to_the_task_team(self) -> None:
        other_team = Team.objects.create(organization=self.team.organization, name="Other Team")
        channel = self._channel(name="scoped", inactivity_days=1)
        stale = self._task(channel=channel, age_days=3)
        push_token = UserPushToken.objects.create(
            user=self.user,
            token="ExponentPushToken[other-team-auto-archive-test]",
            platform=UserPushToken.Platform.IOS,
        )
        TaskRun.objects.create(task=stale, team=other_team, status=TaskRun.Status.IN_PROGRESS)
        TaskPresence.objects.for_team(other_team.id).create(
            team=other_team,
            task=stale,
            user=self.user,
            push_token=push_token,
            expires_at=self.now + timedelta(minutes=1),
        )

        self.assertEqual(sweep_inactive_tasks(at=self.now), 1)

        stale.refresh_from_db()
        self.assertTrue(stale.archived)
