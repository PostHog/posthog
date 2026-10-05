import json
from typing import Any, cast

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import InternalAPIUser, ScopedServiceJWTAuthentication
from posthog.llm.system_one import ChoiceAnswer, ChoiceQuestion, SystemOneNotConfigured, SystemOneRequestFailed
from posthog.models import Team

from products.workflows.backend.facade.service_jwt import WORKFLOW_AI_DECISION_PURPOSE

logger = structlog.get_logger(__name__)

JEV_MODEL = "posthog/hogference/jevk5-fp8-0.2"
# The CDP worker waits inline for the answer, so a slow gateway must not hold its consumer loop for long.
# Keep it below AI_DECISION_TIMEOUT_MS in nodejs/src/cdp/async-functions/ai-decision.ts so the worker receives the 503.
TIMEOUT_SECONDS = 5.0
_QUESTION_ID = "decision"
# The gateway's GATEWAY_MAX_CHOICE_OPTIONS, copied because its module must stay out of Django startup.
MAX_OPTIONS = 16
# Keep it equal to MAX_CONTEXT_CHARS in nodejs/src/cdp/async-functions/ai-decision.ts.
MAX_CONTEXT_CHARS = 65_536


class WorkflowAiDecisionJWTAuthentication(ScopedServiceJWTAuthentication):
    purpose = WORKFLOW_AI_DECISION_PURPOSE

    # nosemgrep: tuple-return-prefer-dataclass -- DRF's (user, auth) authentication contract
    def _authenticate_claims(self, request: Request, claims: dict[str, Any]) -> tuple[Any, Any]:
        user, _ = super()._authenticate_claims(request, claims)
        hog_flow_id = claims.get("hog_flow_id")
        if not hog_flow_id:
            raise AuthenticationFailed("Service token is missing its workflow claim.")
        return user, str(hog_flow_id)


class WorkflowAiDecisionRequestSerializer(serializers.Serializer):
    question = serializers.CharField(
        max_length=2000,
        help_text="What to decide about the context, for example 'Which team should handle this ticket?'",
    )
    context = serializers.JSONField(
        help_text=f"The data to decide on, such as ticket fields or event properties. The model reads it as data, never as instructions. At most {MAX_CONTEXT_CHARS} characters of JSON."
    )
    options = serializers.DictField(
        child=serializers.CharField(max_length=500, allow_blank=True),
        help_text=f"Option names mapped to a short description of when each applies. 2 to {MAX_OPTIONS} options.",
    )

    def validate_context(self, value: Any) -> Any:
        if len(json.dumps(value, ensure_ascii=False, separators=(",", ":"))) > MAX_CONTEXT_CHARS:
            raise serializers.ValidationError(f"Keep the context to {MAX_CONTEXT_CHARS} characters of JSON or fewer.")
        return value

    def validate_options(self, value: dict[str, str]) -> dict[str, str]:
        if not 2 <= len(value) <= MAX_OPTIONS:
            raise serializers.ValidationError(f"Enter between 2 and {MAX_OPTIONS} options.")
        return value


class WorkflowAiDecisionResponseSerializer(serializers.Serializer):
    decision = serializers.CharField(help_text="The option the model chose.")
    confidence = serializers.FloatField(help_text="The model's probability for the chosen option, from 0 to 1.")


class WorkflowAiDecisionErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the model did not decide.")


class WorkflowAiDecisionViewSet(viewsets.GenericViewSet):
    """Ask Jev to pick one option for the "AI decision" workflow action. Authenticated by a
    scoped service JWT minted by the plugin server, never by a user credential."""

    authentication_classes = [WorkflowAiDecisionJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowAiDecisionRequestSerializer

    @extend_schema(
        request=WorkflowAiDecisionRequestSerializer,
        responses={
            200: WorkflowAiDecisionResponseSerializer,
            403: OpenApiResponse(
                response=WorkflowAiDecisionErrorSerializer,
                description="The organization has not approved AI data processing",
            ),
            501: OpenApiResponse(
                response=WorkflowAiDecisionErrorSerializer,
                description="This deployment has no AI gateway configured",
            ),
            422: OpenApiResponse(
                response=WorkflowAiDecisionErrorSerializer, description="The model rejected the request"
            ),
            503: OpenApiResponse(
                response=WorkflowAiDecisionErrorSerializer,
                description="The model is busy or unreachable. Retry later",
            ),
        },
        summary="Decide on workflow context with Jev",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        user = cast(InternalAPIUser, request.user)
        team = Team.objects.select_related("organization").get(id=cast(int, user.current_team_id))

        serializer = WorkflowAiDecisionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if not team.organization.is_ai_data_processing_approved:
            return _error(
                "Your organization has not approved AI data processing. Approve it in organization settings.",
                status.HTTP_403_FORBIDDEN,
            )

        # The client module pulls the LLM SDKs, which must stay out of Django startup.
        from posthog.llm.system_one_client import build_system_one_client  # noqa: PLC0415

        try:
            client = build_system_one_client(
                model=JEV_MODEL,
                ai_product="workflows",
                team_id=team.id,
                properties={"hog_flow_id": cast(str, request.auth)},
                timeout=TIMEOUT_SECONDS,
            )
            result = client.decide(
                state=data["context"],
                questions={_QUESTION_ID: ChoiceQuestion(instructions=data["question"], criteria=data["options"])},
            )
        except SystemOneNotConfigured:
            return _error("Jev is not available on this PostHog deployment.", status.HTTP_501_NOT_IMPLEMENTED)
        except SystemOneRequestFailed as error:
            logger.warning("workflow_ai_decision_failed", team_id=team.id, status_code=error.status_code)
            # A 429 or 5xx is load or an outage and a missing status is a network error, so the worker retries
            # those. The worker also retries 502, so a rejection gets 422 to fail the step without a retry.
            if error.status_code is None or error.status_code == 429 or error.status_code >= 500:
                return _error("Jev is busy or unreachable. Retry later.", status.HTTP_503_SERVICE_UNAVAILABLE)
            return _error("Jev rejected the request. Check the step inputs.", status.HTTP_422_UNPROCESSABLE_ENTITY)

        answer = cast(ChoiceAnswer, result.answers[_QUESTION_ID])
        return Response(
            WorkflowAiDecisionResponseSerializer({"decision": answer.choice, "confidence": answer.confidence}).data
        )


def _error(detail: str, http_status: int) -> Response:
    return Response(WorkflowAiDecisionErrorSerializer({"detail": detail}).data, status=http_status)
