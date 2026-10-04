from typing import Any, cast

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from prometheus_client import Counter
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import InternalAPIUser, ScopedServiceJWTAuthentication

from products.ml_inference.backend.facade.contracts import JsonValue
from products.workflows.backend.facade.api import decide_ai_decision
from products.workflows.backend.facade.contracts import (
    MAX_AI_DECISION_STATE_BYTES,
    AIDecisionAnswered,
    AIDecisionCall,
    AIDecisionFailed,
    AIDecisionFailureReason,
    AIDecisionOutcome,
    AIDecisionQuestion,
    AIDecisionThrottled,
    AIDecisionUnavailable,
)
from products.workflows.backend.facade.enums import AIDecisionAnswerType, AIDecisionErrorCode, AIDecisionStatus
from products.workflows.backend.facade.service_jwt import WORKFLOW_AI_DECISION_PURPOSE
from products.workflows.backend.presentation.views.ai_decision_validation import AIDecisionConfigSerializer

logger = structlog.get_logger(__name__)

AI_DECISION_OUTCOMES = Counter(
    "workflows_ai_decision_outcomes",
    "Workflow AI decision route outcomes, by the code, throttle source, or unavailable cause.",
    ["outcome", "reason"],
)

ERROR_MESSAGES: dict[AIDecisionErrorCode, str] = {
    AIDecisionErrorCode.FEATURE_UNAVAILABLE: "AI decisions aren't available for this organization. Remove the step or contact support.",
    AIDecisionErrorCode.AI_PROCESSING_NOT_APPROVED: "Your organization hasn't approved AI data processing. An organization admin can approve it in organization settings.",
    AIDecisionErrorCode.QUOTA_EXCEEDED: "Your organization is out of AI credits. Add credits in billing settings, then try again.",
    AIDecisionErrorCode.STATE_TOO_LARGE: f"The step's context is larger than {MAX_AI_DECISION_STATE_BYTES // 1024} KB. Remove fields from the context or shorten them.",
    AIDecisionErrorCode.MODEL_REFUSED: "The AI model refused the request. Check the step's question, options, and context.",
    AIDecisionErrorCode.GATEWAY_UNAVAILABLE: "The AI service couldn't take the request. Contact support if this keeps happening.",
}


class WorkflowAIDecisionJWTAuthentication(ScopedServiceJWTAuthentication):
    purpose = WORKFLOW_AI_DECISION_PURPOSE

    # nosemgrep: tuple-return-prefer-dataclass -- DRF's (user, auth) authentication contract
    def _authenticate_claims(self, request: Request, claims: dict[str, Any]) -> tuple[Any, Any]:
        user, _ = super()._authenticate_claims(request, claims)
        # A test run of an unsaved workflow has no workflow id. The id only labels the decision.
        hog_flow_id = claims.get("hog_flow_id")
        return user, str(hog_flow_id) if hog_flow_id else None


class WorkflowAIDecisionRequestSerializer(AIDecisionConfigSerializer):
    invocation_id = serializers.CharField(
        max_length=200, help_text="The workflow invocation asking. Used as the trace id for the decision."
    )
    action_id = serializers.CharField(max_length=200, help_text="The AI decision step asking.")
    state = serializers.DictField(
        child=serializers.JSONField(allow_null=True),
        help_text="The step's rendered context: field names mapped to values. The model reads it as data, never as instructions.",
    )


class AIDecisionErrorSerializer(serializers.Serializer):
    code = serializers.ChoiceField(choices=AIDecisionErrorCode.choices, help_text="Why the decision failed.")
    message = serializers.CharField(help_text="What happened and what to do next, for the run log.")


class WorkflowAIDecisionResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=AIDecisionStatus.choices,
        help_text="succeeded: the model answered. failed: the decision cannot succeed on retry; the step fails.",
    )
    probabilities = serializers.DictField(
        child=serializers.FloatField(),
        required=False,
        help_text="succeeded only: every answer's probability from 0 to 1, keyed by option name, or by yes and no.",
    )
    model = serializers.CharField(required=False, help_text="succeeded only: the model that answered.")
    input_tokens = serializers.IntegerField(required=False, help_text="succeeded only: input tokens the model read.")
    error = AIDecisionErrorSerializer(required=False, help_text="failed only: the failure code and message.")


class WorkflowAIDecisionRetrySerializer(serializers.Serializer):
    detail = serializers.CharField(
        help_text="Why the decision has to wait. A 429 says when to retry in Retry-After; a 503 leaves the wait to the caller's backoff."
    )


