from typing import Any, cast

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import InternalAPIUser, ScopedServiceJWTAuthentication
from posthog.models import Team

from products.ml_inference.backend.facade.contracts import MAX_OPTIONS_PER_QUESTION, JsonValue
from products.workflows.backend.facade.enums import AIDecisionAnswerType, AIDecisionErrorCode, AIDecisionStatus
from products.workflows.backend.facade.service_jwt import WORKFLOW_AI_DECISION_PURPOSE
from products.workflows.backend.services.ai_decision import (
    AIDecisionCall,
    AIDecisionOutcome,
    AIDecisionQuestion,
    Decided,
    Failed,
    Throttled,
    Unavailable,
    decide,
)

logger = structlog.get_logger(__name__)

MIN_OPTIONS = 2
MAX_CONTEXT_FIELD_NAME_LENGTH = 100

# The step's only templated input. Fixed here rather than read from a template, so no saved config can
# turn the question or the options into templates that render person or event data as instructions.
AI_DECISION_INPUTS_SCHEMA: list[dict[str, Any]] = [
    {"key": "context", "type": "dictionary", "label": "Context", "required": True, "templating": "hog"}
]

ERROR_MESSAGES: dict[AIDecisionErrorCode, str] = {
    AIDecisionErrorCode.FEATURE_UNAVAILABLE: "AI decisions aren't available for this organization. Remove the step or contact support.",
    AIDecisionErrorCode.AI_PROCESSING_NOT_APPROVED: "Your organization hasn't approved AI data processing. An organization admin can approve it in organization settings.",
    AIDecisionErrorCode.QUOTA_EXCEEDED: "Your organization is out of AI credits. Add credits in billing settings, then try again.",
    AIDecisionErrorCode.STATE_TOO_LARGE: "The step's context is larger than 8 KB. Remove fields from the context or shorten them.",
    AIDecisionErrorCode.MODEL_REFUSED: "The AI model refused the request. Check the step's question, options, and context.",
    AIDecisionErrorCode.GATEWAY_UNAVAILABLE: "The AI service isn't set up on this PostHog deployment.",
}


class WorkflowAIDecisionJWTAuthentication(ScopedServiceJWTAuthentication):
    purpose = WORKFLOW_AI_DECISION_PURPOSE


class AIDecisionOptionSerializer(serializers.Serializer):
    name = serializers.CharField(
        max_length=500, help_text="The answer's name. It labels the step's output for this answer."
    )
    description = serializers.CharField(
        max_length=500,
        allow_blank=True,
        default="",
        help_text="When this answer applies, in plain words. The model reads it to choose between options.",
    )


