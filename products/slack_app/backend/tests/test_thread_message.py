from django.test import TestCase

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.models import SlackThreadMessage, SlackThreadTaskMapping
from products.tasks.backend.models import Task, TaskRun


class TestSlackThreadMessage(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org")
        self.team = Team.objects.create(organization=self.org, name="Team")
        self.user = User.objects.create(email="creator@test.com")
        self.integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T1", config={})
        self.task = Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.SLACK,
            created_by=self.user,
            repository="org/repo",
        )
        self.task_run = TaskRun.objects.create(task=self.task, team=self.team, state={})
        self.mapping = SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=self.integration,
            slack_workspace_id="T1",
            channel="C1",
            thread_ts="1000.0",
            task=self.task,
            task_run=self.task_run,
            mentioning_slack_user_id="U_CREATOR",
        )

    def test_record_is_idempotent_and_keeps_first_author(self):
        # Temporal retries the forward activity, so a second record for the same ts
        # must not raise or reattribute the message.
        SlackThreadMessage.record(self.mapping, "U_ALICE", "1001.1")
        SlackThreadMessage.record(self.mapping, "U_BOB", "1001.1")

        assert SlackThreadMessage.objects.filter(mapping=self.mapping).count() == 1
        assert SlackThreadMessage.author_of(self.mapping, "1001.1") == "U_ALICE"

    def test_latest_participant_is_the_most_recent_message_author(self):
        SlackThreadMessage.record(self.mapping, "U_ALICE", "1001.1")
        SlackThreadMessage.record(self.mapping, "U_BOB", "1003.3")
        SlackThreadMessage.record(self.mapping, "U_CAROL", "1002.2")

        assert SlackThreadMessage.latest_participant(self.mapping) == "U_BOB"
