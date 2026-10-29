from django.test import TestCase

from posthog.models import Organization, Team, User
from posthog.models.integration import Integration
from posthog.models.user_integration import UserIntegration

from products.slack_app.backend.models import SlackThreadTaskMapping
from products.slack_app.backend.services.task_notifications import task_slack_notifications_muted
from products.tasks.backend.models import Task, TaskRun


class TestTaskNotificationTakeover(TestCase):
    def setUp(self) -> None:
        organization = Organization.objects.create(name="Test organization")
        self.team = Team.objects.create(organization=organization)
        self.user = User.objects.create_user(email="mobile@example.com", password="password", first_name="Mobile")
        self.other = User.objects.create_user(email="other@example.com", password="password", first_name="Other")
        self.integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T123")
        self.task = Task.objects.create(
            team=self.team, created_by=self.user, state={"mobile_push_user_ids": [self.user.id]}
        )
        self.task_run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            state={"slack_actor_user_id": self.user.id, "slack_actor_slack_user_id": "U123"},
        )
        self.mapping = SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id="T123",
            channel="C123",
            thread_ts="123.456",
            task=self.task,
            task_run=self.task_run,
            mentioning_slack_user_id="U123",
            conversation_type=SlackThreadTaskMapping.ConversationType.PUBLIC_CHANNEL,
        )

    def muted(self, slack_user_id: str = "U123", *, private_only: bool = False) -> bool:
        return task_slack_notifications_muted(
            integration_id=self.integration.id,
            channel="C123",
            thread_ts="123.456",
            slack_user_id=slack_user_id,
            private_only=private_only,
        )

    def test_only_the_picked_up_users_task_notifications_are_muted(self) -> None:
        UserIntegration.objects.create(
            user=self.other, kind="slack", integration_id="UOTHER", config={"slack_team_id": "T123"}
        )
        assert self.muted()
        assert not self.muted("UOTHER")
        self.task.state = {}
        self.task.save(update_fields=["state"])
        assert not self.muted()

    def test_proactive_messages_are_muted_only_in_the_users_private_dm(self) -> None:
        assert not self.muted(private_only=True)
        self.mapping.conversation_type = SlackThreadTaskMapping.ConversationType.IM
        self.mapping.save(update_fields=["conversation_type"])
        assert self.muted(private_only=True)

    def test_report_threads_without_task_mapping_are_unchanged(self) -> None:
        self.mapping.delete()
        assert not self.muted()

    def test_linked_slack_identity_is_scoped_to_its_workspace(self) -> None:
        self.task_run.state = {}
        self.task_run.save(update_fields=["state"])
        UserIntegration.objects.create(
            user=self.user, kind="slack", integration_id="UPICKUP", config={"slack_team_id": "TOTHER"}
        )
        assert not self.muted("UPICKUP")
        UserIntegration.objects.filter(user=self.user).update(config={"slack_team_id": "T123"})
        assert self.muted("UPICKUP")
