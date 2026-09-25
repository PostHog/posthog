"""
DRF views for ml_inference.

Validate JSON via serializers, call facade methods, return serialized responses. No business logic here.
"""

from typing import Any

import structlog
from drf_spectacular.utils import OpenApiResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.llm.gateway_client import GatewayNotConfiguredError
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle

from ..facade import api, contracts
from ..facade.contracts import DecisionGatewayError, DecisionGatewayUnreachableError, DecisionsDisabledError
from ..facade.enums import DecisionQuestionType
from .serializers import (
    DecideRequestSerializer,
    DecideResponseSerializer,
    SearchIntentRequestSerializer,
    SearchIntentResponseSerializer,
)

logger = structlog.get_logger(__name__)


class DecisionGatewayUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "The decision model is not available right now. Try again in a moment."
    default_code = "decision_gateway_unavailable"


class DecisionGatewayRefused(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "The decision model could not answer this request."
    default_code = "decision_gateway_refused"


class DecisionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    serializer_class = DecideRequestSerializer
    throttle_classes = [AIBurstRateThrottle, AISustainedRateThrottle]

    @validated_request(
        request_serializer=DecideRequestSerializer,
        responses={
            200: OpenApiResponse(response=DecideResponseSerializer, description="One answer per question."),
            404: OpenApiResponse(description="Decisions are not enabled for this project."),
            502: OpenApiResponse(description="The decision model refused the request."),
            503: OpenApiResponse(description="No decision model is configured."),
        },
        summary="Ask the decision model",
        description="Ask the decision model typed questions about one piece of text and get a calibrated probability per question.",
    )
    @action(detail=False, methods=["POST"])
    def decide(self, request: Request, **kwargs: Any) -> Response:
        data = request.validated_data
        questions = {
            question_id: contracts.DecisionQuestion(
                type=DecisionQuestionType(question["type"]),
                instructions=question["instructions"],
                criteria=question.get("criteria") or None,
            )
            for question_id, question in data["questions"].items()
        }
        decision = contracts.DecisionRequest(
            team_id=self.team_id, state=data["state"], questions=questions, model=data["model"]
        )
        try:
            result = api.decide(decision)
        except DecisionsDisabledError as error:
            raise NotFound() from error
        except (GatewayNotConfiguredError, DecisionGatewayUnreachableError) as error:
            logger.warning("ml_inference_decision_gateway_unavailable", team_id=self.team_id, reason=str(error))
            raise DecisionGatewayUnavailable() from error
        except DecisionGatewayError as error:
            # Only the status is logged: the gateway's body can echo the state text, and the gateway logs its own refusals.
            logger.warning("ml_inference_decision_gateway_refused", team_id=self.team_id, status_code=error.status_code)
            raise DecisionGatewayRefused() from error
        return Response(DecideResponseSerializer(_wire_result(result)).data)


# One search box sends one request per pause in typing, so these rates are far above the AI throttles and
# are separate from them: a person who filters a lot must not lose their PostHog AI budget.
class SearchIntentBurstThrottle(UserRateThrottle):
    scope = "ml_inference_search_intent_burst"
    rate = "120/minute"


class SearchIntentSustainedThrottle(UserRateThrottle):
    scope = "ml_inference_search_intent_sustained"
    rate = "3000/day"


class SearchIntentViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    serializer_class = SearchIntentRequestSerializer
    throttle_classes = [SearchIntentBurstThrottle, SearchIntentSustainedThrottle]

    @validated_request(
        request_serializer=SearchIntentRequestSerializer,
        responses={
            200: OpenApiResponse(response=SearchIntentResponseSerializer, description="The most likely tab."),
            404: OpenApiResponse(description="Decisions are not enabled for this project."),
            503: OpenApiResponse(description="The decision model did not answer in time."),
        },
        summary="Classify a filter picker search",
        description="Guess which filter picker tab a search belongs to, so the picker can suggest or promote it.",
    )
    @action(detail=False, methods=["POST"])
    def classify(self, request: Request, **kwargs: Any) -> Response:
        data = request.validated_data
        search = contracts.SearchIntentRequest(
            team_id=self.team_id,
            query=data["query"],
            active_group_type=data["active_group_type"],
            available_group_types=tuple(data["available_group_types"]),
            scene=data.get("scene"),
        )
        try:
            intent = api.classify_search_intent(search)
        except DecisionsDisabledError as error:
            raise NotFound() from error
        except (GatewayNotConfiguredError, DecisionGatewayUnreachableError, DecisionGatewayError) as error:
            # The picker works without an answer, so every model failure is the same "not now" to the caller.
            logger.warning("ml_inference_search_intent_unavailable", team_id=self.team_id, reason=type(error).__name__)
            raise DecisionGatewayUnavailable() from error
        return Response(
            SearchIntentResponseSerializer(
                {
                    "group_type": intent.group_type,
                    "confidence": intent.confidence,
                    "is_confident": intent.is_confident,
                    "suggests_switch": intent.suggests_switch,
                    "method": intent.source,
                    "prompt_version": intent.prompt_version,
                }
            ).data
        )


def _wire_result(result: contracts.DecisionResult) -> dict[str, Any]:
    answers: dict[str, dict[str, Any]] = {}
    for question_id, answer in result.answers.items():
        wire: dict[str, Any] = {
            "probability": None,
            "choice": None,
            "score": None,
            "confidence": None,
            "probabilities": None,
        }
        match answer:
            case contracts.NoulAnswer(probability=probability):
                wire.update(type=DecisionQuestionType.NOUL, probability=probability)
            case contracts.ChoiceAnswer(choice=choice, confidence=confidence, probabilities=probabilities):
                wire.update(
                    type=DecisionQuestionType.CHOICE, choice=choice, confidence=confidence, probabilities=probabilities
                )
            case contracts.ScoreAnswer(score=score, confidence=confidence, probabilities=probabilities):
                wire.update(
                    type=DecisionQuestionType.SCORE, score=score, confidence=confidence, probabilities=probabilities
                )
        answers[question_id] = wire
    return {
        "model": result.model,
        "answers": answers,
        "input_tokens": result.input_tokens,
        "latency_ms": result.latency_ms,
    }
