from typing import ClassVar

from unittest.mock import patch

from django.test import TestCase

from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.tasks.backend.logic.services.agent_command import send_user_message
from products.tasks.backend.logic.services.run_actor import get_task_actor_uuids, record_task_actor
from products.tasks.backend.models import Task

_SENDER_UUID = "018f3c2a-0000-7000-8000-000000000001"


class TestTaskActorRoster(TestCase):
    org: ClassVar[Organization]
    team: ClassVar[Team]
    alice: ClassVar[User]
    bob: ClassVar[User]
    task: ClassVar[Task]
    other_task: ClassVar[Task]

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="TestOrg")
        cls.team = Team.objects.create(organization=cls.org, name="TestTeam")
        cls.alice = User.objects.create(email="alice@test.com")
        cls.bob = User.objects.create(email="bob@test.com")
        cls.task = Task.objects.create(
            team=cls.team,
            title="Test task",
            description="desc",
            origin_product=Task.OriginProduct.SLACK,
            created_by=cls.alice,
        )
        cls.other_task = Task.objects.create(
            team=cls.team,
            title="Other task",
            description="desc",
            origin_product=Task.OriginProduct.SLACK,
            created_by=cls.alice,
        )

    def _record(self, task, user):
        record_task_actor(team_id=self.team.id, task_id=task.id, user_uuid=str(user.uuid) if user else None)

    def test_the_roster_names_each_person_once_however_often_they_speak(self):
        # Recorded once per message, so a chatty thread must not list them per turn.
        self._record(self.task, self.alice)
        self._record(self.task, self.alice)
        self._record(self.task, self.bob)

        assert sorted(get_task_actor_uuids(self.task.id, self.team.id)) == sorted(
            [str(self.alice.uuid), str(self.bob.uuid)]
        )

    def test_a_senderless_message_adds_nobody(self):
        # Peer and server-composed messages have no person behind them.
        self._record(self.task, None)

        assert get_task_actor_uuids(self.task.id, self.team.id) == []

    def test_the_roster_is_per_task(self):
        self._record(self.task, self.alice)

        assert get_task_actor_uuids(self.other_task.id, self.team.id) == []


class TestSenderOnTheWire(TestCase):
    @patch("products.tasks.backend.logic.services.agent_command.send_agent_command")
    def test_the_sender_uuid_rides_with_the_message(self, mock_send):
        # The agent server moves this onto the prompt's _meta, which is what both
        # harnesses render and the run stream carries.
        send_user_message(object(), "hello", message_id="m1", sender_user_uuid=_SENDER_UUID)

        assert mock_send.call_args.kwargs["params"]["senderUserUuid"] == _SENDER_UUID

    @patch("products.tasks.backend.logic.services.agent_command.send_agent_command")
    def test_a_message_with_no_sender_omits_the_field(self, mock_send):
        send_user_message(object(), "hello", message_id="m1")

        assert "senderUserUuid" not in mock_send.call_args.kwargs["params"]
