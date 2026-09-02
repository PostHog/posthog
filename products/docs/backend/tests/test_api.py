import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache

import fakeredis
from parameterized import parameterized
from rest_framework import status

from posthog import redis as redis_module
from posthog.models.user import User

from products.docs.backend.facade import api
from products.docs.backend.facade.enums import DataShape
from products.docs.backend.logic import data_points
from products.docs.backend.tasks.tasks import sync_context_doc_task
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.api import ensure_personal_channel_id

# Keep the SSE generator lifetime tiny so the stream test terminates deterministically.
_TEST_STREAM_LIFETIME = 0.3
_TEST_STREAM_BLOCK_MS = 50


_NUMBER_RUN = data_points.DataPointRun(shape=DataShape.NUMBER, value="7", rows=1, columns=1, error=None)


@patch("posthog.collab.stream.STREAM_LIFETIME_SECONDS", _TEST_STREAM_LIFETIME)
@patch("posthog.collab.stream.STREAM_BLOCK_MS", _TEST_STREAM_BLOCK_MS)
class TestDocsAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        redis_module.TEST_clear_clients()
        server = fakeredis.FakeServer()
        redis_module._client_map[settings.REDIS_URL] = fakeredis.FakeRedis(server=server)
        redis_module._test_async_client_map[settings.REDIS_URL] = fakeredis.FakeAsyncRedis(server=server)
        self.addCleanup(redis_module.TEST_clear_clients)

        self.channel_id = str(ensure_personal_channel_id(self.team.pk, self.user.pk))

    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/docs/{suffix}"

    def _create_doc(self, template: str = "blank") -> dict:
        response = self.client.post(self._url(), data={"channel": self.channel_id, "template": template}, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()

    def test_docs_in_another_users_personal_space_are_invisible(self):
        doc = self._create_doc()
        other = User.objects.create_and_join(self.organization, "other@posthog.com", "hunter22")
        self.client.force_login(other)

        listed = self.client.get(self._url() + f"?channel={self.channel_id}")
        retrieved = self.client.get(self._url(f"{doc['id']}/"))

        assert listed.json() == []
        assert retrieved.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand([("blank", 1), ("notes", 4)])
    def test_create_applies_the_template_and_appends_to_the_tab_row(self, template: str, block_count: int):
        first = self._create_doc()
        second = self._create_doc(template)

        assert len(second["content"]["content"]) == block_count
        assert second["position"] == first["position"] + 1

    def test_collab_save_rejects_a_stale_baseline_and_keeps_the_stored_content(self):
        doc = self._create_doc()
        accepted = self.client.post(
            self._url(f"{doc['id']}/collab/save/"),
            data={
                "client_id": "client-1",
                "steps": [{"stepType": "replace", "from": 0, "to": 0}],
                "version": 0,
                "content": {"type": "doc", "content": [{"type": "paragraph"}]},
                "title": "First write",
            },
            format="json",
        )
        assert accepted.status_code == status.HTTP_200_OK, accepted.json()
        assert accepted.json()["version"] == 1

        conflict = self.client.post(
            self._url(f"{doc['id']}/collab/save/"),
            data={
                "client_id": "client-2",
                "steps": [{"stepType": "replace", "from": 1, "to": 1}],
                "version": 0,
                "content": {"type": "doc", "content": []},
                "title": "Second write",
            },
            format="json",
        )

        assert conflict.status_code == status.HTTP_409_CONFLICT
        assert conflict.json()["version"] == 1
        assert len(conflict.json()["steps"]) == 1

        stored = self.client.get(self._url(f"{doc['id']}/")).json()
        assert stored["title"] == "First write"
        assert stored["version"] == 1

    def test_stream_replays_accepted_steps_and_discussion_pings(self):
        doc = self._create_doc()
        self.client.post(
            self._url(f"{doc['id']}/collab/save/"),
            data={
                "client_id": "client-1",
                "steps": [{"stepType": "replace", "from": 0, "to": 0}],
                "version": 0,
                "content": {"type": "doc", "content": [{"type": "paragraph"}]},
            },
            format="json",
        )
        self.client.post(
            self._url(f"{doc['id']}/discussions/"),
            data={"content": "Look here", "anchor_key": "a1", "anchor_text": "here"},
            format="json",
        )

        # Last-Event-ID=0-0 means "from the beginning", the same path a reconnecting client takes.
        response = self.client.get(self._url(f"{doc['id']}/collab/stream/"), HTTP_LAST_EVENT_ID="0-0")
        body = b"".join(cast(Any, response).streaming_content).decode()

        assert response["Content-Type"] == "text/event-stream"
        assert "event: step" in body
        assert "event: discussion" in body

    def test_discussion_thread_carries_its_anchor_replies_and_resolved_state(self):
        doc = self._create_doc()
        created = self.client.post(
            self._url(f"{doc['id']}/discussions/"),
            data={"content": "Is this number right?", "anchor_key": "a1", "anchor_text": "18,400 people"},
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.json()
        thread_id = created.json()["id"]

        self.client.post(
            self._url(f"{doc['id']}/discussions/{thread_id}/reply/"), data={"content": "Checked, it is"}, format="json"
        )
        self.client.post(
            self._url(f"{doc['id']}/discussions/{thread_id}/resolve/"), data={"resolved": True}, format="json"
        )

        threads = self.client.get(self._url(f"{doc['id']}/discussions/")).json()

        assert len(threads) == 1
        assert threads[0]["anchor_key"] == "a1"
        assert threads[0]["anchor_text"] == "18,400 people"
        assert threads[0]["resolved"] is True
        assert [reply["content"] for reply in threads[0]["replies"]] == ["Checked, it is"]

    def _start_thread(self, doc: dict, **extra: Any) -> dict:
        response = self.client.post(
            self._url(f"{doc['id']}/discussions/"),
            data={"content": "Is this right?", "anchor_key": "a1", "anchor_text": "18,400 people", **extra},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()

    def test_reply_that_starts_a_task_keeps_the_task_on_the_thread(self):
        doc = self._create_doc()
        thread = self._start_thread(doc)

        replied = self.client.post(
            self._url(f"{doc['id']}/discussions/{thread['id']}/reply/"),
            data={"content": "@agent what does this count?", "task_id": "task-1", "send_to_agent": True},
            format="json",
        )

        assert replied.status_code == status.HTTP_201_CREATED, replied.json()
        assert replied.json()["delivery"] == "sent"
        assert replied.json()["task_id"] == "task-1"
        assert replied.json()["replies"][0]["sent_to_agent"] is True

    @parameterized.expand([("ok", "sent", True), ("no_run", "no_run", False), ("signal_failed", "failed", False)])
    def test_reply_to_the_agent_reports_what_the_run_did(self, outcome: str, delivery: str, sent: bool):
        doc = self._create_doc()
        thread = self._start_thread(doc, task_id="task-1")

        with patch("products.docs.backend.facade.api.tasks_facade.forward_message_to_run", return_value=outcome):
            replied = self.client.post(
                self._url(f"{doc['id']}/discussions/{thread['id']}/reply/"),
                data={"content": "@agent use last 30 days", "send_to_agent": True},
                format="json",
            )

        assert replied.json()["delivery"] == delivery
        assert replied.json()["replies"][0]["sent_to_agent"] is sent

    def test_agent_turn_lands_once_and_a_data_thread_reads_the_query_out_of_it(self):
        doc = self._create_doc()
        self._start_thread(doc, kind="data", anchor_key="req-1", task_id="task-1", send_to_agent=True)
        text = 'Counted them: <hogql label="teams with replay">SELECT uniq(team_id) FROM events;</hogql>'

        with patch("products.docs.backend.facade.api.data_points.run_once", return_value=_NUMBER_RUN):
            for _ in range(2):
                api.record_agent_turn(team_id=self.team.pk, task_id="task-1", run_id="run-1", turn_key="k1", text=text)

        thread = self.client.get(self._url(f"{doc['id']}/discussions/")).json()[0]
        assert [post["author_kind"] for post in thread["replies"]] == ["agent"]
        assert thread["answer"]["query"] == "SELECT uniq(team_id) FROM events"
        assert thread["answer"]["label"] == "teams with replay"

    def test_a_data_thread_that_gets_words_and_no_query_reminds_the_run_once_per_ask(self):
        doc = self._create_doc()
        thread = self._start_thread(doc, kind="data", anchor_key="req-1", task_id="task-1", send_to_agent=True)
        forward = "products.docs.backend.facade.api.tasks_facade.forward_message_to_run"

        with patch(forward, return_value="ok") as forwarded:
            api.record_agent_turn(
                team_id=self.team.pk, task_id="task-1", run_id="run-1", turn_key="k1", text="0 events."
            )
            api.record_agent_turn(
                team_id=self.team.pk, task_id="task-1", run_id="run-1", turn_key="k2", text="Still 0."
            )
        assert forwarded.call_count == 1
        assert "req-1" in forwarded.call_args.kwargs["content"]

        with patch(forward, return_value="ok") as forwarded:
            self.client.post(
                self._url(f"{doc['id']}/discussions/{thread['id']}/reply/"),
                data={"content": "@agent try again", "send_to_agent": True},
                format="json",
            )
            api.record_agent_turn(team_id=self.team.pk, task_id="task-1", run_id="run-1", turn_key="k3", text="Sorry.")
        assert forwarded.call_count == 2

        posts = self.client.get(self._url(f"{doc['id']}/discussions/")).json()[0]["replies"]
        assert [post["author_kind"] for post in posts] == ["agent", "system", "agent", "human", "agent", "system"]

    def test_a_named_teammate_and_the_page_owner_hear_about_a_thread(self):
        peer = User.objects.create_and_join(self.organization, "peer@example.com", None, first_name="Bob")
        doc = self._create_doc()
        thread = self._start_thread(doc)
        self.client.post(
            self._url(f"{doc['id']}/discussions/{thread['id']}/reply/"),
            data={"content": "@[Bob](Peer@Example.com) can you check this?"},
            format="json",
        )

        rows = tasks_facade.list_task_activity(self.team.pk, peer.id).results
        assert [
            (row.activity_kind, row.task_id, row.latest_comment_scope, row.latest_comment_item_id) for row in rows
        ] == [("mention", None, "doc", doc["id"])]
        assert rows[0].task_title == doc["title"]

    def _submit(self, task_id: str | None, body: dict):
        with (
            patch("products.docs.backend.presentation.views._sandbox_task_id", return_value=task_id),
            patch("products.docs.backend.facade.api.data_points.run_once", return_value=_NUMBER_RUN),
            patch("products.docs.backend.facade.api.tasks_facade.latest_run_id", return_value=None),
        ):
            return self.client.post(self._url("data_points/submit/"), data=body, format="json")

    def test_only_the_asked_run_can_submit_and_a_second_submit_replaces_the_query(self):
        doc = self._create_doc()
        self._start_thread(doc, kind="data", anchor_key="req-1", task_id="task-1", send_to_agent=True)

        other = self._submit("task-2", {"request_id": "req-1", "query": "SELECT 1", "label": "one"})
        assert other.status_code == status.HTTP_403_FORBIDDEN

        first = self._submit("task-1", {"request_id": "req-1", "query": "SELECT 1;", "label": "one"})
        second = self._submit("task-1", {"request_id": "req-1", "query": "SELECT 2", "label": "two"})
        assert first.json() == {"ok": True, "shape": "number", "value": "7", "rows": 1, "columns": 1, "error": None}
        assert second.status_code == status.HTTP_200_OK

        thread = self.client.get(self._url(f"{doc['id']}/discussions/")).json()[0]
        assert thread["answer"]["query"] == "SELECT 2"
        assert thread["answer"]["label"] == "two"
        assert [post["content"] for post in thread["replies"]] == [
            "Put the number on the page.",
            "Updated the number on the page.",
        ]

    @parameterized.expand([("DELETE FROM events",), ("SELECT 1; SELECT 2",), ("",)])
    def test_submit_refuses_anything_but_one_select(self, query: str):
        doc = self._create_doc()
        self._start_thread(doc, kind="data", anchor_key="req-1", task_id="task-1", send_to_agent=True)

        response = self._submit("task-1", {"request_id": "req-1", "query": query, "label": "x"})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["ok"] is False
        assert self.client.get(self._url(f"{doc['id']}/discussions/")).json()[0]["answer"] is None

    def test_submit_with_no_answer_says_why_in_the_thread(self):
        doc = self._create_doc()
        self._start_thread(doc, kind="data", anchor_key="req-1", task_id="task-1", send_to_agent=True)

        response = self._submit("task-1", {"request_id": "req-1", "status": "none", "note": "No replay events yet."})

        assert response.json()["ok"] is True
        thread = self.client.get(self._url(f"{doc['id']}/discussions/")).json()[0]
        assert thread["answer"] is None
        assert thread["replies"][-1]["content"] == "No replay events yet."
        assert thread["replies"][-1]["author_kind"] == "agent"

    def _fake_scout(self):
        config = type("Config", (), {"id": uuid.uuid4(), "skill_name": "signals-scout-doc-watch-abc"})()
        return type("Created", (), {"config": config, "created": True, "skill": None})()

    def _watch(self, doc: dict, value: str = "5", **extra: Any) -> dict:
        thread = self._start_thread(
            doc,
            kind="watch",
            anchor_key="w1",
            anchor_text="most signups came from two countries",
            task_id="task-7",
            send_to_agent=True,
            **extra,
        )
        run = data_points.DataPointRun(shape=DataShape.NUMBER, value=value, rows=1, columns=1, error=None)
        with (
            patch("products.docs.backend.presentation.views._sandbox_task_id", return_value="task-7"),
            patch("products.docs.backend.logic.data_points.run_once", return_value=run),
            patch("products.docs.backend.facade.api.tasks_facade.latest_run_id", return_value=None),
            patch(
                "products.docs.backend.facade.api.signals_facade.create_scout_for_source",
                return_value=self._fake_scout(),
            ),
        ):
            response = self.client.post(
                self._url("watches/brief/"),
                data={
                    "request_id": "w1",
                    "claim": "Most signups come from two countries.",
                    "confirms": "The two countries keep over half of signups.",
                    "refutes": "Their share drops under half.",
                    "evidence": [{"label": "signups last month", "query": "SELECT count() FROM events"}],
                    "signals": ["signup_completed by country"],
                },
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["ok"] is True
        return thread

    def _thread(self, doc: dict) -> dict:
        return self.client.get(self._url(f"{doc['id']}/discussions/")).json()[0]

    def test_a_watch_brief_lands_and_only_its_run_may_send_it(self):
        doc = self._create_doc()
        self._watch(doc)

        thread = self._thread(doc)
        watch = thread["watch"]
        assert watch["status"] == "active"
        assert watch["verdict"]["verdict"] == "holding"
        assert watch["brief"]["evidence"][0]["baseline"] == 5.0
        assert watch["scout"]["skill_name"] == "signals-scout-doc-watch-abc"
        assert thread["replies"][-1]["content"] == "Watching. 1 check runs daily. The scout follows 1 signal daily."

        with patch("products.docs.backend.presentation.views._sandbox_task_id", return_value="task-8"):
            other = self.client.post(
                self._url("watches/brief/"), data={"request_id": "w1", "claim": "x"}, format="json"
            )
        assert other.status_code == status.HTTP_403_FORBIDDEN

    def test_evidence_that_moves_is_said_once_and_the_scout_is_asked_why(self):
        doc = self._create_doc()
        self._watch(doc)
        moved = data_points.DataPointRun(shape=DataShape.NUMBER, value="2", rows=1, columns=1, error=None)
        later = datetime.now(UTC) + timedelta(days=2)

        with (
            patch("products.docs.backend.logic.data_points.run_once", return_value=moved),
            patch("products.docs.backend.facade.api.signals_facade.run_scout_now_for_source", return_value=True),
            patch("products.docs.backend.facade.api.signals_facade.scout_reports_for_source", return_value=[]),
        ):
            assert api.check_due_watches(now=later) == 1
            assert api.check_due_watches() == 0

        thread = self._thread(doc)
        assert thread["watch"]["verdict"]["verdict"] == "moved"
        assert thread["watch"]["brief"]["evidence"][0]["moved"] is True
        lines = [post["content"] for post in thread["replies"] if post["author_kind"] == "system"]
        assert lines[-1] == "“signups last month” moved from 5 to 2. The scout is looking into why."

    def test_the_watch_stops_when_its_words_leave_the_page(self):
        doc = self._create_doc()
        self._watch(doc)

        with patch("products.docs.backend.facade.api.signals_facade.update_scout_for_source") as toggle:
            saved = self.client.post(
                self._url(f"{doc['id']}/collab/save/"),
                data={
                    "client_id": "c",
                    "steps": [],
                    "version": 0,
                    "content": {"type": "doc", "content": [{"type": "paragraph"}]},
                },
                format="json",
            )
        assert saved.status_code == status.HTTP_200_OK, saved.json()
        thread = self._thread(doc)
        assert thread["watch"]["status"] == "stopped"
        assert thread["watch"]["stopped_reason"] == "section_removed"
        assert thread["resolved"] is True
        assert toggle.call_args.kwargs["enabled"] is False

    def test_a_done_page_pauses_its_watches_and_reopening_resumes_them(self):
        doc = self._create_doc()
        self._watch(doc)

        with patch("products.docs.backend.facade.api.signals_facade.update_scout_for_source"):
            self.client.patch(self._url(f"{doc['id']}/"), data={"status": "done"}, format="json")
            assert self._thread(doc)["watch"]["status"] == "paused"
            self.client.patch(self._url(f"{doc['id']}/"), data={"status": "active"}, format="json")
        assert self._thread(doc)["watch"]["status"] == "active"

    def test_a_scout_run_sets_the_verdict_and_refuted_ends_the_watch(self):
        doc = self._create_doc()
        self._watch(doc)

        with (
            patch("products.docs.backend.presentation.views._sandbox_task_id", return_value="scout-task"),
            patch("products.docs.backend.facade.api.signals_facade.scout_run_owns_task", return_value=True),
            patch("products.docs.backend.facade.api.signals_facade.update_scout_for_source"),
            patch("products.docs.backend.facade.api.tasks_facade.latest_run_id", return_value=None),
        ):
            response = self.client.post(
                self._url("watches/verdict/"),
                data={"request_id": "w1", "verdict": "refuted", "reason": "The two countries fell to 30%."},
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK, response.json()
        thread = self._thread(doc)
        assert thread["watch"]["verdict"] == {
            "verdict": "refuted",
            "reason": "The two countries fell to 30%.",
            "by": "agent",
            "at": thread["watch"]["verdict"]["at"],
        }
        assert thread["watch"]["status"] == "stopped"
        assert [post["content"] for post in thread["replies"][-2:]] == [
            "Refuted. The two countries fell to 30%.",
            "Refuted, so the watch ended.",
        ]

    def test_a_number_on_the_page_is_watched_without_the_agent(self):
        doc = self._create_doc()
        with patch("products.docs.backend.logic.data_points.run_once", return_value=_NUMBER_RUN):
            thread = self._start_thread(
                doc,
                kind="watch",
                anchor_key="req-9",
                anchor_text="teams with replay on",
                evidence=[{"label": "teams with replay on", "query": "SELECT count() FROM events"}],
            )

        assert thread["watch"]["evidence_only"] is True
        assert thread["watch"]["scout"] is None
        assert thread["watch"]["verdict"]["verdict"] == "holding"
        assert thread["watch"]["brief"]["evidence"][0]["baseline"] == 7.0

    def test_a_turn_shaped_by_the_schema_becomes_the_data_point(self):
        doc = self._create_doc()
        self._start_thread(doc, kind="data", anchor_key="req-2", task_id="task-2", send_to_agent=True)

        with patch("products.docs.backend.facade.api.data_points.run_once", return_value=_NUMBER_RUN):
            api.record_agent_turn(
                team_id=self.team.pk,
                task_id="task-2",
                run_id="run-2",
                turn_key="k2",
                text='{"status": "ok", "query": "SELECT count() FROM events", "label": "events", "note": ""}',
            )

        thread = self.client.get(self._url(f"{doc['id']}/discussions/")).json()[0]
        assert thread["answer"]["query"] == "SELECT count() FROM events"
        assert [(post["author_kind"], post["content"]) for post in thread["replies"]] == [
            ("system", "Put the number on the page.")
        ]

    def test_space_home_says_what_lives_in_each_page_and_lists_the_watches(self):
        doc = self._create_doc()
        self.client.post(
            self._url(f"{doc['id']}/collab/save/"),
            data={
                "client_id": "c",
                "steps": [],
                "version": 0,
                "content": {"type": "doc", "content": [{"type": "paragraph"}]},
                "text_content": "Replay went on for the whole team in August.",
            },
            format="json",
        )
        self._start_thread(doc)
        self._watch(doc)
        api.record_agent_turn(team_id=self.team.pk, task_id="task-7", run_id="r", turn_key="k", text="Still growing.")

        home = self.client.get(self._url("home/") + f"?channel={self.channel_id}").json()

        page = next(entry for entry in home["docs"] if entry["id"] == doc["id"])
        assert page["excerpt"] == "Replay went on for the whole team in August."
        assert page["open_thread_count"] == 1
        assert page["watch_count"] == 1
        assert home["watches"][0]["anchor_text"] == "most signups came from two countries"
        assert home["watches"][0]["verdict"] == "holding"
        assert home["watches"][0]["last_report"] == "Still growing."

    def _wiki(self, content: str):
        page = type("Page", (), {"content": content, "head_sha": "abc", "path": "projects/1/spaces/general.md"})()
        return (
            patch(
                "products.docs.backend.logic.documents.context_layer.resolve_channel_page",
                return_value="projects/1/spaces/general.md",
            ),
            patch("products.docs.backend.logic.documents.context_layer.get_page", return_value=page),
            patch(
                "products.docs.backend.facade.api.context_layer.resolve_channel_page",
                return_value="projects/1/spaces/general.md",
            ),
            patch("products.docs.backend.facade.api.context_layer.get_page", return_value=page),
        )

    def test_the_context_doc_is_made_once_from_the_wiki_notes_and_stays_out_of_the_pages(self):
        wiki = "---\nteam_id: 1\nchannel_id: c\n---\n\n# General (project 1)\n\nSessions are **cheap**.\n"
        with (
            self._wiki(wiki)[0],
            self._wiki(wiki)[1],
        ):
            first = self.client.get(self._url("context/") + f"?channel={self.channel_id}")
            second = self.client.get(self._url("context/") + f"?channel={self.channel_id}")

        assert first.status_code == status.HTTP_200_OK, first.json()
        assert first.json()["id"] == second.json()["id"]
        assert first.json()["kind"] == "context"
        paragraph = first.json()["content"]["content"][0]
        assert paragraph["content"][1] == {"type": "text", "text": "cheap", "marks": [{"type": "bold"}]}
        pages = self.client.get(self._url() + f"?channel={self.channel_id}").json()
        assert first.json()["id"] not in {page["id"] for page in pages}

    def test_saving_the_context_doc_compiles_it_into_the_wiki_page(self):
        wiki = "---\nteam_id: 1\n---\n\n# General (project 1)\n\nOld notes.\n"
        patches = self._wiki(wiki)
        with patches[0], patches[1]:
            doc = self.client.get(self._url("context/") + f"?channel={self.channel_id}").json()

        with patch("products.docs.backend.facade.api.schedule_context_sync") as schedule:
            saved = self.client.post(
                self._url(f"{doc['id']}/collab/save/"),
                data={
                    "client_id": "c",
                    "steps": [],
                    "version": doc["version"],
                    "content": {
                        "type": "doc",
                        "content": [
                            {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Rules"}]},
                            {"type": "paragraph", "content": [{"type": "text", "text": "Ship small."}]},
                        ],
                    },
                },
                format="json",
            )
        assert saved.status_code == status.HTTP_200_OK, saved.json()
        schedule.assert_called_once()

        with (
            patches[2],
            patches[3],
            patch("products.docs.backend.facade.api.context_layer.write_page", return_value="def") as write,
        ):
            head = api.sync_context_doc(doc["id"])

        assert head == "def"
        written = write.call_args.kwargs["content"]
        assert "# General (project 1)" in written
        assert "## Rules\n\nShip small.\n" in written
        assert f"doc_id: {doc['id']}" in written

    def test_scheduling_the_compile_coalesces_a_burst_of_saves_into_one_task(self):
        doc_id = uuid.uuid4()
        cache.delete(f"docs:context-sync:{doc_id}")
        with patch.object(sync_context_doc_task, "apply_async") as apply_async:
            api.schedule_context_sync(doc_id)
            api.schedule_context_sync(doc_id)

        apply_async.assert_called_once_with((str(doc_id),), countdown=api.CONTEXT_SYNC_DELAY_SECONDS)
        cache.delete(f"docs:context-sync:{doc_id}")
