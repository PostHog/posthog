"""Tests for translation API endpoint."""

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from rest_framework import status

from products.llm_analytics.backend.translation.constants import (
    DEFAULT_TARGET_LANGUAGE,
    SUPPORTED_LANGUAGES,
    TRANSLATION_MODEL,
)


class TestTranslateAPI(APIBaseTest):
    def test_unauthenticated_user_cannot_access_translation(self):
        self.client.logout()
        response = self.client.post(f"/api/environments/{self.team.id}/llm_analytics/translate")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @patch("products.llm_analytics.backend.api.translate.settings")
    @patch("openai.OpenAI")
    def test_successful_translation(self, mock_openai_class, mock_settings):
        mock_settings.OPENAI_API_KEY = "test-key"
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Hola mundo"))]
        mock_openai_class.return_value.chat.completions.create.return_value = mock_response

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/translate",
            {"text": "Hello world", "target_language": "es"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["translation"] == "Hola mundo"
        assert response.data["provider"] == "openai"

    @patch("products.llm_analytics.backend.api.translate.settings")
    @patch("openai.OpenAI")
    def test_translation_uses_correct_model(self, mock_openai_class, mock_settings):
        mock_settings.OPENAI_API_KEY = "test-key"
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Translated"))]
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/translate",
            {"text": "Test", "target_language": "fr"},
            format="json",
        )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == TRANSLATION_MODEL

    @patch("products.llm_analytics.backend.api.translate.settings")
    @patch("openai.OpenAI")
    def test_translation_uses_default_language_when_not_specified(self, mock_openai_class, mock_settings):
        mock_settings.OPENAI_API_KEY = "test-key"
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Translated"))]
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/translate",
            {"text": "Bonjour le monde"},
            format="json",
        )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        target_name = SUPPORTED_LANGUAGES.get(DEFAULT_TARGET_LANGUAGE, DEFAULT_TARGET_LANGUAGE)
        assert target_name in call_kwargs["messages"][0]["content"]

    @patch("products.llm_analytics.backend.api.translate.settings")
    def test_translation_fails_without_openai_key(self, mock_settings):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        mock_settings.OPENAI_API_KEY = None

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/translate",
            {"text": "Hello world", "target_language": "es"},
            format="json",
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "not configured" in response.data["detail"]

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

    @patch("products.llm_analytics.backend.api.translate.settings")
    @patch("openai.OpenAI")
    def test_translation_handles_openai_error(self, mock_openai_class, mock_settings):
        mock_settings.OPENAI_API_KEY = "test-key"
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        mock_openai_class.return_value.chat.completions.create.side_effect = Exception("API error")

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/translate",
            {"text": "Hello world", "target_language": "es"},
            format="json",
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.data["detail"] == "Translation failed due to an internal error."

    @patch("products.llm_analytics.backend.api.translate.settings")
    @patch("openai.OpenAI")
    def test_translation_preserves_formatting(self, mock_openai_class, mock_settings):
        mock_settings.OPENAI_API_KEY = "test-key"
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Translated"))]
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/translate",
            {"text": "Line 1\nLine 2", "target_language": "es"},
            format="json",
        )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        system_content = call_kwargs["messages"][0]["content"]
        assert "Preserve formatting" in system_content

    @patch("products.llm_analytics.backend.api.translate.settings")
    @patch("openai.OpenAI")
    def test_translation_handles_empty_response(self, mock_openai_class, mock_settings):
        mock_settings.OPENAI_API_KEY = "test-key"
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=None))]
        mock_openai_class.return_value.chat.completions.create.return_value = mock_response

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

    @patch("openai.OpenAI")
    @patch("products.llm_analytics.backend.api.translate.settings")
    def test_translation_allowed_when_ai_consent_approved(self, mock_settings, mock_openai_class):
        mock_settings.OPENAI_API_KEY = "test-key"
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Hola mundo"))]
        mock_openai_class.return_value.chat.completions.create.return_value = mock_response

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/translate",
            {"text": "Hello world", "target_language": "es"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
