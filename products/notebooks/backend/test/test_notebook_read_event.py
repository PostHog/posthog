from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

CAPTURE_PATH = "products.notebooks.backend.presentation.views.notebook.capture_notebook_read"


class TestNotebookReadEvent(APIBaseTest):
    def _create_notebook(self) -> str:
        response = self.client.post(f"/api/projects/{self.team.id}/notebooks/", data={}, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        return response.json()["short_id"]

    def _url(self, short_id: str) -> str:
        return f"/api/projects/{self.team.id}/notebooks/{short_id}/"

    @patch(CAPTURE_PATH)
    def test_browser_session_read_does_not_emit(self, mock_capture):
        short_id = self._create_notebook()
        response = self.client.get(self._url(short_id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Browser reads are the client-side `notebook opened` event — emitting here would double-count.
        mock_capture.assert_not_called()

    @patch(CAPTURE_PATH)
    def test_personal_api_key_read_emits_programmatic_event(self, mock_capture):
        short_id = self._create_notebook()

        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="read-key",
            secure_value=hash_key_value(key_value),
            scopes=["notebook:read"],
        )
        self.client.logout()

        response = self.client.get(self._url(short_id), HTTP_AUTHORIZATION=f"Bearer {key_value}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_capture.assert_called_once()
        kwargs = mock_capture.call_args.kwargs
        self.assertEqual(kwargs["short_id"], short_id)
        self.assertEqual(kwargs["read_source"], "mcp")
        self.assertEqual(kwargs["api_key_type"], "PersonalAPIKeyAuthentication")
