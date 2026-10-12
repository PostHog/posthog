import json
import math
from typing import Any, cast

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import InternalAPIUser, ScopedServiceJWTAuthentication
from posthog.cdp.flag_gated_templates import gated_template_enabled
from posthog.models import Team

from products.ml_inference.backend.facade.contracts import (
    DEFAULT_DECISION_MODEL,
    MAX_OPTIONS_PER_QUESTION,
    ChoiceAnswer,
    DecisionGatewayError,
    DecisionGatewayUnreachableError,
    DecisionQuestion,
    DecisionRequest,
    DecisionsDisabledError,
)
from products.ml_inference.backend.facade.enums import DecisionQuestionType
from products.workflows.backend.facade.service_jwt import WORKFLOW_CLASSIFY_PURPOSE

logger = structlog.get_logger(__name__)

# The CDP worker waits inline for the answer, so a slow gateway must not hold its consumer loop for long.
# Keep it below CLASSIFY_TIMEOUT_MS in nodejs/src/cdp/async-functions/classify.ts so the worker receives the 503.
TIMEOUT_SECONDS = 5.0
_QUESTION_ID = "category"
MAX_CATEGORIES = MAX_OPTIONS_PER_QUESTION
MAX_CATEGORY_NAME_LENGTH = 100
# Same state limit as the ml_inference decide API, which asks the same model.
# Keep it equal to MAX_CONTEXT_CHARS in nodejs/src/cdp/async-functions/classify.ts.
MAX_CONTEXT_CHARS = 65_536
# DecisionRequest validation fails on JSON nested about 255 levels deep, and its error text repeats the
# whole context into logs and exception reporting. A small payload can reach that depth, so cap it first.
# Keep it equal to MAX_CONTEXT_DEPTH in nodejs/src/cdp/async-functions/classify.ts.
MAX_CONTEXT_DEPTH = 100
# The models an author can pick for the step, keyed by the value the step stores. A new entry needs the AI gateway
# to route the model on /v1/systemone, and the vendor's data processing must be covered for customer context.
CLASSIFICATION_MODELS: dict[str, str] = {"jev": DEFAULT_DECISION_MODEL}
DEFAULT_CLASSIFICATION_MODEL = "jev"


def _nesting_exceeds(value: Any, limit: int) -> bool:
    pending: list[tuple[Any, int]] = [(value, 1)]
    while pending:
        item, depth = pending.pop()
        if isinstance(item, dict):
            children = list(item.values())
        elif isinstance(item, list):
            children = item
        else:
            continue
        if depth > limit:
            return True
        pending.extend((child, depth + 1) for child in children)
    return False