class AIDecisionConfigSerializer(serializers.Serializer):
    """The question an AI decision step asks. A workflow save and the decide route validate it alike,
    so a step that saves never fails at run time on its own config."""

    question = serializers.CharField(
        max_length=2000,
        help_text="The question the model answers, in plain words. Never templated: person and event data go in the context.",
    )
    answer_type = serializers.ChoiceField(
        choices=AIDecisionAnswerType.choices,
        default=AIDecisionAnswerType.YES_NO,
        help_text="yes_no: the step has a Yes and a No output. pick_one: the step has one output per option.",
    )
    options = serializers.ListField(
        child=AIDecisionOptionSerializer(),
        required=False,
        default=list,
        help_text=f"pick_one only: {MIN_OPTIONS} to {MAX_OPTIONS_PER_QUESTION} options with unique names, in output order.",
    )
    yes_means = serializers.CharField(
        max_length=500,
        allow_blank=True,
        default="",
        help_text="yes_no only: what a yes means, to help the model judge.",
    )
    no_means = serializers.CharField(
        max_length=500,
        allow_blank=True,
        default="",
        help_text="yes_no only: what a no means, to help the model judge.",
    )
    yes_threshold = serializers.IntegerField(
        min_value=1,
        max_value=99,
        default=50,
        help_text="yes_no only: answer yes when the probability of yes is at or above this percent.",
    )
    unsure_enabled = serializers.BooleanField(
        default=False,
        help_text="Adds an Unsure output after the answer outputs, for answers the model is not sure about.",
    )
    min_pick_probability = serializers.IntegerField(
        min_value=1,
        max_value=99,
        default=60,
        help_text="pick_one with unsure_enabled: answer Unsure when the top option's probability is below this percent.",
    )
    no_threshold = serializers.IntegerField(
        min_value=1,
        max_value=98,
        default=20,
        help_text="yes_no with unsure_enabled: answer no at or below this percent. Must be below yes_threshold.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["answer_type"] == AIDecisionAnswerType.PICK_ONE:
            names = [option["name"] for option in attrs["options"]]
            if not MIN_OPTIONS <= len(names) <= MAX_OPTIONS_PER_QUESTION:
                raise serializers.ValidationError(
                    {"options": f"Enter between {MIN_OPTIONS} and {MAX_OPTIONS_PER_QUESTION} options."}
                )
            if len(set(names)) != len(names):
                raise serializers.ValidationError({"options": "Give each option a different name."})
        elif attrs["unsure_enabled"] and attrs["no_threshold"] >= attrs["yes_threshold"]:
            raise serializers.ValidationError({"no_threshold": "Set the no threshold below the yes threshold."})
        return attrs


def ai_decision_context_error(inputs: Any) -> str | None:
    context_input = inputs.get("context") if isinstance(inputs, dict) else None
    context = context_input.get("value") if isinstance(context_input, dict) else None
    if not isinstance(context, dict) or not context:
        return "Add at least one field for the model to read."
    if any(not name.strip() or len(name) > MAX_CONTEXT_FIELD_NAME_LENGTH for name in context):
        return f"Give each context field a name of 1 to {MAX_CONTEXT_FIELD_NAME_LENGTH} characters."
    return None


class WorkflowAIDecisionRequestSerializer(AIDecisionConfigSerializer):
    invocation_id = serializers.CharField(
        max_length=200, help_text="The workflow invocation asking. Used as the trace id for the decision."
    )
    action_id = serializers.CharField(max_length=200, help_text="The AI decision step asking.")
    state = serializers.DictField(
        child=serializers.JSONField(),
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
    detail = serializers.CharField(help_text="Why the decision has to wait. Retry after the Retry-After header.")


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
            429: OpenApiResponse(
                response=WorkflowAIDecisionRetrySerializer,
                description="Too many decisions right now. Retry after the Retry-After header.",
            ),
            503: OpenApiResponse(
                response=WorkflowAIDecisionRetrySerializer,
                description="The decision model or the admission store is unavailable. Retry later.",
            ),
        },
        summary="Answer a workflow AI decision",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        user = cast(InternalAPIUser, request.user)
        team = Team.objects.select_related("organization").get(id=cast(int, user.current_team_id))
        serializer = WorkflowAIDecisionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        claims = cast(dict[str, Any], request.auth)
        outcome = decide(_call(team, claims.get("hog_flow_id"), serializer.validated_data))
        return _response(team.id, outcome)


def _call(team: Team, hog_flow_id: Any, data: dict[str, Any]) -> AIDecisionCall:
    return AIDecisionCall(
        team=team,
        hog_flow_id=str(hog_flow_id) if hog_flow_id else None,
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
        case Decided(probabilities=probabilities, model=model, input_tokens=input_tokens):
            body = {
                "status": AIDecisionStatus.SUCCEEDED,
                "probabilities": probabilities,
                "model": model,
                "input_tokens": input_tokens,
            }
            return Response(WorkflowAIDecisionResponseSerializer(body).data)
        case Failed(code=code):
            logger.info("workflow_ai_decision_failed", team_id=team_id, code=code.value)
            body = {"status": AIDecisionStatus.FAILED, "error": {"code": code, "message": ERROR_MESSAGES[code]}}
            return Response(WorkflowAIDecisionResponseSerializer(body).data)
        case Throttled(retry_after_seconds=retry_after_seconds):
            logger.info("workflow_ai_decision_throttled", team_id=team_id, retry_after=retry_after_seconds)
            return Response(
                WorkflowAIDecisionRetrySerializer({"detail": "Too many AI decisions right now."}).data,
                status=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(retry_after_seconds)},
            )
        case Unavailable():
            logger.warning("workflow_ai_decision_unavailable", team_id=team_id)
            return Response(
                WorkflowAIDecisionRetrySerializer({"detail": "The AI decision service is unavailable."}).data,
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
