from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.conf import settings

import fakeredis
from parameterized import parameterized
from rest_framework import status

from posthog import redis as redis_module
from posthog.models.user import User

from products.tasks.backend.facade.api import ensure_personal_channel_id

# Keep the SSE generator lifetime tiny so the stream test terminates deterministically.
_TEST_STREAM_LIFETIME = 0.3
_TEST_STREAM_BLOCK_MS = 50


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
        body = b"".join(response.streaming_content).decode()

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
