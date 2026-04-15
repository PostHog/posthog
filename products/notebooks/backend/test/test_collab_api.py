from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from products.notebooks.backend.collab import SubmitResult, initialize_collab_session
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

    def _init_collab(self, notebook) -> int:
        initialize_collab_session(self.team.pk, notebook["short_id"], notebook["version"])
        return notebook["version"]

    def test_collab_save_accepted(self):
        notebook = self._create_notebook(SAMPLE_DOC)
        version = self._init_collab(notebook)

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
        version = self._init_collab(notebook)

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
        version = self._init_collab(notebook)

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
        version = self._init_collab(notebook)

        # First client advances the version
        self._collab_save(
            notebook,
            version=version,
            steps=[{"stepType": "replace", "from": 0, "to": 0}],
            client_id="client-1",
        )

        # Second client submits with stale version - gets 409 with missed steps
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
        assert "version" in data

    def test_collab_save_returns_full_notebook_on_success(self):
        notebook = self._create_notebook(SAMPLE_DOC)
        version = self._init_collab(notebook)

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
        self._init_collab(notebook)

        mock_submit.return_value = SubmitResult(accepted=False, version=5, steps_since=None)

        response = self._collab_save(
            notebook,
            version=0,
            steps=[{"stepType": "replace", "from": 0, "to": 0}],
        )
        assert response.status_code == status.HTTP_410_GONE
        data = response.json()
        assert data["code"] == "conflict_stale"
