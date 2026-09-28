from typing import Any, cast

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import InternalAPIUser, ScopedServiceJWTAuthentication
from posthog.llm.gateway_client import team_distinct_id
from posthog.llm.system_one import ChoiceAnswer, ChoiceQuestion, SystemOneNotConfigured, SystemOneRequestFailed
from posthog.llm.system_one_client import GATEWAY_MAX_CHOICE_OPTIONS, build_system_one_client
from posthog.models import Team

from products.workflows.backend.service_jwt import WORKFLOW_CLASSIFY_PURPOSE

logger = structlog.get_logger(__name__)

JEV_MODEL = "posthog/hogference/jevk5-fp8-0.2"
# The CDP worker waits inline for the answer, so a slow gateway must not hold its consumer loop for long.
# Keep it below CLASSIFY_TIMEOUT_MS in nodejs/src/cdp/async-functions/classify.ts so the worker receives the 503.
TIMEOUT_SECONDS = 5.0
_QUESTION_ID = "category"


class WorkflowClassifyJWTAuthentication(ScopedServiceJWTAuthentication):
    purpose = WORKFLOW_CLASSIFY_PURPOSE

    # nosemgrep: tuple-return-prefer-dataclass -- DRF's (user, auth) authentication contract
    def _authenticate_claims(self, request: Request, claims: dict[str, Any]) -> tuple[Any, Any]:
        user, _ = super()._authenticate_claims(request, claims)
        hog_flow_id = claims.get("hog_flow_id")
        if not hog_flow_id:
            raise AuthenticationFailed("Service token is missing its workflow claim.")
        return user, str(hog_flow_id)


class WorkflowClassificationRequestSerializer(serializers.Serializer):
    question = serializers.CharField(
        max_length=2000,
        help_text="What to decide about the context, for example 'Which team should handle this ticket?'",
    )
    context = serializers.JSONField(
        help_text="The data to classify, such as ticket fields or event properties. The model reads it as data, never as instructions."
    )
    categories = serializers.DictField(
        child=serializers.CharField(max_length=500, allow_blank=True),
        help_text=f"Category names mapped to a short description of when each applies. 2 to {GATEWAY_MAX_CHOICE_OPTIONS} categories.",
    )

    def validate_categories(self, value: dict[str, str]) -> dict[str, str]:
        if not 2 <= len(value) <= GATEWAY_MAX_CHOICE_OPTIONS:
            raise serializers.ValidationError(f"Enter between 2 and {GATEWAY_MAX_CHOICE_OPTIONS} categories.")
        return value


class WorkflowClassificationResponseSerializer(serializers.Serializer):
    category = serializers.CharField(help_text="The category the model chose.")
    confidence = serializers.FloatField(help_text="The model's probability for the chosen category, from 0 to 1.")
    probabilities = serializers.DictField(
        child=serializers.FloatField(), help_text="The probability of every category, from 0 to 1."
    )


class WorkflowClassificationErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the context was not classified.")


class WorkflowClassificationViewSet(viewsets.GenericViewSet):
    """Classify a workflow's context with Jev for the "Classify with Jev" action. Authenticated by a
    scoped service JWT minted by the plugin server, never by a user credential."""

    authentication_classes = [WorkflowClassifyJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowClassificationRequestSerializer

    @extend_schema(
        request=WorkflowClassificationRequestSerializer,
        responses={
            200: WorkflowClassificationResponseSerializer,
            403: OpenApiResponse(
                response=WorkflowClassificationErrorSerializer,
                description="The organization has not approved AI data processing",
            ),
            501: OpenApiResponse(
                response=WorkflowClassificationErrorSerializer,
                description="This deployment has no AI gateway configured",
            ),
            502: OpenApiResponse(
                response=WorkflowClassificationErrorSerializer, description="The model rejected the request"
            ),
            503: OpenApiResponse(
                response=WorkflowClassificationErrorSerializer,
                description="The model is busy or unreachable. Retry later",
            ),
        },
        summary="Classify workflow context with Jev",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        user = cast(InternalAPIUser, request.user)
        team = Team.objects.select_related("organization").get(id=cast(int, user.current_team_id))

        serializer = WorkflowClassificationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if not team.organization.is_ai_data_processing_approved:
            return _error(
                "Your organization has not approved AI data processing. Approve it in organization settings.",
                status.HTTP_403_FORBIDDEN,
            )

        try:
            client = build_system_one_client(
                model=JEV_MODEL,
                ai_product="workflows",
                distinct_id=team_distinct_id(team.id),
                # The AI usage report charges spend to the team_id label. The distinct ID does not set it.
                properties={"hog_flow_id": cast(str, request.auth), "team_id": str(team.id)},
                timeout=TIMEOUT_SECONDS,
            )
            result = client.decide(
                state=data["context"],
                questions={_QUESTION_ID: ChoiceQuestion(instructions=data["question"], criteria=data["categories"])},
            )
        except SystemOneNotConfigured:
            return _error("Jev is not available on this PostHog deployment.", status.HTTP_501_NOT_IMPLEMENTED)
        except SystemOneRequestFailed as error:
            logger.warning("workflow_classification_failed", team_id=team.id, status_code=error.status_code)
            # A 429 or 529 is load and a missing status is a network error, so the worker retries those.
            if error.status_code in (None, 429, 529):
                return _error("Jev is busy or unreachable. Retry later.", status.HTTP_503_SERVICE_UNAVAILABLE)
            return _error("Jev rejected the request. Check the step inputs.", status.HTTP_502_BAD_GATEWAY)

        answer = cast(ChoiceAnswer, result.answers[_QUESTION_ID])
        return Response(
            WorkflowClassificationResponseSerializer(
                {"category": answer.choice, "confidence": answer.confidence, "probabilities": answer.probabilities}
            ).data
        )


def _error(detail: str, http_status: int) -> Response:
    return Response(WorkflowClassificationErrorSerializer({"detail": detail}).data, status=http_status)