class WorkflowAIDecisionViewSet(viewsets.GenericViewSet):
    """Answer a workflow AI decision step with the hosted decision model. Authenticated by a scoped
    service JWT minted by the CDP worker, never by a user credential. Status codes are retry
    instructions: 200 is final, 429 and 503 ask the worker to reschedule."""

    authentication_classes = [WorkflowAIDecisionJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowAIDecisionRequestSerializer

    @extend_schema(
        request=WorkflowAIDecisionRequestSerializer,
        responses={
            200: WorkflowAIDecisionResponseSerializer,
            400: OpenApiResponse(description="The request does not pass the step's config validation."),
            429: OpenApiResponse(
                response=WorkflowAIDecisionRetrySerializer,
                description="Too many decisions right now. Retry after the Retry-After header.",
            ),
            503: OpenApiResponse(
                response=WorkflowAIDecisionRetrySerializer,
                description="The decision model or the admission store is unavailable. Retry with backoff; no Retry-After is sent.",
            ),
        },
        summary="Answer a workflow AI decision",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        team_id = cast(int, cast(InternalAPIUser, request.user).current_team_id)
        serializer = WorkflowAIDecisionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        outcome = decide_ai_decision(_call(team_id, cast(str | None, request.auth), serializer.validated_data))
        return _response(team_id, outcome)


def _call(team_id: int, hog_flow_id: str | None, data: dict[str, Any]) -> AIDecisionCall:
    return AIDecisionCall(
        team_id=team_id,
        hog_flow_id=hog_flow_id,
        action_id=data["action_id"],
        invocation_id=data["invocation_id"],
        question=AIDecisionQuestion(
            answer_type=AIDecisionAnswerType(data["answer_type"]),
            question=data["question"],
            options={option["name"]: option["description"] for option in data["options"]},
            yes_means=data["yes_means"],
            no_means=data["no_means"],
        ),
        state=cast(JsonValue, data["state"]),
    )


def _response(team_id: int, outcome: AIDecisionOutcome) -> Response:
    match outcome:
        case AIDecisionAnswered(probabilities=probabilities, model=model, input_tokens=input_tokens):
            AI_DECISION_OUTCOMES.labels("succeeded", "").inc()
            body = {
                "status": AIDecisionStatus.SUCCEEDED,
                "probabilities": probabilities,
                "model": model,
                "input_tokens": input_tokens,
            }
            return Response(WorkflowAIDecisionResponseSerializer(body).data)
        case AIDecisionFailed(code=code, reason=reason, status_code=status_code):
            AI_DECISION_OUTCOMES.labels("failed", code.value).inc()
            # Causes about one organization or one input repeat for every person a batch run sends, so the
            # counter carries their rate. Causes that fail every decision on this deployment stay visible.
            log = logger.warning if _fails_every_decision(code, reason) else logger.debug
            log("workflow_ai_decision_failed", team_id=team_id, code=code.value, reason=reason, status_code=status_code)
            body = {"status": AIDecisionStatus.FAILED, "error": {"code": code, "message": ERROR_MESSAGES[code]}}
            return Response(WorkflowAIDecisionResponseSerializer(body).data)
        case AIDecisionThrottled(retry_after_seconds=retry_after_seconds, source=source):
            AI_DECISION_OUTCOMES.labels("throttled", source).inc()
            # Debug level because a large batch run can throttle thousands of times; the counter carries the rate.
            logger.debug("workflow_ai_decision_throttled", team_id=team_id, source=source)
            return Response(
                WorkflowAIDecisionRetrySerializer({"detail": "Too many AI decisions right now."}).data,
                status=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(retry_after_seconds)},
            )
        case AIDecisionUnavailable(reason=reason, status_code=status_code):
            AI_DECISION_OUTCOMES.labels("unavailable", reason).inc()
            # Causes before admission (flag, Redis) repeat for every person a batch run sends, so the counter
            # carries their rate. Gateway causes come after admission, so their rate is already bounded.
            log = logger.warning if reason in ("gateway_error", "gateway_unreachable") else logger.debug
            log("workflow_ai_decision_unavailable", team_id=team_id, reason=reason, status_code=status_code)
            return Response(
                WorkflowAIDecisionRetrySerializer({"detail": "The AI decision service is unavailable."}).data,
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


def _fails_every_decision(code: AIDecisionErrorCode, reason: AIDecisionFailureReason | None) -> bool:
    # An answer that does not fit its question is a gateway contract break, not one bad input.
    return code == AIDecisionErrorCode.GATEWAY_UNAVAILABLE or reason in (
        "region_without_decisions",
        "answer_does_not_fit_question",
    )
