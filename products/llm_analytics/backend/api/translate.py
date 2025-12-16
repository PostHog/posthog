"""
Django REST API endpoint for translating LLM trace message content.

Endpoint:
- POST /api/environments/:id/llm_analytics/translate/ - Translate text
"""

from typing import cast

from django.conf import settings

import structlog
import posthoganalytics
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.rate_limit import (
    LLMAnalyticsTranslationBurstThrottle,
    LLMAnalyticsTranslationDailyThrottle,
    LLMAnalyticsTranslationSustainedThrottle,
)

from products.llm_analytics.backend.translation.constants import (
    DEFAULT_TARGET_LANGUAGE,
    EARLY_ADOPTERS_FEATURE_FLAG,
    LLM_ANALYTICS_TRANSLATION,
)
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
        """Validate that the user has access to the translation feature."""
        if not request.user.is_authenticated:
            raise exceptions.NotAuthenticated()

        if settings.DEBUG:
            return

        user = cast(User, request.user)
        distinct_id = str(user.distinct_id)
        organization_id = str(self.team.organization_id)

        person_properties = {"email": user.email}
        groups = {"organization": organization_id}
        group_properties = {"organization": {"id": organization_id}}

        if not (
            posthoganalytics.feature_enabled(
                LLM_ANALYTICS_TRANSLATION,
                distinct_id,
                person_properties=person_properties,
                groups=groups,
                group_properties=group_properties,
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
            or posthoganalytics.feature_enabled(
                EARLY_ADOPTERS_FEATURE_FLAG,
                distinct_id,
                person_properties=person_properties,
                groups=groups,
                group_properties=group_properties,
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        ):
            raise exceptions.PermissionDenied("LLM trace translation is not enabled for this user")

        if not self.organization.is_ai_data_processing_approved:
            raise exceptions.PermissionDenied(
                "AI data processing must be approved by your organization before using translation"
            )

    def create(self, request: Request, *args, **kwargs) -> Response:
        """Translate text to target language."""
        self._validate_feature_access(request)

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
            logger.info(
                "translation_requested",
                target_language=target_language,
                text_length=len(text),
            )
            translation = translate_text(text, target_language)
            logger.info(
                "translation_completed",
                target_language=target_language,
                translation_length=len(translation),
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