class WorkflowClassifyJWTAuthentication(ScopedServiceJWTAuthentication):
    purpose = WORKFLOW_CLASSIFY_PURPOSE

    def _authenticate_claims(self, request: Request, claims: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        if not claims.get("hog_flow_id"):
            raise AuthenticationFailed("Service token is missing its workflow claim.")
        return super()._authenticate_claims(request, claims)


class WorkflowClassificationRequestSerializer(serializers.Serializer):
    question = serializers.CharField(
        max_length=2000,
        help_text="What to decide about the context, for example 'Which team should handle this ticket?'",
    )
    context = serializers.JSONField(  # type: ignore[assignment]  # The field name shadows DRF Field.context.
        help_text=f"The data to classify, such as ticket fields or event properties. The model reads it as data, never as instructions. At most {MAX_CONTEXT_CHARS} characters of JSON and {MAX_CONTEXT_DEPTH} levels of nesting."
    )
    model = serializers.ChoiceField(
        choices=list(CLASSIFICATION_MODELS),
        default=DEFAULT_CLASSIFICATION_MODEL,
        allow_null=True,
        help_text="The model that picks the category. Defaults to Jev.",
    )
    categories = serializers.DictField(
        child=serializers.CharField(max_length=500, allow_blank=True),
        help_text=f"Category names of at most {MAX_CATEGORY_NAME_LENGTH} characters mapped to a short description of when each applies. 2 to {MAX_CATEGORIES} categories.",
    )

    def validate_context(self, value: Any) -> Any:
        if _nesting_exceeds(value, MAX_CONTEXT_DEPTH):
            raise serializers.ValidationError(f"Keep the context to {MAX_CONTEXT_DEPTH} levels of nesting or fewer.")
        if len(json.dumps(value, ensure_ascii=False, separators=(",", ":"))) > MAX_CONTEXT_CHARS:
            raise serializers.ValidationError(f"Keep the context to {MAX_CONTEXT_CHARS} characters of JSON or fewer.")
        return value

    def validate_categories(self, value: dict[str, str]) -> dict[str, str]:
        if not 2 <= len(value) <= MAX_CATEGORIES:
            raise serializers.ValidationError(f"Enter between 2 and {MAX_CATEGORIES} categories.")
        if any(not name.strip() for name in value):
            raise serializers.ValidationError("Give every category a name.")
        if any(len(name) > MAX_CATEGORY_NAME_LENGTH for name in value):
            raise serializers.ValidationError(f"Keep category names to {MAX_CATEGORY_NAME_LENGTH} characters or fewer.")
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
    """Classify a workflow's context with an AI model for the "Classify with AI" action. Authenticated by a
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
                description="The feature is disabled or the organization has not approved AI data processing",
            ),
            501: OpenApiResponse(
                response=WorkflowClassificationErrorSerializer,
                description="This deployment has no AI gateway configured",
            ),
            422: OpenApiResponse(
                response=WorkflowClassificationErrorSerializer,
                description="The model rejected the request or returned an unusable answer",
            ),
            503: OpenApiResponse(
                response=WorkflowClassificationErrorSerializer,
                description="The model is busy or unreachable. Retry later",
            ),
        },
        summary="Classify workflow context with an AI model",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        user = cast(InternalAPIUser, request.user)
        team = Team.objects.select_related("organization").get(id=cast(int, user.current_team_id))

        if not gated_template_enabled("workflow-classify-action", team):
            return _error("Classify with AI is not enabled for this project.", status.HTTP_403_FORBIDDEN)

        serializer = WorkflowClassificationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if not team.organization.is_ai_data_processing_approved:
            return _error(
                "Your organization has not approved AI data processing. Approve it in organization settings.",
                status.HTTP_403_FORBIDDEN,
            )

        # The facade pulls the LLM SDKs through the gateway client, which must stay out of Django startup.
        from posthog.llm.gateway_client import GatewayNotConfiguredError  # noqa: PLC0415

        from products.ml_inference.backend.facade import api as decisions_api  # noqa: PLC0415

        categories: dict[str, str] = data["categories"]
        try:
            result = decisions_api.decide_when_available(
                DecisionRequest(
                    team_id=team.id,
                    state=data["context"],
                    questions={
                        _QUESTION_ID: DecisionQuestion(
                            type=DecisionQuestionType.CHOICE, instructions=data["question"], criteria=categories
                        )
                    },
                    model=CLASSIFICATION_MODELS[data["model"] or DEFAULT_CLASSIFICATION_MODEL],
                    ai_product="workflows",
                    properties={"hog_flow_id": str(cast(dict[str, Any], request.auth)["hog_flow_id"])},
                    # The context carries person and event data, which must stay out of the internal AI observability project.
                    privacy_mode=True,
                ),
                timeout_seconds=TIMEOUT_SECONDS,
            )
        except (DecisionsDisabledError, GatewayNotConfiguredError):
            return _error("The model is not available on this PostHog deployment.", status.HTTP_501_NOT_IMPLEMENTED)
        except DecisionGatewayUnreachableError:
            logger.warning("workflow_classification_unreachable", team_id=team.id)
            return _error("The model is busy or unreachable. Retry later.", status.HTTP_503_SERVICE_UNAVAILABLE)
        except DecisionGatewayError as error:
            # Only the status is logged: the gateway's body can echo the context.
            logger.warning("workflow_classification_failed", team_id=team.id, status_code=error.status_code)
            if error.status_code == 429 or error.status_code >= 500:
                return _error("The model is busy or unreachable. Retry later.", status.HTTP_503_SERVICE_UNAVAILABLE)
            if error.status_code == 200:
                return _error(
                    "The model returned an answer the step cannot read.", status.HTTP_422_UNPROCESSABLE_ENTITY
                )
            return _error(
                f"The model refused the request (gateway status {error.status_code}).",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        answer = result.answers.get(_QUESTION_ID)
        if not _is_usable(answer, categories):
            logger.warning("workflow_classification_unusable_answer", team_id=team.id)
            return _error("The model returned an answer the step cannot read.", status.HTTP_422_UNPROCESSABLE_ENTITY)
        answer = cast(ChoiceAnswer, answer)
        return Response(
            WorkflowClassificationResponseSerializer(
                {
                    "category": answer.choice,
                    "confidence": answer.confidence,
                    "probabilities": {name: answer.probabilities[name] for name in categories},
                }
            ).data
        )


def _is_usable(answer: object, categories: dict[str, str]) -> bool:
    """The facade checks the answer's shape but not its values. A choice outside the categories
    would send the person down no branch."""
    if not isinstance(answer, ChoiceAnswer) or answer.choice not in categories:
        return False
    if not all(name in answer.probabilities for name in categories):
        return False
    values = [answer.confidence, *(answer.probabilities[name] for name in categories)]
    return all(math.isfinite(value) and 0 <= value <= 1 for value in values)


def _error(detail: str, http_status: int) -> Response:
    return Response(WorkflowClassificationErrorSerializer({"detail": detail}).data, status=http_status)
