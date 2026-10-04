import json
from typing import cast

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

import structlog
import posthoganalytics
from redis.exceptions import RedisError

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import GatewayNotConfiguredError
from posthog.models import Team
from posthog.redis import get_client
from posthog.token_bucket import BucketUnavailable, Budget, consume

from products.ml_inference.backend.facade import api as decision_api
from products.ml_inference.backend.facade.contracts import (
    ChoiceAnswer,
    DecisionGatewayError,
    DecisionGatewayUnreachableError,
    DecisionQuestion,
    DecisionRequest,
    DecisionResult,
    DecisionsDisabledError,
    JsonValue,
    NoulAnswer,
)
from products.ml_inference.backend.facade.enums import DecisionQuestionType
from products.workflows.backend.facade.enums import AIDecisionAnswerType, AIDecisionErrorCode

logger = structlog.get_logger(__name__)

AI_DECISION_FEATURE_FLAG = "workflows-ai-decision"
MAX_STATE_BYTES = 8192
GATEWAY_TIMEOUT_SECONDS = 5
GATEWAY_BUSY_RETRY_AFTER_SECONDS = 5
_QUESTION_ID = "answer"
_ADMISSION_KEY = "workflows:ai_decision:admission"
_REDIS_TIMEOUT_SECONDS = 0.1


@frozen
class AIDecisionQuestion:
    answer_type: AIDecisionAnswerType
    question: str
    options: dict[str, str]
    yes_means: str
    no_means: str


@frozen
class AIDecisionCall:
    team: Team
    hog_flow_id: str | None
    action_id: str
    invocation_id: str
    question: AIDecisionQuestion
    state: JsonValue


@frozen
class Decided:
    probabilities: dict[str, float]
    model: str
    input_tokens: int


@frozen
class Failed:
    code: AIDecisionErrorCode


@frozen
class Throttled:
    retry_after_seconds: int


@frozen
class Unavailable:
    pass


AIDecisionOutcome = Decided | Failed | Throttled | Unavailable


def ai_decision_enabled(team: Team) -> bool:
    # Evaluated locally because every workflow save and every decision reads it, and a remote
    # evaluation would add a network call to each of them.
    if settings.DEBUG:
        return True
    organization_id = str(team.organization_id)
    try:
        return bool(
            posthoganalytics.feature_enabled(
                AI_DECISION_FEATURE_FLAG,
                str(team.uuid),
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.warning("workflow_ai_decision_flag_check_failed", team_id=team.id, exc_info=True)
        return False


def state_size_bytes(state: JsonValue) -> int:
    return len(json.dumps(state, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def decide(call: AIDecisionCall) -> AIDecisionOutcome:
    team = call.team
    if not ai_decision_enabled(team):
        return Failed(code=AIDecisionErrorCode.FEATURE_UNAVAILABLE)
    if not team.organization.is_ai_data_processing_approved:
        return Failed(code=AIDecisionErrorCode.AI_PROCESSING_NOT_APPROVED)
    if _is_over_ai_credit_budget(team):
        return Failed(code=AIDecisionErrorCode.QUOTA_EXCEEDED)
    if state_size_bytes(call.state) > MAX_STATE_BYTES:
        return Failed(code=AIDecisionErrorCode.STATE_TOO_LARGE)
    admission = _admit(team.id)
    if admission is not None:
        return admission
    return _ask_the_model(call)


def _is_over_ai_credit_budget(team: Team) -> bool:
    from ee.billing.quota_limiting import (  # noqa: PLC0415 — keeps the billing query stack off the API import path
        is_team_over_ai_credit_budget,
    )

    try:
        return is_team_over_ai_credit_budget(team.api_token)
    except Exception:
        # A team that is really out of credits still gets a 402 from the gateway, so a cache outage fails open.
        logger.warning("workflow_ai_decision_credit_lookup_failed", team_id=team.id, exc_info=True)
        return False


def _admit(team_id: int) -> Throttled | Unavailable | None:
    team_budget = Budget(
        burst=settings.WORKFLOWS_AI_DECISION_TEAM_BURST, per_hour=settings.WORKFLOWS_AI_DECISION_TEAM_PER_HOUR
    )
    global_budget = Budget(
        burst=settings.WORKFLOWS_AI_DECISION_GLOBAL_BURST, per_hour=settings.WORKFLOWS_AI_DECISION_GLOBAL_PER_HOUR
    )
    try:
        client = get_client(socket_timeout=_REDIS_TIMEOUT_SECONDS, socket_connect_timeout=_REDIS_TIMEOUT_SECONDS)
    except (RedisError, ImproperlyConfigured):
        return Unavailable()
    for key, budget in ((f"{_ADMISSION_KEY}:team:{team_id}", team_budget), (_ADMISSION_KEY, global_budget)):
        decision = consume(key, budget, client=client)
        if isinstance(decision, BucketUnavailable):
            return Unavailable()
        if not decision.allowed:
            return Throttled(retry_after_seconds=max(1, decision.retry_after))
    return None


def _ask_the_model(call: AIDecisionCall) -> AIDecisionOutcome:
    properties = {"action_id": call.action_id}
    if call.hog_flow_id:
        properties["hog_flow_id"] = call.hog_flow_id
    request = DecisionRequest(
        team_id=call.team.id,
        state=call.state,
        questions={_QUESTION_ID: _decision_question(call.question)},
        ai_product="workflows",
        trace_id=call.invocation_id,
        properties=properties,
        privacy_mode=True,
    )
    try:
        result = decision_api.decide_when_available(request, timeout_seconds=GATEWAY_TIMEOUT_SECONDS)
    except DecisionsDisabledError:
        return Failed(code=AIDecisionErrorCode.FEATURE_UNAVAILABLE)
    except GatewayNotConfiguredError:
        return Failed(code=AIDecisionErrorCode.GATEWAY_UNAVAILABLE)
    except DecisionGatewayUnreachableError:
        return Unavailable()
    except DecisionGatewayError as error:
        return _gateway_error_outcome(error.status_code)
    return Decided(
        probabilities=_probabilities(result),
        model=result.model,
        input_tokens=result.input_tokens,
    )


def _decision_question(question: AIDecisionQuestion) -> DecisionQuestion:
    if question.answer_type == AIDecisionAnswerType.YES_NO:
        criteria = {"true": question.yes_means, "false": question.no_means}
        return DecisionQuestion(
            type=DecisionQuestionType.NOUL,
            instructions=question.question,
            criteria={key: value for key, value in criteria.items() if value} or None,
        )
    return DecisionQuestion(type=DecisionQuestionType.CHOICE, instructions=question.question, criteria=question.options)


def _gateway_error_outcome(status_code: int) -> AIDecisionOutcome:
    if status_code == 429:
        return Throttled(retry_after_seconds=GATEWAY_BUSY_RETRY_AFTER_SECONDS)
    if status_code == 402:
        return Failed(code=AIDecisionErrorCode.QUOTA_EXCEEDED)
    if status_code in (400, 413, 422):
        return Failed(code=AIDecisionErrorCode.MODEL_REFUSED)
    return Unavailable()


def _probabilities(result: DecisionResult) -> dict[str, float]:
    # The facade already rejects an answer whose type does not match its question.
    answer = result.answers[_QUESTION_ID]
    if isinstance(answer, NoulAnswer):
        return {"yes": answer.probability, "no": 1 - answer.probability}
    return cast(ChoiceAnswer, answer).probabilities
