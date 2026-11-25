from types import SimpleNamespace
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from rest_framework.exceptions import PermissionDenied, ValidationError

from products.meep.backend.delegation import reconcile_notification, reconcile_wait, spawn_child, wait_for_children
from products.meep.backend.models import BoardRun, ChatTurn, ChildWait, Topic
from products.meep.backend.replication import apply_command


class TestDelegation(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.topic_id = uuid4()
        apply_command(
            self.team.pk,
            self.user,
            uuid4(),
            self.topic_id,
            {"kind": "CreateTopicWithoutSort", "name": "Research", "mission": "Investigate activation"},
        )
        self.topic = Topic.objects.for_team(self.team.pk).get(pk=self.topic_id)
        self.topic.conversation_id = uuid4()
        self.topic.save(update_fields=["conversation_id"])
        self.turn = ChatTurn.objects.create(topic=self.topic, message_id=uuid4(), text="Investigate", run_id=uuid4())

    def test_spawn_is_idempotent_and_links_the_originating_thread(self) -> None:
        self.topic.chat_model = "example-model"
        self.topic.save(update_fields=["chat_model"])
        request = uuid4()
        task_id, run_id = uuid4(), uuid4()
        created = SimpleNamespace(task_id=task_id, latest_run=SimpleNamespace(id=run_id))
        with (
            patch("products.meep.backend.board.check_access"),
            patch("products.meep.backend.board.environment", return_value=uuid4()),
            patch("products.meep.backend.board.api.create_and_run_task", return_value=created) as create,
        ):
            first = spawn_child(
                self.team,
                self.user,
                self.topic.conversation_id,
                self.turn.run_id,
                self.topic_id,
                request,
                "Review",
                "Investigate",
            )
            assert (
                spawn_child(
                    self.team,
                    self.user,
                    self.topic.conversation_id,
                    self.turn.run_id,
                    self.topic_id,
                    request,
                    "Review",
                    "Investigate",
                )
                == first
            )
        assert create.call_count == 1
        assert create.call_args.kwargs["extra_run_state"]["agent_parent_run_id"] == str(self.turn.run_id)
        assert create.call_args.kwargs["options"].output_schema["required"] == ["reply", "needs_input"]
        assert create.call_args.kwargs["options"].model == "example-model"
        job = BoardRun.objects.get(run_id=run_id)
        assert job.parent_turn == self.turn
        self.topic.refresh_from_db()
        assert self.topic.state["tasks"][0]["from_thread"] == str(self.turn.message_id)
        assert self.topic.state["tasks"][0]["model"] == "example-model"

    def test_child_task_cannot_delegate(self) -> None:
        with self.assertRaises(PermissionDenied):
            spawn_child(
                self.team, self.user, uuid4(), self.turn.run_id, self.topic_id, uuid4(), "Review", "Investigate"
            )

    def test_delegation_limits_running_children(self) -> None:
        for _ in range(3):
            BoardRun.objects.create(
                topic=self.topic, item_id=uuid4(), task_id=uuid4(), run_id=uuid4(), parent_turn=self.turn
            )
        with self.assertRaises(ValidationError):
            spawn_child(
                self.team,
                self.user,
                self.topic.conversation_id,
                self.turn.run_id,
                self.topic_id,
                uuid4(),
                "Review",
                "Investigate",
            )

    def test_wait_releases_on_failure_and_leaves_other_children_for_notification(self) -> None:
        first = BoardRun.objects.create(
            topic=self.topic, item_id=uuid4(), task_id=uuid4(), run_id=uuid4(), parent_turn=self.turn, finished=True
        )
        second = BoardRun.objects.create(
            topic=self.topic, item_id=uuid4(), task_id=uuid4(), run_id=uuid4(), parent_turn=self.turn
        )
        result = wait_for_children(
            self.team,
            self.user,
            self.topic.conversation_id,
            self.turn.run_id,
            self.topic_id,
            uuid4(),
            [first.item_id, second.item_id],
        )
        assert result["status"] == "waiting"
        wait = ChildWait.objects.get(topic=self.topic)
        self.turn.finished_at = timezone.now()
        self.turn.save(update_fields=["finished_at"])
        runs = {
            self.turn.run_id: SimpleNamespace(is_terminal=True, status="completed"),
            first.run_id: SimpleNamespace(
                is_terminal=True, status="failed", output={}, error_message="Failed", id=first.run_id
            ),
            second.run_id: SimpleNamespace(is_terminal=False),
        }
        new_run = uuid4()
        with (
            patch(
                "products.meep.backend.delegation.api.get_task_run", side_effect=lambda run_id, team_id: runs[run_id]
            ),
            patch("products.meep.backend.delegation.api.run_task", return_value=SimpleNamespace(run_id=new_run)),
            patch("products.meep.backend.delegation.check_access"),
        ):
            reconcile_wait(wait.pk)
        wait.refresh_from_db()
        first.refresh_from_db()
        second.refresh_from_db()
        assert wait.status == "resumed"
        assert first.notified and not second.notified
        assert ChatTurn.objects.get(run_id=new_run).target_message_id == self.turn.message_id

    def test_automatic_notification_waits_for_active_user_turn(self) -> None:
        job = BoardRun.objects.create(
            topic=self.topic, item_id=uuid4(), task_id=uuid4(), run_id=uuid4(), parent_turn=self.turn, finished=True
        )
        run = SimpleNamespace(
            is_terminal=True,
            status="completed",
            output={"reply": "Done", "needs_input": False},
            error_message=None,
            id=job.run_id,
        )
        with (
            patch("products.meep.backend.delegation.api.get_task_run", return_value=run),
            patch(
                "products.meep.backend.delegation.api.run_task", return_value=SimpleNamespace(run_id=uuid4())
            ) as resume,
            patch("products.meep.backend.delegation.check_access"),
        ):
            reconcile_notification(job.pk)
            assert not resume.called
            self.turn.finished_at = timezone.now()
            self.turn.save(update_fields=["finished_at"])
            reconcile_notification(job.pk)
        job.refresh_from_db()
        assert job.notified
        assert resume.call_count == 1

    def test_question_wakes_parent_without_waiting_for_other_children(self) -> None:
        question = BoardRun.objects.create(
            topic=self.topic, item_id=uuid4(), task_id=uuid4(), run_id=uuid4(), parent_turn=self.turn, finished=True
        )
        pending = BoardRun.objects.create(
            topic=self.topic, item_id=uuid4(), task_id=uuid4(), run_id=uuid4(), parent_turn=self.turn
        )
        wait_for_children(
            self.team,
            self.user,
            self.topic.conversation_id,
            self.turn.run_id,
            self.topic_id,
            uuid4(),
            [question.item_id, pending.item_id],
        )
        wait = ChildWait.objects.get(topic=self.topic)
        self.turn.finished_at = timezone.now()
        self.turn.save(update_fields=["finished_at"])
        runs = {
            self.turn.run_id: SimpleNamespace(is_terminal=True, status="completed"),
            question.run_id: SimpleNamespace(
                is_terminal=True,
                status="completed",
                output={"reply": "Which segment?", "needs_input": True},
                error_message=None,
                id=question.run_id,
            ),
            pending.run_id: SimpleNamespace(is_terminal=False),
        }
        with (
            patch(
                "products.meep.backend.delegation.api.get_task_run", side_effect=lambda run_id, team_id: runs[run_id]
            ),
            patch(
                "products.meep.backend.delegation.api.run_task", return_value=SimpleNamespace(run_id=uuid4())
            ) as resume,
            patch("products.meep.backend.delegation.check_access"),
        ):
            reconcile_wait(wait.pk)
        message = resume.call_args.kwargs["validated_data"]["pending_user_message"]
        assert str(question.item_id) in message
        assert str(question.run_id) in message
        assert "Which segment?" in message
