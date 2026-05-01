from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.conf import settings

import fakeredis
from rest_framework import status

from posthog import redis as redis_module
from posthog.models import Team
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.notebooks.backend.collab import SubmitResult, submit_steps
from products.notebooks.backend.models import Notebook

SAMPLE_DOC = {"type": "doc", "content": [{"type": "heading", "content": [{"type": "text", "text": "Test"}]}]}
UPDATED_DOC = {"type": "doc", "content": [{"type": "heading", "content": [{"type": "text", "text": "Updated"}]}]}


class TestNotebookCollabSaveAPI(APIBaseTest):
    def _create_notebook(self, content=None):
        data = {}
        if content:
            data["content"] = content
        response = self.client.post(f"/api/projects/{self.team.id}/notebooks/", data=data, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        return response.json()

    def _collab_save(self, notebook, *, version, steps, content=None, text_content=None, client_id="test-client"):
        payload = {
            "client_id": client_id,
            "version": version,
            "steps": steps,
            "content": content or UPDATED_DOC,
        }
        if text_content is not None:
            payload["text_content"] = text_content
        return self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook['short_id']}/collab/save/",
            data=payload,
            format="json",
        )

    def test_collab_save_accepted(self):
        notebook = self._create_notebook(SAMPLE_DOC)
        version = notebook["version"]

        response = self._collab_save(
            notebook,
            version=version,
            steps=[{"stepType": "replace", "from": 0, "to": 0}],
            content=UPDATED_DOC,
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["version"] == version + 1
        assert data["content"] == UPDATED_DOC

    def test_collab_save_persists_to_postgres(self):
        notebook = self._create_notebook(SAMPLE_DOC)
        version = notebook["version"]

        self._collab_save(
            notebook,
            version=version,
            steps=[{"stepType": "replace", "from": 0, "to": 0}],
            content=UPDATED_DOC,
            text_content="Updated",
        )

        nb = Notebook.objects.get(short_id=notebook["short_id"])
        assert nb.version == version + 1
        assert nb.content == UPDATED_DOC
        assert nb.text_content == "Updated"

    def test_collab_save_updates_title(self):
        notebook = self._create_notebook(SAMPLE_DOC)
        version = notebook["version"]

        self._collab_save(
            notebook,
            version=version,
            steps=[{"stepType": "replace", "from": 0, "to": 0}],
            content=UPDATED_DOC,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook['short_id']}/collab/save/",
            data={
                "client_id": "test-client",
                "version": version + 1,
                "steps": [{"stepType": "replace", "from": 0, "to": 0}],
                "content": UPDATED_DOC,
                "title": "New Title",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        nb = Notebook.objects.get(short_id=notebook["short_id"])
        assert nb.title == "New Title"

    def test_collab_save_rejected_stale_version(self):
        notebook = self._create_notebook(SAMPLE_DOC)
        version = notebook["version"]

        # First client advances the version
        self._collab_save(
            notebook,
            version=version,
            steps=[{"stepType": "replace", "from": 0, "to": 0}],
            client_id="client-1",
        )

        # Second client submits with stale version - gets 409 with missed steps
        # plus the new server version. Client dedupes against any SSE-delivered
        # copies and retries.
        response = self._collab_save(
            notebook,
            version=version,
            steps=[{"stepType": "replace", "from": 1, "to": 1}],
            client_id="client-2",
        )
        assert response.status_code == status.HTTP_409_CONFLICT
        data = response.json()
        assert data["code"] == "conflict"
        assert data["steps"] == [{"stepType": "replace", "from": 0, "to": 0}]
        assert data["client_ids"] == ["client-1"]
        assert data["version"] == version + 1

    def test_collab_save_returns_full_notebook_on_success(self):
        notebook = self._create_notebook(SAMPLE_DOC)
        version = notebook["version"]

        response = self._collab_save(
            notebook,
            version=version,
            steps=[{"stepType": "replace", "from": 0, "to": 0}],
            content=UPDATED_DOC,
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "short_id" in data
        assert "id" in data
        assert "content" in data
        assert "version" in data

    def test_collab_save_missing_required_fields(self):
        notebook = self._create_notebook(SAMPLE_DOC)

        response = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook['short_id']}/collab/save/",
            data={},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("products.notebooks.backend.api.notebook.submit_steps")
    def test_collab_save_returns_410_when_steps_expired(self, mock_submit):
        notebook = self._create_notebook(SAMPLE_DOC)

        mock_submit.return_value = SubmitResult(status="stale", version=5, steps_since=None)

        response = self._collab_save(
            notebook,
            version=0,
            steps=[{"stepType": "replace", "from": 0, "to": 0}],
        )
        assert response.status_code == status.HTTP_410_GONE
        data = response.json()
        assert data["code"] == "conflict_stale"


# Keep the SSE generator lifetime tiny so tests terminate deterministically.
# XREAD blocks until we either see data or hit this window;
# then the keepalive loop unwinds and the lifetime cap fires, closing the stream.
_TEST_STREAM_LIFETIME = 0.3
_TEST_STREAM_BLOCK_MS = 50


@patch("products.notebooks.backend.collab.STREAM_LIFETIME_SECONDS", _TEST_STREAM_LIFETIME)
@patch("products.notebooks.backend.collab.STREAM_BLOCK_MS", _TEST_STREAM_BLOCK_MS)
class TestNotebookCollabStreamAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        # posthog.redis builds FakeRedis / FakeAsyncRedis with independent servers by default,
        # so submit_steps (sync) and stream_collab_sse (async) wouldn't see each other's writes.
        # Pin both to a shared FakeServer for these tests.
        redis_module.TEST_clear_clients()
        server = fakeredis.FakeServer()
        redis_module._client_map[settings.REDIS_URL] = fakeredis.FakeRedis(server=server)
        redis_module._test_async_client_map[settings.REDIS_URL] = fakeredis.FakeAsyncRedis(server=server)
        self.addCleanup(redis_module.TEST_clear_clients)

    def _create_notebook(self):
        response = self.client.post(f"/api/projects/{self.team.id}/notebooks/", data={}, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        return response.json()

    def _stream_url(self, short_id: str, team_id: int | None = None) -> str:
        return f"/api/projects/{team_id or self.team.id}/notebooks/{short_id}/collab/stream/"

    def _consume_stream(self, response) -> str:
        return b"".join(response.streaming_content).decode("utf-8")

    def test_stream_happy_path_delivers_pre_populated_step(self):
        notebook = self._create_notebook()
        submit_steps(
            self.team.pk,
            notebook["short_id"],
            "client-1",
            [{"stepType": "replace", "from": 0, "to": 0}],
            notebook["version"],
        )

        # Last-Event-ID=0-0 means "from the beginning of the stream", so the pre-populated
        # entry is replayed on connect — same path a reconnecting client takes.
        response = self.client.get(self._stream_url(notebook["short_id"]), HTTP_LAST_EVENT_ID="0-0")

        assert response.status_code == status.HTTP_200_OK
        assert response["Content-Type"] == "text/event-stream"
        assert response["Cache-Control"] == "no-cache"
        assert response["X-Accel-Buffering"] == "no"

        body = self._consume_stream(response)
        assert "event: step" in body
        assert f"id: {notebook['version'] + 1}-0" in body
        assert '"client_id":"client-1"' in body
        assert '"stepType":"replace"' in body

    def test_stream_resumes_past_last_event_id(self):
        notebook = self._create_notebook()
        base_version = notebook["version"]

        submit_steps(
            self.team.pk,
            notebook["short_id"],
            "client-A",
            [{"stepType": "replace", "from": 0, "to": 0}],
            base_version,
        )
        submit_steps(
            self.team.pk,
            notebook["short_id"],
            "client-B",
            [{"stepType": "replace", "from": 1, "to": 1}],
            base_version + 1,
        )

        first_step_id = f"{base_version + 1}-0"
        response = self.client.get(
            self._stream_url(notebook["short_id"]),
            HTTP_LAST_EVENT_ID=first_step_id,
        )

        assert response.status_code == status.HTTP_200_OK
        body = self._consume_stream(response)
        assert '"client_id":"client-B"' in body
        assert '"client_id":"client-A"' not in body
        assert f"id: {base_version + 2}-0" in body

    def test_stream_idle_emits_only_keepalives(self):
        notebook = self._create_notebook()

        # Fresh stream, no Last-Event-ID → server tails from "$" (only new entries).
        # Nothing has been submitted, so we should see keepalives but no step frames.
        response = self.client.get(self._stream_url(notebook["short_id"]))

        assert response.status_code == status.HTTP_200_OK
        body = self._consume_stream(response)
        assert "event: step" not in body
        assert ": keepalive" in body

    def test_stream_requires_authentication(self):
        notebook = self._create_notebook()
        self.client.logout()

        response = self.client.get(self._stream_url(notebook["short_id"]))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_stream_returns_404_for_notebook_in_other_team(self):
        other_team = Team.objects.create(organization=self.organization, api_token=self.CONFIG_API_TOKEN + "2")
        other_notebook = Notebook.objects.create(
            team=other_team, created_by=self.user, short_id="other-nb", title="other"
        )

        # URL pinned to our team, short_id belongs to the other team — queryset filters by team_id.
        response = self.client.get(self._stream_url(other_notebook.short_id))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_stream_rejects_personal_api_key_without_notebook_read_scope(self):
        notebook = self._create_notebook()

        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="wrong-scope-key",
            secure_value=hash_key_value(key_value),
            scopes=["dashboard:read"],
        )
        self.client.logout()

        response = self.client.get(
            self._stream_url(notebook["short_id"]),
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )
        # 403 response goes through ServerSentEventRenderer (the action-level renderer),
        # so the body isn't JSON — just assert the gate fired.
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_stream_allows_personal_api_key_with_notebook_read_scope(self):
        notebook = self._create_notebook()

        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="read-scope-key",
            secure_value=hash_key_value(key_value),
            scopes=["notebook:read"],
        )
        self.client.logout()

        response = self.client.get(
            self._stream_url(notebook["short_id"]),
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )
        assert response.status_code == status.HTTP_200_OK
        # Drain the generator so the background bridge thread terminates before the test ends.
        self._consume_stream(response)
