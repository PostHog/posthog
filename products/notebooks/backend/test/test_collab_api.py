import json
import time

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.conf import settings

import fakeredis
from rest_framework import status

from posthog import redis as redis_module
from posthog.models import Team
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.notebooks.backend import presence
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

    def _collab_save(
        self, notebook, *, version, steps, content=None, text_content=None, title=None, client_id="test-client"
    ):
        payload = {
            "client_id": client_id,
            "version": version,
            "steps": steps,
            "content": content or UPDATED_DOC,
        }
        if text_content is not None:
            payload["text_content"] = text_content
        if title is not None:
            payload["title"] = title
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

    def test_collab_save_allows_blank_title(self):
        notebook = self._create_notebook(SAMPLE_DOC)
        version = notebook["version"]

        response = self._collab_save(
            notebook,
            version=version,
            steps=[{"stepType": "replace", "from": 0, "to": 0}],
            content={"type": "doc", "content": [{"type": "heading"}]},
            text_content="",
            title="",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["title"] == ""
        nb = Notebook.objects.get(short_id=notebook["short_id"])
        assert nb.title == ""
        assert nb.text_content == ""

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

    @patch("products.notebooks.backend.presentation.views.notebook.submit_steps")
    def test_collab_save_returns_410_when_steps_expired(self, mock_submit):
        notebook = self._create_notebook(SAMPLE_DOC)

        mock_submit.return_value = SubmitResult(status="stale", version=5, steps_since=None)

        response = self._collab_save(
            notebook,
            version=notebook["version"],
            steps=[{"stepType": "replace", "from": 0, "to": 0}],
        )
        assert response.status_code == status.HTTP_410_GONE
        data = response.json()
        assert data["code"] == "conflict_stale"

    def test_collab_save_accepted_logs_diff_against_pre_update_snapshot(self):
        # The activity log records a diff between `notebook_before` and `notebook`
        # Django returns independent Python objects per `.get()`,
        # so refreshing one must not bleed into the other
        notebook = self._create_notebook(SAMPLE_DOC)
        version = notebook["version"]

        response = self._collab_save(
            notebook,
            version=version,
            steps=[{"stepType": "replace", "from": 0, "to": 0}],
            content=UPDATED_DOC,
        )
        assert response.status_code == status.HTTP_200_OK

        log = ActivityLog.objects.get(
            team_id=self.team.id,
            scope="Notebook",
            item_id=notebook["short_id"],
            activity="updated",
        )
        assert log.detail is not None
        changes_by_field = {c["field"]: c for c in log.detail["changes"]}

        assert changes_by_field["content"]["action"] == "changed"
        assert changes_by_field["content"]["before"] == SAMPLE_DOC
        assert changes_by_field["content"]["after"] == UPDATED_DOC

        assert changes_by_field["version"]["action"] == "changed"
        assert changes_by_field["version"]["before"] == version
        assert changes_by_field["version"]["after"] == version + 1

        # text_content is excluded from Notebook diffs and should never surface
        assert "text_content" not in changes_by_field

    def test_collab_save_rejected_stale_logs_attempted_content(self):
        notebook = self._create_notebook(SAMPLE_DOC)

        with patch("products.notebooks.backend.presentation.views.notebook.submit_steps") as mock_submit:
            mock_submit.return_value = SubmitResult(status="stale", version=5, steps_since=None)
            self._collab_save(
                notebook,
                version=0,
                steps=[{"stepType": "replace", "from": 0, "to": 0}],
                content=UPDATED_DOC,
            )

        log = ActivityLog.objects.get(
            team_id=self.team.id,
            scope="Notebook",
            item_id=notebook["short_id"],
            activity="save_rejected_stale",
        )
        assert log.detail is not None
        [change] = log.detail["changes"]
        assert change["field"] == "content"
        assert change["before"] == SAMPLE_DOC
        assert change["after"] == UPDATED_DOC

    def test_collab_save_rejected_conflict_logs_attempted_content(self):
        notebook = self._create_notebook(SAMPLE_DOC)
        version = notebook["version"]

        self._collab_save(
            notebook,
            version=version,
            steps=[{"stepType": "replace", "from": 0, "to": 0}],
            client_id="client-1",
        )

        rejected_doc = {"type": "doc", "content": [{"type": "heading", "content": [{"type": "text", "text": "C2"}]}]}
        response = self._collab_save(
            notebook,
            version=version,
            steps=[{"stepType": "replace", "from": 1, "to": 1}],
            content=rejected_doc,
            client_id="client-2",
        )
        assert response.status_code == status.HTTP_409_CONFLICT

        log = ActivityLog.objects.get(
            team_id=self.team.id,
            scope="Notebook",
            item_id=notebook["short_id"],
            activity="save_rejected_conflict",
        )
        assert log.detail is not None
        [change] = log.detail["changes"]
        assert change["field"] == "content"
        # `before` is the server's content at rejection time (post client-1's accepted save)
        assert change["before"] == UPDATED_DOC
        assert change["after"] == rejected_doc


# Keep the SSE generator lifetime tiny so tests terminate deterministically.
# XREAD blocks until we either see data or hit this window;
# then the keepalive loop unwinds and the lifetime cap fires, closing the stream.
_TEST_STREAM_LIFETIME = 0.3
_TEST_STREAM_BLOCK_MS = 50


@patch("products.notebooks.backend.collab_stream.STREAM_LIFETIME_SECONDS", _TEST_STREAM_LIFETIME)
@patch("products.notebooks.backend.collab_stream.STREAM_BLOCK_MS", _TEST_STREAM_BLOCK_MS)
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
            last_saved_version=notebook["version"],
        )

        # Last-Event-ID=0-0 means "from the beginning of the stream", so the pre-populated
        # entry is replayed on connect — same path a reconnecting client takes.
        response = self.client.get(self._stream_url(notebook["short_id"]), HTTP_LAST_EVENT_ID="0-0")

        assert response.status_code == status.HTTP_200_OK
        assert response["Content-Type"] == "text/event-stream"
        assert response["Cache-Control"] == "no-cache, no-transform"
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
            last_saved_version=base_version,
        )
        submit_steps(
            self.team.pk,
            notebook["short_id"],
            "client-B",
            [{"stepType": "replace", "from": 1, "to": 1}],
            base_version + 1,
            last_saved_version=base_version + 1,
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

    @patch(
        "products.notebooks.backend.presentation.views.notebook.transaction.on_commit",
        side_effect=lambda callback: callback(),
    )
    def test_stream_delivers_update_event_after_full_doc_patch(self, _mock_on_commit):
        notebook = self._create_notebook()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/notebooks/{notebook['short_id']}/",
            data={"content": UPDATED_DOC, "version": notebook["version"]},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        stream_response = self.client.get(self._stream_url(notebook["short_id"]), HTTP_LAST_EVENT_ID="0-0")

        assert stream_response.status_code == status.HTTP_200_OK
        body = self._consume_stream(stream_response)
        assert "event: update" in body
        assert f"id: {notebook['version'] + 1}-1" in body
        assert f'"version":{notebook["version"] + 1}' in body

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

    def _presence_url(self, short_id: str) -> str:
        return f"/api/projects/{self.team.id}/notebooks/{short_id}/collab/presence/"

    def test_presence_endpoint_broadcasts_on_stream(self):
        notebook = self._create_notebook()

        response = self.client.post(
            self._presence_url(notebook["short_id"]),
            data={"client_id": "caret-client", "version": notebook["version"], "cursor": {"head": 7}},
            format="json",
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

        body = self._consume_stream(self.client.get(self._stream_url(notebook["short_id"])))
        assert "event: presence" in body
        assert '"client_id":"caret-client"' in body
        assert '"cursor":{"head":7}' in body
        assert f'"user_id":{self.user.pk}' in body
        assert '"user_name"' in body
        # Presence frames must not carry an id: line — Last-Event-ID belongs to the content stream
        presence_frame = next(frame for frame in body.split("\n\n") if "event: presence" in frame)
        assert "id:" not in presence_frame

    def test_stream_skips_presence_older_than_backfill_window(self):
        notebook = self._create_notebook()
        stream_key = presence.PRESENCE_STREAM_KEY_PATTERN.format(team_id=self.team.pk, notebook_id=notebook["short_id"])

        stale_payload = json.dumps(
            {
                "type": "presence",
                "client_id": "old-client",
                "user_id": 1,
                "user_name": "Old",
                "version": 0,
                "cursor": {},
            }
        )
        stale_id = f"{int(time.time() * 1000) - 60_000}-0"
        redis_module.get_client().xadd(stream_key, {"data": stale_payload}, id=stale_id)

        response = self.client.post(
            self._presence_url(notebook["short_id"]),
            data={"client_id": "fresh-client", "version": notebook["version"], "cursor": {"head": 1}},
            format="json",
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

        body = self._consume_stream(self.client.get(self._stream_url(notebook["short_id"])))
        assert '"client_id":"fresh-client"' in body
        assert '"client_id":"old-client"' not in body

    def test_presence_requires_cursor(self):
        notebook = self._create_notebook()

        response = self.client.post(
            self._presence_url(notebook["short_id"]),
            data={"client_id": "caret-client", "version": notebook["version"]},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_presence_returns_404_for_notebook_in_other_team(self):
        other_team = Team.objects.create(organization=self.organization, name="other")
        other_notebook = Notebook.objects.create(team=other_team, created_by=self.user)

        response = self.client.post(
            self._presence_url(other_notebook.short_id),
            data={"client_id": "caret-client", "version": 0, "cursor": {"head": 0}},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_presence_rejects_personal_api_key_without_write_scope(self):
        notebook = self._create_notebook()

        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="read-only-key",
            secure_value=hash_key_value(key_value),
            scopes=["notebook:read"],
        )
        self.client.logout()

        response = self.client.post(
            self._presence_url(notebook["short_id"]),
            data={"client_id": "caret-client", "version": 0, "cursor": {"head": 0}},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


def _markdown_doc(markdown: str) -> dict:
    return {
        "type": "doc",
        "content": [{"type": "ph-markdown-notebook", "attrs": {"nodeId": "n1", "markdown": markdown}}],
    }


class TestNotebookMarkdownSaveAPI(APIBaseTest):
    def _create_markdown_notebook(self, markdown: str = "# Title\n\nHello"):
        response = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/",
            data={"content": _markdown_doc(markdown)},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        return response.json()

    def _markdown_save(self, notebook, *, version, markdown, title=None, client_id="md-client"):
        payload = {
            "client_id": client_id,
            "version": version,
            "content": _markdown_doc(markdown),
            "text_content": markdown,
        }
        if title is not None:
            payload["title"] = title
        return self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook['short_id']}/collab/markdown_save/",
            data=payload,
            format="json",
        )

    def test_markdown_save_accepted(self):
        notebook = self._create_markdown_notebook("# Title\n\nHello")

        response = self._markdown_save(notebook, version=notebook["version"], markdown="# Title\n\nHello world")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["version"] == notebook["version"] + 1
        assert data["content"] == _markdown_doc("# Title\n\nHello world")

        nb = Notebook.objects.get(short_id=notebook["short_id"])
        assert nb.version == notebook["version"] + 1
        assert nb.text_content == "# Title\n\nHello world"

    def test_markdown_save_appends_replayable_diff_to_stream(self):
        from products.notebooks.backend.collab_stream import STREAM_KEY_PATTERN
        from products.notebooks.backend.markdown_collab import apply_utf16_text_changes, markdown_crc

        notebook = self._create_markdown_notebook("# Title\n\nHello")
        self._markdown_save(notebook, version=notebook["version"], markdown="# Title\n\nHello world")

        import json as json_module

        client = redis_module.get_client()
        entries = client.xrange(STREAM_KEY_PATTERN.format(team_id=self.team.pk, notebook_id=notebook["short_id"]))
        assert len(entries) == 1
        stream_id, fields = entries[0]
        assert stream_id.decode() == f"{notebook['version'] + 1}-0"
        payload = json_module.loads(fields[b"data"])
        assert payload["type"] == "update"
        assert payload["client_id"] == "md-client"
        assert payload["base_crc"] == markdown_crc("# Title\n\nHello")
        assert apply_utf16_text_changes("# Title\n\nHello", payload["diff"]) == "# Title\n\nHello world"

    def test_markdown_save_conflict_returns_foldable_updates(self):
        from products.notebooks.backend.markdown_collab import apply_utf16_text_changes

        notebook = self._create_markdown_notebook("base text")
        version = notebook["version"]

        first = self._markdown_save(notebook, version=version, markdown="base text plus A", client_id="client-a")
        assert first.status_code == status.HTTP_200_OK

        response = self._markdown_save(notebook, version=version, markdown="base text plus B", client_id="client-b")
        assert response.status_code == status.HTTP_409_CONFLICT
        data = response.json()
        assert data["code"] == "conflict"
        assert data["version"] == version + 1
        assert len(data["updates"]) == 1
        update = data["updates"][0]
        assert update["version"] == version + 1
        assert update["client_id"] == "client-a"
        assert apply_utf16_text_changes("base text", update["diff"]) == "base text plus A"

        # The losing client's content was not persisted
        nb = Notebook.objects.get(short_id=notebook["short_id"])
        assert nb.version == version + 1
        assert nb.content == _markdown_doc("base text plus A")

    @patch(
        "products.notebooks.backend.presentation.views.notebook.transaction.on_commit",
        side_effect=lambda callback: callback(),
    )
    def test_markdown_save_conflict_replays_legacy_patch_diff(self, _mock_on_commit):
        from products.notebooks.backend.markdown_collab import apply_utf16_text_changes

        notebook = self._create_markdown_notebook("base text")
        version = notebook["version"]

        patch_response = self.client.patch(
            f"/api/projects/{self.team.id}/notebooks/{notebook['short_id']}/",
            data={"content": _markdown_doc("base text via patch"), "version": version},
            format="json",
        )
        assert patch_response.status_code == status.HTTP_200_OK

        response = self._markdown_save(notebook, version=version, markdown="base text plus mine")
        assert response.status_code == status.HTTP_409_CONFLICT
        data = response.json()
        assert data["version"] == version + 1
        assert apply_utf16_text_changes("base text", data["updates"][0]["diff"]) == "base text via patch"

    def test_markdown_save_with_unreplayable_gap_returns_410(self):
        notebook = self._create_markdown_notebook("base text")
        version = notebook["version"]

        # Postgres advanced without any stream entry (e.g. failed publish): nothing to replay.
        Notebook.objects.filter(short_id=notebook["short_id"]).update(version=version + 1)

        response = self._markdown_save(notebook, version=version, markdown="base text plus mine")
        assert response.status_code == status.HTTP_410_GONE
        assert response.json()["code"] == "conflict_stale"

    def test_markdown_save_with_cursor_broadcasts_author_presence_in_update(self):
        from products.notebooks.backend.collab_stream import STREAM_KEY_PATTERN

        notebook = self._create_markdown_notebook("# Title\n\nHello")
        response = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook['short_id']}/collab/markdown_save/",
            data={
                "client_id": "md-client",
                "version": notebook["version"],
                "content": _markdown_doc("# Title\n\nHello world"),
                "cursor": {"node_index": 1, "offset": 11},
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        client = redis_module.get_client()
        entries = client.xrange(STREAM_KEY_PATTERN.format(team_id=self.team.pk, notebook_id=notebook["short_id"]))
        payload = json.loads(entries[0][1][b"data"])
        assert payload["cursor"] == {"node_index": 1, "offset": 11}
        assert payload["user_id"] == self.user.pk
        assert "user_name" in payload

    def test_markdown_save_rejects_non_markdown_content(self):
        notebook = self._create_markdown_notebook()

        response = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook['short_id']}/collab/markdown_save/",
            data={
                "client_id": "md-client",
                "version": notebook["version"],
                "content": SAMPLE_DOC,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_markdown_save_preserves_title_when_omitted_and_clears_when_blank(self):
        notebook = self._create_markdown_notebook()
        rename = self.client.patch(
            f"/api/projects/{self.team.id}/notebooks/{notebook['short_id']}/",
            data={"title": "Keep me"},
            format="json",
        )
        assert rename.status_code == status.HTTP_200_OK

        response = self._markdown_save(notebook, version=notebook["version"], markdown="changed once")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["title"] == "Keep me"

        response = self._markdown_save(notebook, version=notebook["version"] + 1, markdown="changed twice", title="")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["title"] == ""

    def test_markdown_save_logs_activity(self):
        notebook = self._create_markdown_notebook("before")

        self._markdown_save(notebook, version=notebook["version"], markdown="after")

        log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Notebook", item_id=notebook["short_id"], activity="updated"
        ).last()
        assert log is not None

    def test_markdown_save_requires_authentication(self):
        notebook = self._create_markdown_notebook()
        self.client.logout()

        response = self._markdown_save(notebook, version=notebook["version"], markdown="anything")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
