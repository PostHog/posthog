"""Tests for translation API endpoint."""

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from rest_framework import status

from products.llm_analytics.backend.translation.constants import (
    DEFAULT_TARGET_LANGUAGE,
    SUPPORTED_LANGUAGES,
    TRANSLATION_MODEL,
)

MOCK_PATH = "products.llm_analytics.backend.translation.llm.get_llm_client"


class TestTranslateAPI(APIBaseTest):
    def test_unauthenticated_user_cannot_access_translation(self):
        self.client.logout()
        response = self.client.post(f"/api/environments/{self.team.id}/llm_analytics/translate")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @patch(MOCK_PATH)
    def test_successful_translation(self, mock_get_client):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Hola mundo"))]
        mock_get_client.return_value.chat.completions.create.return_value = mock_response

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/translate",
            {"text": "Hello world", "target_language": "es"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["translation"] == "Hola mundo"
        assert response.data["provider"] == "openai"

    @patch(MOCK_PATH)
    def test_translation_uses_correct_model(self, mock_get_client):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Translated"))]
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/translate",
            {"text": "Test", "target_language": "fr"},
            format="json",
        )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == TRANSLATION_MODEL

    @patch(MOCK_PATH)
    def test_translation_uses_default_language_when_not_specified(self, mock_get_client):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Translated"))]
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/translate",
            {"text": "Bonjour le monde"},
            format="json",
        )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        target_name = SUPPORTED_LANGUAGES.get(DEFAULT_TARGET_LANGUAGE, DEFAULT_TARGET_LANGUAGE)
        assert target_name in call_kwargs["messages"][0]["content"]

    @patch(MOCK_PATH)
    def test_translation_fails_when_gateway_not_configured(self, mock_get_client):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        mock_get_client.side_effect = ValueError("LLM_GATEWAY_URL and LLM_GATEWAY_API_KEY must be configured")

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/translate",
            {"text": "Hello world", "target_language": "es"},
            format="json",
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_translation_validates_text_max_length(self):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        long_text = "a" * 10001

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/translate",
            {"text": long_text, "target_language": "es"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["attr"] == "text"

    def test_translation_requires_text(self):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/translate",
            {"target_language": "es"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["attr"] == "text"

    @patch(MOCK_PATH)
    def test_translation_handles_llm_error(self, mock_get_client):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        mock_get_client.return_value.chat.completions.create.side_effect = Exception("API error")

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/translate",
            {"text": "Hello world", "target_language": "es"},
            format="json",
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.data["detail"] == "Translation failed due to an internal error."

    @patch(MOCK_PATH)
    def test_translation_preserves_formatting(self, mock_get_client):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Translated"))]
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/translate",
            {"text": "Line 1\nLine 2", "target_language": "es"},
            format="json",
        )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        system_content = call_kwargs["messages"][0]["content"]
        assert "Preserve formatting" in system_content

    @patch(MOCK_PATH)
    def test_translation_handles_empty_response(self, mock_get_client):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=None))]
        mock_get_client.return_value.chat.completions.create.return_value = mock_response

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/translate",
            {"text": "Hello", "target_language": "es"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["translation"] == ""

    def test_translation_denied_when_ai_consent_not_approved(self):
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/translate",
            {"text": "Hello world", "target_language": "es"},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "AI data processing must be approved" in response.data["detail"]

    @patch(MOCK_PATH)
    def test_translation_allowed_when_ai_consent_approved(self, mock_get_client):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Hola mundo"))]
        mock_get_client.return_value.chat.completions.create.return_value = mock_response

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/translate",
            {"text": "Hello world", "target_language": "es"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK

    @patch(MOCK_PATH)
    def test_translation_passes_user_distinct_id(self, mock_get_client):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Translated"))]
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/translate",
            {"text": "Test", "target_language": "es"},
            format="json",
        )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["user"] == self.user.distinct_id
