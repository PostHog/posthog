"""
Django REST API endpoint for translating LLM trace message content.

Endpoint:
- POST /api/environments/:id/llm_analytics/translate/ - Translate text
"""

import time
from typing import cast

import structlog
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.rate_limit import (
    LLMAnalyticsTranslationBurstThrottle,
    LLMAnalyticsTranslationDailyThrottle,
    LLMAnalyticsTranslationSustainedThrottle,
)

from products.llm_analytics.backend.api.metrics import llma_track_latency
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

    def get_throttles(self):
        return [
            LLMAnalyticsTranslationBurstThrottle(),
            LLMAnalyticsTranslationSustainedThrottle(),
            LLMAnalyticsTranslationDailyThrottle(),
        ]

    def _validate_feature_access(self, request: Request) -> None:
        """Validate that the user is authenticated and AI data processing is approved."""
        if not request.user.is_authenticated:
            raise exceptions.NotAuthenticated()

        if not self.organization.is_ai_data_processing_approved:
            raise exceptions.PermissionDenied(
                "AI data processing must be approved by your organization before using translation"
            )

    @llma_track_latency("llma_translate")
    @monitor(feature=None, endpoint="llma_translate", method="POST")
    def create(self, request: Request, *args, **kwargs) -> Response:
        """Translate text to target language."""
        self._validate_feature_access(request)

        serializer = TranslateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        text = serializer.validated_data["text"]
        target_language = serializer.validated_data.get("target_language", DEFAULT_TARGET_LANGUAGE)

        try:
            logger.info(
                "translation_requested",
                target_language=target_language,
                text_length=len(text),
            )
            start_time = time.time()
            user = cast(User, request.user)
            translation = translate_text(text, target_language, user_distinct_id=user.distinct_id)
            duration_seconds = time.time() - start_time
            logger.info(
                "translation_completed",
                target_language=target_language,
                translation_length=len(translation),
            )

            report_user_action(
                user,
                "llma translation generated",
                {
                    "target_language": target_language,
                    "text_length": len(text),
                    "translation_length": len(translation),
                    "duration_seconds": duration_seconds,
                },
                self.team,
            )

            return Response(
                {
                    "translation": translation,
                    "detected_language": None,
                    "provider": "openai",
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            logger.exception("translation_failed", error=str(e), target_language=target_language)
            raise exceptions.APIException(
                detail="Translation failed due to an internal error.",
                code="translation_error",
            )
