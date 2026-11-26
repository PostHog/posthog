from uuid import UUID, uuid4

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework.exceptions import ValidationError

from products.meep.backend.authoring import finish_view
from products.meep.backend.board import finish_board
from products.meep.backend.chat import finish_turn
from products.meep.backend.child_input import answer_child
from products.meep.backend.delegation import spawn_child, wait_for_children
from products.meep.backend.github import mission_repository
from products.meep.backend.models import BoardRun, ChatTurn, Topic, ViewJob
from products.meep.backend.replication import apply_command
from products.meep.backend.tasks import reconcile_topic_tasks, schedule_delegated_task_recovery
from products.tasks.backend.facade import access, api
from products.tasks.backend.models import TaskRun


@pytest.mark.parametrize(
    ("mission", "expected"),
    [
        (
            "Read https://github.com/Example/Atlas/pull/5 and https://github.com/example/atlas/issues/7.",
            "example/atlas",
        ),
        ("Compare https://github.com/example/atlas to https://github.com/example/delta", None),
        ("Read https://example.com/example/atlas", None),
        ("Read https://example.com/?redirect=https://github.com/example/atlas", None),
        ("Review the new feature", None),
    ],
)
def test_mission_repository(mission: str, expected: str | None) -> None:
    assert mission_repository(mission) == expected


