"""
Django REST API endpoint for translating LLM trace message content.

Endpoint:
- POST /api/environments/:id/llm_analytics/translate/ - Translate text
"""

from django.conf import settings

import structlog
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.llm_analytics.backend.translation.constants import DEFAULT_TARGET_LANGUAGE
from products.llm_analytics.backend.translation.llm import translate_text

logger = structlog.get_logger(__name__)


class TranslateRequestSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=10000, help_text="The text to translate")
    target_language = serializers.CharField(
        max_length=10,
        default=DEFAULT_TARGET_LANGUAGE,
        required=False,
        help_text="Target language code (default: 'en' for English)",
    )


class TranslateResponseSerializer(serializers.Serializer):
    translation = serializers.CharField(help_text="The translated text")
    detected_language = serializers.CharField(
        required=False, allow_null=True, help_text="Detected source language (if available)"
    )
    provider = serializers.CharField(help_text="Translation provider used")


class LLMAnalyticsTranslateViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """ViewSet for translating LLM trace message content."""

    scope_object = "llm_analytics"  # type: ignore[assignment]

    def create(self, request: Request, *args, **kwargs) -> Response:
        """Translate text to target language."""
        serializer = TranslateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        text = serializer.validated_data["text"]
        target_language = serializer.validated_data.get("target_language", DEFAULT_TARGET_LANGUAGE)

        if not getattr(settings, "OPENAI_API_KEY", None):
            raise exceptions.APIException(
                detail="Translation service is not configured. OPENAI_API_KEY is required.",
                code="translation_not_configured",
            )

        try:
            translation = translate_text(text, target_language)
            return Response(
                {
                    "translation": translation,
                    "detected_language": None,
                    "provider": "openai",
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            logger.exception("Translation failed", error=str(e))
            raise exceptions.APIException(
                detail=f"Translation failed: {e!s}",
                code="translation_error",
            )
