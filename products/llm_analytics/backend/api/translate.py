"""
Django REST API endpoint for translating LLM trace message content.

This ViewSet provides translation of message text content using LLM.

Endpoint:
- POST /api/environments/:id/llm_analytics/translate/ - Translate text to English
"""

from django.conf import settings

import structlog
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

logger = structlog.get_logger(__name__)


class TranslateRequestSerializer(serializers.Serializer):
    text = serializers.CharField(
        max_length=10000,
        help_text="The text to translate",
    )
    target_language = serializers.CharField(
        max_length=10,
        default="en",
        required=False,
        help_text="Target language code (default: 'en' for English)",
    )


class TranslateResponseSerializer(serializers.Serializer):
    translation = serializers.CharField(help_text="The translated text")
    detected_language = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Detected source language (if available)",
    )
    provider = serializers.CharField(help_text="Translation provider used")


class LLMAnalyticsTranslateViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    ViewSet for translating LLM trace message content.

    Provides translation of text content using OpenAI's GPT model.
    """

    def create(self, request: Request, *args, **kwargs) -> Response:
        """
        Translate text to target language.

        POST /api/environments/:id/llm_analytics/translate/
        """
        serializer = TranslateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        text = serializer.validated_data["text"]
        target_language = serializer.validated_data.get("target_language", "en")

        # Check if OpenAI is configured
        if not getattr(settings, "OPENAI_API_KEY", None):
            raise exceptions.APIException(
                detail="Translation service is not configured. OPENAI_API_KEY is required.",
                code="translation_not_configured",
            )

        try:
            translation = self._translate_with_openai(text, target_language)
            response_data = {
                "translation": translation,
                "detected_language": None,
                "provider": "openai",
            }
            return Response(response_data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.exception("Translation failed", error=str(e))
            raise exceptions.APIException(
                detail=f"Translation failed: {str(e)}",
                code="translation_error",
            )

    def _translate_with_openai(self, text: str, target_language: str) -> str:
        """
        Translate text using OpenAI's GPT model.
        """
        import openai

        client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)

        language_names = {
            "en": "English",
            "es": "Spanish",
            "fr": "French",
            "de": "German",
            "pt": "Portuguese",
            "zh": "Chinese",
            "ja": "Japanese",
            "ko": "Korean",
            "it": "Italian",
            "nl": "Dutch",
            "ru": "Russian",
            "ar": "Arabic",
        }
        target_name = language_names.get(target_language, target_language)

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": f"You are a translator. Translate the following text to {target_name}. "
                    "Only return the translation, nothing else. Preserve formatting and line breaks.",
                },
                {"role": "user", "content": text},
            ],
            temperature=0.3,
            max_tokens=min(len(text) * 3, 4000),  # Allow room for expansion, cap at 4k
        )

        content = response.choices[0].message.content
        return content.strip() if content else ""