class TestTopics(APIBaseTest):
    def test_create_and_read_topic(self) -> None:
        url = f"/api/projects/{self.team.id}/meep/topics/"
        created = self.client.post(url, {"title": "Activation", "mission": "Explain first-week dropoffs."})
        assert created.status_code == 201, created.content
        topic = Topic.objects.for_team(self.team.id).get(pk=created.json()["id"])
        assert topic.owner_id == self.user.pk
        assert self.client.get(f"{url}{topic.id}/").json()["mission"] == topic.mission
        assert self.client.get(url).json()["results"][0]["id"] == str(topic.pk)

    def test_cannot_bind_an_unknown_task(self) -> None:
        topic = Topic.objects.for_team(self.team.id).create(
            team=self.team, owner=self.user, title="Retention", mission="Look for churn"
        )
        url = f"/api/projects/{self.team.id}/meep/topics/{topic.pk}/conversation/"
        assert self.client.post(url, {"task_id": str(uuid4())}).status_code == 400
        topic.refresh_from_db()
        assert topic.conversation_id is None

    def test_cannot_read_another_members_topic(self) -> None:
        other = self._create_user("other@example.com")
        topic = Topic.objects.for_team(self.team.id).create(
            team=self.team, owner=other, title="Private", mission="Member research"
        )
        url = f"/api/projects/{self.team.id}/meep/topics/"
        assert self.client.get(url).json()["results"] == []
        assert self.client.get(f"{url}{topic.pk}/").status_code == 404

    def test_replica_retries_and_pulls_board_edits(self) -> None:
        url = f"/api/projects/{self.team.pk}/meep/v1/"
        topic, task = str(uuid4()), str(uuid4())
        batch = {
            "commands": [
                {
                    "id": str(uuid4()),
                    "topic": topic,
                    "command": {"kind": "CreateTopicWithoutSort", "name": "Activation", "mission": "Explain dropoff"},
                },
                {
                    "id": str(uuid4()),
                    "topic": topic,
                    "command": {"kind": "AddTask", "id": task, "title": "Review onboarding"},
                },
            ]
        }
        first = self.client.post(url + "commands/", batch, format="json")
        assert first.status_code == 200, first.content
        assert [r["status"] for r in first.json()["results"]] == ["applied", "applied"]
        assert self.client.post(url + "commands/", batch, format="json").json() == first.json()
        page = self.client.get(url + "changes/").json()
        assert page["topics"][0]["revision"] == 2
        assert page["topics"][0]["state"]["tasks"][0]["id"] == task
        assert self.client.get(url + "changes/", {"cursor": page["cursor"]}).json()["topics"] == []
        assert self.client.get(url + "views/").json() == []
        assert self.client.get(url + "connections/").json()["connections"][0]["grants"] == [topic]

    def test_repository_attachment_replay_replace_and_detach(self) -> None:
        topic_id, create_id = uuid4(), uuid4()
        create = {
            "kind": "CreateTopicWithoutSort",
            "name": "Source review",
            "mission": "Review https://github.com/example/first/pull/7",
        }
        apply_command(self.team.id, self.user, create_id, topic_id, create)
        apply_command(self.team.id, self.user, create_id, topic_id, create)
        topic = Topic.objects.for_team(self.team.pk).get(pk=topic_id)
        assert topic.state["topic"]["context_sources"] == []
        topic.conversation_id = uuid4()
        topic.save(update_fields=["conversation_id"])
        source = {
            "id": str(uuid4()),
            "key": "example/second",
            "label": "example/second",
            "connection": "github",
            "kind": "repository",
        }
        add = {
            "kind": "SelectGithubRepository",
            "previous": None,
            "id": source["id"],
            "repository": source["key"],
        }
        with patch("products.meep.backend.replication.personal_repository_available", return_value=False):
            with self.assertRaises(ValidationError):
                apply_command(self.team.id, self.user, uuid4(), topic_id, add)
        topic.refresh_from_db()
        assert topic.conversation_id is not None
        with patch("products.meep.backend.replication.personal_repository_available", return_value=True):
            apply_command(self.team.id, self.user, uuid4(), topic_id, add)
        topic.refresh_from_db()
        assert topic.state["topic"]["context_sources"] == [source]
        assert topic.conversation_id is not None
        apply_command(
            self.team.id, self.user, uuid4(), topic_id, {**add, "previous": None, "repository": "example/stale"}
        )
        topic.refresh_from_db()
        assert topic.state["topic"]["context_sources"] == [source]
        apply_command(
            self.team.id, self.user, uuid4(), topic_id, {"kind": "RemoveContextSource", "source": source["id"]}
        )
        topic.refresh_from_db()
        assert topic.state["topic"]["context_sources"] == []

    def test_mission_repository_requires_owner_approval(self) -> None:
        topic_id = uuid4()
        create = api.create_and_run_task
        with (
            patch("products.meep.backend.chat.check_access"),
            patch(
                "products.meep.backend.chat.api.create_and_run_task",
                side_effect=lambda **kwargs: create(**kwargs, start_workflow=False),
            ),
        ):
            apply_command(
                self.team.pk,
                self.user,
                uuid4(),
                topic_id,
                {"kind": "CreateTopic", "name": "Source review", "mission": "Review https://github.com/example/atlas"},
            )
        turn = ChatTurn.objects.get(topic_id=topic_id)
        TaskRun.objects.filter(pk=turn.run_id).update(
            status="completed", output={"reply": "Keep this source handy.", "suggested_repository": "example/atlas"}
        )
        finish_turn(turn.run_id, self.team.pk)
        topic = Topic.objects.for_team(self.team.pk).get(pk=topic_id)
        assert not topic.state["topic"]["context_sources"]
        thread = topic.state["threads"][0]
        proposed = thread["state"]["NeedsYou"]["suggestions"][0]
        assert proposed == {"LinkRepository": {"repository": "example/atlas", "previous": None}}
        with patch("products.meep.backend.replication.personal_repository_available", return_value=True):
            apply_command(
                self.team.pk,
                self.user,
                uuid4(),
                topic_id,
                {
                    "kind": "Answer",
                    "thread": thread["id"],
                    "expected_review": thread.get("review_version", 0),
                    "task_id": str(uuid4()),
                    "suggestion": proposed,
                },
            )
        topic.refresh_from_db()
        assert [w["key"] for w in topic.state["topic"]["context_sources"]] == ["example/atlas"]

    def test_view_replication_and_idempotent_replay(self) -> None:
        url = f"/api/projects/{self.team.pk}/meep/v1/views/"
        cmd = {
            "id": str(uuid4()),
            "view": str(uuid4()),
            "at": "2026-11-01T00:00:00Z",
            "command": {"kind": "create", "prompt": "Show activation"},
        }
        create = api.create_and_run_task
        with (
            patch("products.meep.backend.authoring.check_access"),
            patch(
                "products.meep.backend.authoring.api.create_and_run_task",
                side_effect=lambda **kwargs: create(**kwargs, start_workflow=False),
            ),
        ):
            result = self.client.post(url + "commands/", cmd, format="json")
            assert result.status_code == 200, result.content
            assert self.client.post(url + "commands/", cmd, format="json").json() == result.json()
        assert self.client.get(url).json() == [result.json()]
        job = ViewJob.objects.get(turn_id=cmd["id"])
        script = 'view({render(){return Page({},Text("Activation"));}})'
        TaskRun.objects.filter(pk=job.run_id).update(
            status=TaskRun.Status.COMPLETED, output={"title": "Activation", "source": script, "reply": "Ready."}
        )
        finish_view(job.run_id, self.team.pk)
        finish_view(job.run_id, self.team.pk)
        published = self.client.get(url).json()[0]
        assert published["turns"][0]["stage"] == {"Finished": "Ready."}, published
        assert [r["source"] for r in published["revisions"]] == [script]

    def test_chat_creates_one_posthog_task_and_applies_its_reply(self) -> None:
        url = f"/api/projects/{self.team.pk}/meep/v1/"
        topic, message = str(uuid4()), str(uuid4())
        commands = [
            {
                "id": str(uuid4()),
                "topic": topic,
                "command": {"kind": "CreateTopicWithoutSort", "name": "Activation", "mission": "Explain dropoff"},
            },
            {
                "id": str(uuid4()),
                "topic": topic,
                "command": {"kind": "Chat", "message_id": message, "task_id": str(uuid4()), "text": "What changed?"},
            },
        ]
        create = api.create_and_run_task
        with (
            patch(
                "products.meep.backend.chat.api.create_and_run_task",
                side_effect=lambda **kwargs: create(**kwargs, start_workflow=False),
            ),
            patch("products.meep.backend.chat.usage.task_run_usage_limited", return_value=False),
            patch(
                "products.meep.backend.chat.access.get_desktop_access_decision",
                return_value=access.DesktopAccessDecision.ALLOWED,
            ),
        ):
            result = self.client.post(url + "commands/", {"commands": commands}, format="json")
            assert result.status_code == 200, result.content
            assert [r["status"] for r in result.json()["results"]] == ["applied", "applied"], result.content
            assert self.client.post(url + "commands/", {"commands": commands}, format="json").json() == result.json()
        turn = ChatTurn.objects.get(topic_id=topic)
        TaskRun.objects.filter(pk=turn.run_id).update(
            status=TaskRun.Status.COMPLETED, output={"reply": "Activation increased."}
        )
        finish_turn(turn.run_id, self.team.pk)
        finish_turn(turn.run_id, self.team.pk)
        state = self.client.get(url + "topics/" + topic + "/").json()
        assert state["revision"] == 3
        assert state["state"]["threads"][0]["outcomes"] == [{"Reply": {"to": "User", "text": "Activation increased."}}]

    def test_file_history_survives_a_competing_offline_write(self) -> None:
        topic = Topic.objects.for_team(self.team.id).create(
            team=self.team, owner=self.user, title="Files", mission="Review"
        )
        url = f"/api/projects/{self.team.pk}/meep/v1/topics/{topic.pk}/files/notes/readme.txt/"
        for base, data in [(0, b"draft"), (1, b"accepted"), (1, b"offline")]:
            key = str(uuid4())
            for _ in range(2):
                response = self.client.put(
                    url,
                    data,
                    content_type="application/octet-stream",
                    HTTP_IDEMPOTENCY_KEY=key,
                    HTTP_X_MEEP_BASE_REVISION=str(base),
                )
                assert response.status_code == 200, response.content
                assert response.content == data
        assert response["x-meep-conflict-head"] == "2"
        assert self.client.get(url).content == b"accepted"
        assert self.client.get(url, {"revision": 3}).content == b"offline"
        topic.refresh_from_db()
        assert topic.state["threads"][-1]["key"] == "file-review/3/notes/readme.txt"

    def test_read_only_device_cannot_upload(self) -> None:
        topic = Topic.objects.for_team(self.team.pk).create(
            team=self.team, owner=self.user, title="Scoped", mission="Read"
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + self.create_personal_api_key_with_scopes(["meep:read"]))
        url = f"/api/projects/{self.team.pk}/meep/v1/topics/{topic.pk}/files/"
        assert self.client.get(url).status_code == 200
        assert (
            self.client.put(url + "example.txt/", b"example", content_type="application/octet-stream").status_code
            == 403
        )

    def test_agent_board_task_runs_only_when_started(self) -> None:
        url = f"/api/projects/{self.team.pk}/meep/v1/"
        topic, item = str(uuid4()), str(uuid4())

        def send(command: dict) -> dict:
            batch = {"commands": [{"id": str(uuid4()), "topic": topic, "command": command}]}
            response = self.client.post(url + "commands/", batch, format="json")
            assert response.status_code == 200, response.content
            assert response.json()["results"][0]["status"] == "applied", response.content
            return response.json()

        send({"kind": "CreateTopicWithoutSort", "name": "Board", "mission": "Investigate trends"})
        send({"kind": "AddConfiguredTask", "id": item, "title": "Explain activation", "start": False})
        assert not BoardRun.objects.filter(topic_id=topic).exists()
        create = api.create_and_run_task
        with (
            patch("products.meep.backend.board.check_access"),
            patch(
                "products.meep.backend.board.api.create_and_run_task",
                side_effect=lambda **kwargs: create(**kwargs, start_workflow=False),
            ),
        ):
            send({"kind": "StartTask", "task": item})
        job = BoardRun.objects.get(topic_id=topic, item_id=item)
        TaskRun.objects.filter(pk=job.run_id).update(
            status=TaskRun.Status.COMPLETED, output={"reply": "Signup volume rose."}
        )
        finish_board(job.run_id, self.team.pk)
        row = self.client.get(url + f"topics/{topic}/").json()["state"]["tasks"][0]
        assert (row["column"], row["result"]) == ("Done", "Signup volume rose.")
        conversation_url = url + f"topics/{topic}/tasks/{item}/conversation/"
        conversation = self.client.get(conversation_url)
        assert conversation.status_code == 200, conversation.content
        assert conversation.json()["brief"] == "Explain activation"
        assert [attempt["reply"] for attempt in conversation.json()["attempts"]] == ["Signup volume rose."]
        with (
            patch("products.meep.backend.board.check_access"),
        ):
            message = self.client.post(url + f"topics/{topic}/tasks/{item}/messages/", {"text": "Which week?"})
        assert message.status_code == 200, message.content
        followup = BoardRun.objects.exclude(pk=job.pk).get(topic_id=topic, item_id=item)
        assert followup.task_id == job.task_id
        assert TaskRun.objects.get(pk=followup.run_id).state["pending_user_message"] == "Which week?"

    def test_offline_child_question_answer_and_recovery(self) -> None:
        topic_id, message_id = uuid4(), uuid4()
        apply_command(
            self.team.pk,
            self.user,
            uuid4(),
            topic_id,
            {"kind": "CreateTopicWithoutSort", "name": "Research", "mission": "Review the chart"},
        )
        original_create = api.create_and_run_task
        with (
            patch("products.tasks.backend.temporal.client.execute_task_processing_workflow"),
            patch.object(
                api, "create_and_run_task", side_effect=lambda **kw: original_create(**kw, start_workflow=False)
            ),
            patch("products.meep.backend.chat.usage.task_run_usage_limited", return_value=False),
            patch(
                "products.meep.backend.chat.access.get_desktop_access_decision",
                return_value=access.DesktopAccessDecision.ALLOWED,
            ),
        ):
            apply_command(
                self.team.pk,
                self.user,
                uuid4(),
                topic_id,
                {
                    "kind": "Chat",
                    "message_id": str(message_id),
                    "task_id": str(uuid4()),
                    "text": "Investigate the chart.",
                },
            )
            topic = Topic.objects.for_team(self.team.pk).get(pk=topic_id)
            parent = topic.turns.get()
            child = spawn_child(
                team=self.team,
                user=self.user,
                topic_id=topic_id,
                parent_task_id=topic.conversation_id,
                parent_run_id=parent.run_id,
                request_id=uuid4(),
                title="Check date ranges",
                instructions="Compare the chart windows",
            )
            sibling = spawn_child(
                team=self.team,
                user=self.user,
                topic_id=topic_id,
                parent_task_id=topic.conversation_id,
                parent_run_id=parent.run_id,
                request_id=uuid4(),
                title="Check volume",
                instructions="Count signups",
            )
            wait_for_children(
                team=self.team,
                user=self.user,
                topic_id=topic_id,
                parent_task_id=topic.conversation_id,
                parent_run_id=parent.run_id,
                request_id=uuid4(),
                item_ids=[UUID(child["item_id"]), UUID(sibling["item_id"])],
            )
            TaskRun.objects.filter(pk=parent.run_id).update(status="completed", output={"reply": "Checking."})
            TaskRun.objects.filter(pk=sibling["run_id"]).update(
                status="completed", output={"reply": "Volume is stable.", "needs_input": False}
            )
            reconcile_topic_tasks(self.team.pk, str(topic_id))
            assert topic.turns.count() == 1
            TaskRun.objects.filter(pk=child["run_id"]).update(
                status="completed", output={"reply": "Which week?", "needs_input": True}
            )
            with patch.object(reconcile_topic_tasks, "delay", side_effect=reconcile_topic_tasks.run):
                schedule_delegated_task_recovery()
                schedule_delegated_task_recovery()
            parent_question = topic.turns.get(target_message_id=message_id)
            delivered = TaskRun.objects.get(pk=parent_question.run_id)
            assert "Volume is stable." in delivered.state["pending_user_message"]
            assert "Which week?" in delivered.state["pending_user_message"]
            assert child["run_id"] in delivered.state["pending_user_message"]
            TaskRun.objects.filter(pk=parent_question.run_id).update(
                status="completed", output={"reply": "Which week?"}
            )
            finish_turn(parent_question.run_id, self.team.pk)
            answer_message_id = uuid4()
            apply_command(
                self.team.pk,
                self.user,
                uuid4(),
                topic_id,
                {"kind": "Chat", "message_id": str(answer_message_id), "task_id": str(uuid4()), "text": "Last week"},
            )
            answer_turn = topic.turns.get(message_id=answer_message_id)
            args = {
                "team": self.team,
                "user": self.user,
                "parent_task_id": topic.conversation_id,
                "parent_run_id": answer_turn.run_id,
                "topic_id": topic_id,
                "item_id": UUID(child["item_id"]),
                "request_id": uuid4(),
                "question_run_id": UUID(child["run_id"]),
                "answer": "Last week",
            }
            with self.assertRaisesMessage(ValidationError, "no longer waiting"):
                answer_child(**{**args, "question_run_id": uuid4()})
            result = answer_child(**args)
            assert answer_child(**args) == result
            assert result["task_id"] == child["task_id"]
            assert TaskRun.objects.get(pk=result["run_id"]).state["pending_user_message"] == "Last week"
            TaskRun.objects.filter(pk=answer_turn.run_id).update(status="completed", output={"reply": "Following up."})
            TaskRun.objects.filter(pk=result["run_id"]).update(
                status="completed", output={"reply": "The windows match.", "needs_input": False}
            )
            reconcile_topic_tasks(self.team.pk, str(topic_id))
            resumed = topic.turns.last()
            assert resumed.target_message_id == message_id
            assert "The windows match." in TaskRun.objects.get(pk=resumed.run_id).state["pending_user_message"]
            TaskRun.objects.filter(pk=resumed.run_id).update(
                status="completed", output={"reply": "Both weeks use the same dates."}
            )
            reconcile_topic_tasks(self.team.pk, str(topic_id))
            topic.refresh_from_db()
            assert topic.state["threads"][0]["outcomes"][-1] == {
                "Reply": {"to": "User", "text": "Both weeks use the same dates."}
            }
            assert next(item for item in topic.state["tasks"] if item["id"] == child["item_id"])["column"] == "Done"
