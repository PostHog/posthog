import json

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

import structlog
import posthoganalytics
from redis.exceptions import RedisError

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import GatewayNotConfiguredError
from posthog.models import Team
from posthog.redis import get_client
from posthog.token_bucket import BucketDecision, BucketUnavailable, Budget, consume, refund

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
    # A cause for logs only, never a state value or a gateway body.
    reason: str


AIDecisionOutcome = Decided | Failed | Throttled | Unavailable


def ai_decision_enabled(team: Team) -> bool:
    """For saves: a flag evaluation error hides the step rather than exposing it."""
    try:
        return _flag_enabled(team)
    except Exception:
        logger.warning("workflow_ai_decision_flag_check_failed", team_id=team.id, exc_info=True)
        return False


def _flag_enabled(team: Team) -> bool:
    # Evaluated locally because every workflow save and every decision reads it, and a remote
    # evaluation would add a network call to each of them.
    if settings.DEBUG:
        return True
    organization_id = str(team.organization_id)
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


def state_size_bytes(state: JsonValue) -> int:
    # surrogatepass counts a lone surrogate, such as half of an emoji cut by a template, instead of raising.
    return len(json.dumps(state, separators=(",", ":"), ensure_ascii=False).encode("utf-8", "surrogatepass"))


def decide(call: AIDecisionCall) -> AIDecisionOutcome:
    team = call.team
    try:
        enabled = _flag_enabled(team)
    except Exception:
        # A decision that fails here is final for the person, so an evaluation error asks for a retry instead.
        logger.warning("workflow_ai_decision_flag_check_failed", team_id=team.id, exc_info=True)
        return Unavailable(reason="flag_check_failed")
    if not enabled:
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
    team_key = f"{_ADMISSION_KEY}:team:{team_id}"
    team_budget = Budget(
        burst=settings.WORKFLOWS_AI_DECISION_TEAM_BURST, per_hour=settings.WORKFLOWS_AI_DECISION_TEAM_PER_HOUR
    )
    global_budget = Budget(
        burst=settings.WORKFLOWS_AI_DECISION_GLOBAL_BURST, per_hour=settings.WORKFLOWS_AI_DECISION_GLOBAL_PER_HOUR
    )
    try:
        client = get_client(socket_timeout=_REDIS_TIMEOUT_SECONDS, socket_connect_timeout=_REDIS_TIMEOUT_SECONDS)
    except (RedisError, ImproperlyConfigured):
        return Unavailable(reason="redis_unavailable")
    team_decision = consume(team_key, team_budget, client=client)
    if isinstance(team_decision, BucketUnavailable):
        return Unavailable(reason="redis_unavailable")
    if not team_decision.allowed:
        return Throttled(retry_after_seconds=max(1, team_decision.retry_after))
    global_decision = consume(_ADMISSION_KEY, global_budget, client=client)
    if isinstance(global_decision, BucketDecision) and global_decision.allowed:
        return None
    # No decision ran, so the team keeps its token for the retry.
    refund(team_key, team_budget)
    if isinstance(global_decision, BucketUnavailable):
        return Unavailable(reason="redis_unavailable")
    return Throttled(retry_after_seconds=max(1, global_decision.retry_after))


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
        return Unavailable(reason="gateway_unreachable")
    except DecisionGatewayError as error:
        return _gateway_error_outcome(error.status_code)
    probabilities = _probabilities(result, call.question)
    if probabilities is None:
        return Failed(code=AIDecisionErrorCode.MODEL_REFUSED)
    return Decided(probabilities=probabilities, model=result.model, input_tokens=result.input_tokens)


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
    if status_code >= 500:
        return Unavailable(reason=f"gateway_{status_code}")
    if status_code == 402:
        return Failed(code=AIDecisionErrorCode.QUOTA_EXCEEDED)
    # 200 is an answer the facade could not read. The model ran, so a retry would pay for the same failure again.
    if status_code in (200, 400, 413, 422):
        return Failed(code=AIDecisionErrorCode.MODEL_REFUSED)
    # Any other 4xx means the gateway credential or route is wrong for every decision, which a retry cannot fix.
    return Failed(code=AIDecisionErrorCode.GATEWAY_UNAVAILABLE)


def _probabilities(result: DecisionResult, question: AIDecisionQuestion) -> dict[str, float] | None:
    """Every answer's probability, or None when the answer does not fit the question it was asked."""
    answer = result.answers[_QUESTION_ID]
    if isinstance(answer, NoulAnswer):
        probabilities = {"yes": answer.probability, "no": 1 - answer.probability}
    elif isinstance(answer, ChoiceAnswer) and set(answer.probabilities) == set(question.options):
        probabilities = answer.probabilities
    else:
        return None
    return probabilities if all(0 <= value <= 1 for value in probabilities.values()) else None
