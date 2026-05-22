from datetime import timedelta

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.user_push_token import UserPushToken
from posthog.push_notifications import send_push_to_user

from products.tasks.backend.models import TASK_PRESENCE_TTL_SECONDS, Task, TaskPresence, TaskRun
from products.tasks.backend.push_dispatcher import notify_task_run_completed


def _flag_check_factory():
    """Return a side_effect that turns on both the tasks-access flag and the push flag."""

    def check_flag(flag_name, *_args, **_kwargs):
        return flag_name in {"tasks", "posthog-code-mobile-push"}

    return check_flag


def _make_presence(
    *, team: Team, task: Task, user: User, push_token: UserPushToken, expires_in: timedelta
) -> TaskPresence:
    """Create a presence row directly without needing a team_scope context.

    ``Model(...).save()`` sidesteps ``TeamScopedManager.get_queryset`` so test
    setUp doesn't have to wrap every helper in ``team_scope``. Production
    writers (the DRF beacon endpoint) come in through ``objects`` and are
    auto-scoped via ``TeamAndOrgViewSetMixin``.
    """
    instance = TaskPresence(
        team=team,
        task=task,
        user=user,
        push_token=push_token,
        expires_at=timezone.now() + expires_in,
    )
    instance.save()
    return instance


class PresenceAPITestCase(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user(email="presence@example.com", first_name="P", password="password")
        self.organization.members.add(self.user)
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="A Task",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        self.push_token = UserPushToken.objects.create(
            user=self.user,
            token="ExponentPushToken[device-A]",
            platform=UserPushToken.Platform.IOS,
        )

        self.client = APIClient()
        self.client.force_authenticate(self.user)

        self.flag_patcher = patch("posthoganalytics.feature_enabled", side_effect=_flag_check_factory())
        self.flag_patcher.start()
        self.addCleanup(self.flag_patcher.stop)

    def _presence_url(self) -> str:
        return f"/api/projects/{self.team.id}/tasks/{self.task.id}/presence/"

    def _all_presence(self):
        # Assertions run outside the DRF team-scope context, so go through
        # the cross-team queryset explicitly.
        return TaskPresence.objects.unscoped()

    def test_beacon_creates_presence_row(self) -> None:
        response = self.client.post(self._presence_url(), {"device_id": str(self.push_token.id)}, format="json")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self._all_presence().filter(task=self.task, push_token=self.push_token).count(), 1)
        presence = self._all_presence().get(task=self.task, push_token=self.push_token)
        self.assertEqual(presence.user_id, self.user.id)
        self.assertEqual(presence.team_id, self.team.id)
        # expires_at lands ~TTL seconds in the future. A loose lower bound
        # avoids flake if the clock advances between the view and the assert.
        delta = (presence.expires_at - timezone.now()).total_seconds()
        self.assertGreater(delta, TASK_PRESENCE_TTL_SECONDS - 5)
        self.assertLessEqual(delta, TASK_PRESENCE_TTL_SECONDS + 1)

    def test_second_beacon_refreshes_without_duplicating(self) -> None:
        self.client.post(self._presence_url(), {"device_id": str(self.push_token.id)}, format="json")
        first = self._all_presence().get(task=self.task, push_token=self.push_token)

        # Drag expires_at into the past so we can prove the upsert refreshed it.
        self._all_presence().filter(pk=first.pk).update(expires_at=timezone.now() - timedelta(minutes=5))

        response = self.client.post(self._presence_url(), {"device_id": str(self.push_token.id)}, format="json")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self._all_presence().filter(task=self.task, push_token=self.push_token).count(), 1)
        refreshed = self._all_presence().get(task=self.task, push_token=self.push_token)
        self.assertEqual(refreshed.pk, first.pk)
        self.assertGreater(refreshed.expires_at, timezone.now())

    def test_beacon_leave_removes_row(self) -> None:
        _make_presence(
            team=self.team,
            task=self.task,
            user=self.user,
            push_token=self.push_token,
            expires_in=timedelta(seconds=60),
        )
        response = self.client.delete(self._presence_url(), {"device_id": str(self.push_token.id)}, format="json")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(self._all_presence().filter(task=self.task, push_token=self.push_token).exists())

    def test_beacon_leave_on_missing_row_is_idempotent(self) -> None:
        response = self.client.delete(self._presence_url(), {"device_id": str(self.push_token.id)}, format="json")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    @parameterized.expand(
        [
            ("unknown_device_id", "unknown"),
            ("device_id_belonging_to_another_user", "other_user"),
        ]
    )
    def test_beacon_rejects_invalid_device_id(self, _name, kind) -> None:
        if kind == "unknown":
            device_id = "00000000-0000-0000-0000-000000000000"
        else:
            other = User.objects.create_user(email="other@example.com", first_name="O", password="x")
            self.organization.members.add(other)
            other_token = UserPushToken.objects.create(
                user=other,
                token="ExponentPushToken[other-device]",
                platform=UserPushToken.Platform.IOS,
            )
            device_id = str(other_token.id)

        response = self.client.post(self._presence_url(), {"device_id": device_id}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(self._all_presence().exists())

    def test_beacon_on_inaccessible_task_returns_404(self) -> None:
        other_user = User.objects.create_user(email="taskowner@example.com", first_name="To", password="x")
        self.organization.members.add(other_user)
        their_task = Task.objects.create(
            team=self.team,
            created_by=other_user,
            title="Not Yours",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        url = f"/api/projects/{self.team.id}/tasks/{their_task.id}/presence/"
        response = self.client.post(url, {"device_id": str(self.push_token.id)}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class PresenceFanoutSuppressionTestCase(TransactionTestCase):
    """``send_user_push`` is dispatched via ``transaction.on_commit``; we need a
    TransactionTestCase so the callback actually fires.

    The contract under test: any non-expired presence row for this user/task
    suppresses fanout to ALL of that user's push tokens — including the
    watching device itself, which is already rendering the task UI live.
    """

    def setUp(self) -> None:
        cache.clear()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user(email="fan@example.com", first_name="F", password="password")
        OrganizationMembership.objects.create(user=self.user, organization=self.organization)
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Watching Task",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        self.task_run = TaskRun.objects.create(task=self.task, team=self.team)
        self.device_a = UserPushToken.objects.create(
            user=self.user, token="ExponentPushToken[A]", platform=UserPushToken.Platform.IOS
        )
        self.device_b = UserPushToken.objects.create(
            user=self.user, token="ExponentPushToken[B]", platform=UserPushToken.Platform.ANDROID
        )

    def _present(self, device: UserPushToken, *, on_task: Task | None = None, expires_in: timedelta) -> None:
        _make_presence(
            team=self.team,
            task=on_task or self.task,
            user=self.user,
            push_token=device,
            expires_in=expires_in,
        )

    # Each case sets up a different presence layout and asserts which devices
    # the dispatcher told the celery task to suppress. The "all devices" cases
    # cover the documented contract: any active presence -> blanket suppression.
    @parameterized.expand(
        [
            # (label, scenario_id, expected_suppressed_kind)
            #   "all"  -> both device_a and device_b
            #   "none" -> no devices
            ("one_device_watching_suppresses_all", "one_active", "all"),
            ("both_devices_watching_suppresses_all", "both_active", "all"),
            ("only_expired_presence_suppresses_none", "expired_only", "none"),
            ("presence_on_other_task_suppresses_none", "other_task_only", "none"),
        ]
    )
    @patch("products.tasks.backend.push_dispatcher.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.tasks.backend.push_dispatcher.send_user_push.delay")
    def test_fanout_suppression_matrix(self, _name, scenario, expected, mock_delay, _flag) -> None:
        if scenario == "one_active":
            self._present(self.device_a, expires_in=timedelta(seconds=30))
        elif scenario == "both_active":
            self._present(self.device_a, expires_in=timedelta(seconds=30))
            self._present(self.device_b, expires_in=timedelta(seconds=30))
        elif scenario == "expired_only":
            self._present(self.device_a, expires_in=-timedelta(seconds=1))
        elif scenario == "other_task_only":
            other_task = Task.objects.create(
                team=self.team,
                created_by=self.user,
                title="Other Task",
                description="d",
                origin_product=Task.OriginProduct.USER_CREATED,
            )
            self._present(self.device_a, on_task=other_task, expires_in=timedelta(seconds=30))

        notify_task_run_completed(self.task_run)

        mock_delay.assert_called_once()
        suppressed = mock_delay.call_args.args[4]

        if expected == "all":
            self.assertEqual(set(suppressed), {str(self.device_a.id), str(self.device_b.id)})
        else:
            self.assertEqual(suppressed, [])


class PresencePushHelperSuppressionTestCase(TestCase):
    """Direct test of ``send_push_to_user`` honouring the suppression set,
    so we cover the helper without exercising the dispatcher path."""

    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user(email="helper@example.com", first_name="H", password="password")
        self.device_a = UserPushToken.objects.create(
            user=self.user, token="ExponentPushToken[helper-A]", platform=UserPushToken.Platform.IOS
        )
        self.device_b = UserPushToken.objects.create(
            user=self.user, token="ExponentPushToken[helper-B]", platform=UserPushToken.Platform.ANDROID
        )

    @patch("posthog.push_notifications._send_batch")
    def test_excludes_suppressed_tokens_from_fanout(self, mock_send_batch) -> None:
        mock_send_batch.return_value = 1

        send_push_to_user(
            self.user,
            title="t",
            body="b",
            suppressed_push_token_ids=[str(self.device_a.id)],
        )

        mock_send_batch.assert_called_once()
        sent_tokens = mock_send_batch.call_args.args[1]
        self.assertEqual(sent_tokens, [self.device_b.token])

    @patch("posthog.push_notifications._send_batch")
    def test_no_call_when_every_token_is_suppressed(self, mock_send_batch) -> None:
        send_push_to_user(
            self.user,
            title="t",
            body="b",
            suppressed_push_token_ids=[str(self.device_a.id), str(self.device_b.id)],
        )

        mock_send_batch.assert_not_called()
