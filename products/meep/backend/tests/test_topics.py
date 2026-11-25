import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.management import call_command

from products.meep.backend.authoring import finish_view
from products.meep.backend.chat import finish_turn
from products.meep.backend.models import ChatTurn, Topic, ViewJob
from products.meep.backend.replication import snapshot
from products.tasks.backend.facade import access, api
from products.tasks.backend.models import TaskRun


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

    def test_import_snapshots_is_atomic_and_repeatable(self) -> None:
        topic = Topic.objects.for_team(self.team.id).create(
            team=self.team, owner=self.user, title="Source", mission="Explain"
        )
        data = snapshot(topic)["state"]
        pk = str(uuid4())
        data["topic"]["id"] = pk
        with TemporaryDirectory() as directory:
            path = Path(directory) / "topics.sqlite"
            db = sqlite3.connect(path)
            try:
                db.execute("CREATE TABLE records(kind TEXT, id TEXT, body TEXT, deleted INTEGER)")
                db.execute(
                    "INSERT INTO records VALUES ('engine/topic',?,?,0)",
                    (pk, json.dumps({**data, "revision": 7, "capability": "private-fixture"})),
                )
                db.commit()
            finally:
                db.close()
            params = {"project": self.team.pk, "owner": self.user.pk}
            call_command("import_meep_workspace", path, **params)
            assert not Topic.objects.for_team(self.team.id).filter(pk=pk).exists()
            for _ in range(2):
                call_command("import_meep_workspace", path, apply=True, **params)
            imported = Topic.objects.for_team(self.team.id).get(pk=pk)
            assert imported.revision == 7 and imported.state == data
            assert imported.receipts.count() == 1

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
