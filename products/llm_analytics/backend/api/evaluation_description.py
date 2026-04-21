"""
Django REST API endpoint for generating LLM evaluation descriptions.

This ViewSet provides AI-powered generation of a concise description for an
LLM evaluation based on its current configuration (name, prompt or Hog source,
evaluation type). It can be used both when creating a new evaluation (before
an ID exists) and when updating an existing one.

Endpoints:
- POST /api/environments/:id/llm_analytics/evaluation_description/ - Generate description
"""

import time
from typing import cast

import structlog
from asgiref.sync import async_to_sync
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.permissions import AccessControlPermission
from posthog.rate_limit import (
    LLMAnalyticsSummarizationBurstThrottle,
    LLMAnalyticsSummarizationDailyThrottle,
    LLMAnalyticsSummarizationSustainedThrottle,
)

from products.llm_analytics.backend.api.metrics import llma_track_latency
from products.llm_analytics.backend.summarization.llm.evaluation_description import generate_evaluation_description
from products.llm_analytics.backend.summarization.models import OpenAIModel

logger = structlog.get_logger(__name__)

DESCRIPTION_MAX_LENGTH = 500
# The Evaluation.description field is an unbounded TextField and may legitimately
# exceed the UI cap for legacy or API-set values. Accept a longer hint so
# regeneration requests for those records aren't hard-rejected.
EXISTING_DESCRIPTION_MAX_LENGTH = 20000
PROMPT_MAX_LENGTH = 20000
SOURCE_MAX_LENGTH = 20000


class EvaluationDescriptionRequestSerializer(serializers.Serializer):
    """Request serializer for evaluation description generation.

    Accepts the current (possibly unsaved) evaluation configuration so the
    feature works both for new evaluations and edits-in-progress.
    """

    evaluation_type = serializers.ChoiceField(
        choices=["llm_judge", "hog"],
        required=True,
        help_text="The evaluation type ('llm_judge' or 'hog')",
    )
    name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=400,
        default="",
        help_text="Current evaluation name (optional)",
    )
    prompt = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=PROMPT_MAX_LENGTH,
        default="",
        help_text="Current LLM judge prompt (required when evaluation_type is 'llm_judge')",
    )
    source = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=SOURCE_MAX_LENGTH,
        default="",
        help_text="Current Hog source code (required when evaluation_type is 'hog')",
    )
    allows_na = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether the evaluation allows 'Not applicable' results",
    )
    existing_description = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=EXISTING_DESCRIPTION_MAX_LENGTH,
        default="",
        help_text="The current description, if any, to use as a hint",
    )

    def validate(self, attrs: dict) -> dict:
        evaluation_type = attrs["evaluation_type"]
        prompt = (attrs.get("prompt") or "").strip()
        source = (attrs.get("source") or "").strip()
        name = (attrs.get("name") or "").strip()

        if evaluation_type == "llm_judge" and not prompt and not name:
            raise serializers.ValidationError("Cannot generate description: add a name or a judge prompt first.")
        if evaluation_type == "hog" and not source and not name:
            raise serializers.ValidationError("Cannot generate description: add a name or Hog source code first.")
        return attrs


class EvaluationDescriptionResponseSerializer(serializers.Serializer):
    description = serializers.CharField()


class LLMEvaluationDescriptionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    ViewSet for generating LLM evaluation descriptions.

    Produces a short, human-readable description based on the current
    evaluation configuration. Works for both LLM judge and Hog code evaluations,
    and for both new (unsaved) and existing evaluations.
    """

    scope_object = "llm_analytics"
    permission_classes = [AccessControlPermission]

    def get_throttles(self):
        """Rate limit shared with other LLM-powered endpoints to control costs."""
        return [
            LLMAnalyticsSummarizationBurstThrottle(),
            LLMAnalyticsSummarizationSustainedThrottle(),
            LLMAnalyticsSummarizationDailyThrottle(),
        ]

    def _validate_feature_access(self, request: Request) -> None:
        """Validate that the user is authenticated and AI data processing is approved."""
        if not request.user.is_authenticated:
            raise exceptions.NotAuthenticated()

        if not self.organization.is_ai_data_processing_approved:
            raise exceptions.PermissionDenied(
                "AI data processing must be approved by your organization before using description generation"
            )

    @extend_schema(
        request=EvaluationDescriptionRequestSerializer,
        responses={
            200: EvaluationDescriptionResponseSerializer,
            400: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
            500: OpenApiTypes.OBJECT,
        },
        examples=[
            OpenApiExample(
                "LLM Judge Description Request",
                description="Generate a description for a new LLM judge evaluation",
                value={
                    "evaluation_type": "llm_judge",
                    "name": "Helpfulness Check",
                    "prompt": "Rate true if the assistant's response is helpful, actionable, and directly answers the user's question.",
                    "allows_na": False,
                },
                request_only=True,
            ),
            OpenApiExample(
                "Hog Description Request",
                description="Generate a description for a Hog evaluation",
                value={
                    "evaluation_type": "hog",
                    "name": "Output not empty",
                    "source": "let result := length(output) > 0\nreturn result",
                    "allows_na": False,
                },
                request_only=True,
            ),
            OpenApiExample(
                "Success Response",
                value={
                    "description": "Checks whether the assistant's response directly addresses the user's question."
                },
                response_only=True,
                status_codes=["200"],
            ),
        ],
        description="""
Generate an AI-powered description for an LLM evaluation based on its current configuration.

Works for both LLM judge evaluations (prompt-based) and Hog code evaluations (code-based).
Can be used before the evaluation is saved — no evaluation ID is required.
        """,
        tags=["LLM Analytics"],
    )
    @llma_track_latency("llma_evaluation_description")
    @monitor(feature=None, endpoint="llma_evaluation_description", method="POST")
    def create(self, request: Request, **kwargs) -> Response:
        """
        Generate a description for an evaluation.

        POST /api/environments/:id/llm_analytics/evaluation_description/
        """
        self._validate_feature_access(request)

        serializer = EvaluationDescriptionRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            data = serializer.validated_data
            user = cast(User, self.request.user)
            start_time = time.time()

            generated = async_to_sync(generate_evaluation_description)(
                team_id=self.team_id,
                model=OpenAIModel.GPT_4_1_MINI,
                evaluation_type=data["evaluation_type"],
                evaluation_name=data.get("name", ""),
                evaluation_prompt=data.get("prompt", ""),
                evaluation_source=data.get("source", ""),
                allows_na=data.get("allows_na", False),
                existing_description=data.get("existing_description", ""),
                user_distinct_id=user.distinct_id or "",
            )
            duration_seconds = time.time() - start_time

            result = {"description": generated.description.strip()[:DESCRIPTION_MAX_LENGTH]}

            logger.info(
                "Generated evaluation description",
                team_id=self.team_id,
                evaluation_type=data["evaluation_type"],
                duration_seconds=duration_seconds,
            )

            report_user_action(
                user,
                "llma evaluation description generated",
                {
                    "evaluation_type": data["evaluation_type"],
                    "has_existing_description": bool(data.get("existing_description", "").strip()),
                    "duration_seconds": duration_seconds,
                },
                team=self.team,
                request=self.request,
            )

            return Response(result, status=status.HTTP_200_OK)

        except exceptions.ValidationError:
            raise
        except Exception as e:
            logger.exception(
                "Failed to generate evaluation description",
                team_id=self.team_id,
                error=str(e),
            )
            return Response(
                {
                    "error": "Failed to generate description",
                    "detail": "An error occurred while generating the description",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
