import json
import math
import random

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

import structlog
import posthoganalytics

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
from products.workflows.backend.facade.contracts import (
    MAX_AI_DECISION_STATE_BYTES,
    AIDecisionAnswered,
    AIDecisionCall,
    AIDecisionFailed,
    AIDecisionOutcome,
    AIDecisionQuestion,
    AIDecisionThrottled,
    AIDecisionUnavailable,
)
from products.workflows.backend.facade.enums import AIDecisionAnswerType, AIDecisionErrorCode

logger = structlog.get_logger(__name__)

AI_DECISION_FEATURE_FLAG = "workflows-ai-decision"
GATEWAY_TIMEOUT_SECONDS = 5
GATEWAY_BUSY_RETRY_AFTER_SECONDS = 5
_QUESTION_ID = "answer"
_ADMISSION_KEY = "workflows:ai_decision:admission"
_REDIS_TIMEOUT_SECONDS = 0.1


def _flag_state(team: Team) -> bool | None:
    """None when the flag cannot be evaluated, for example before the flag definitions load."""
    # Evaluated locally because every workflow save and every decision reads it, and a remote
    # evaluation would add a network call to each of them.
    if settings.DEBUG:
        return True
    organization_id = str(team.organization_id)
    try:
        enabled = posthoganalytics.feature_enabled(
            AI_DECISION_FEATURE_FLAG,
            str(team.uuid),
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception:
        logger.warning("workflow_ai_decision_flag_check_failed", team_id=team.id, exc_info=True)
        return None
    return None if enabled is None else bool(enabled)


def ai_decision_enabled(team_id: int) -> bool:
    """For saves: a flag that cannot be evaluated hides the step rather than exposing it."""
    team = Team.objects.only("id", "uuid", "organization_id").get(id=team_id)
    return _flag_state(team) is True


def _without_lone_surrogates(state: JsonValue) -> JsonValue:
    """A template can cut an emoji in half. The gateway client cannot encode the lone surrogate that
    remains, so it becomes U+FFFD."""
    text = json.dumps(state, ensure_ascii=False)
    return json.loads(text.encode("utf-16", "surrogatepass").decode("utf-16", "replace"))


def _state_size_bytes(state: JsonValue) -> int:
    return len(json.dumps(state, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _is_over_ai_credit_budget(team: Team) -> bool:
    try:
        # Inside the try because posthog-foss ships without ee, and it keeps the billing query stack off the API import path.
        from ee.billing.quota_limiting import is_team_over_ai_credit_budget  # noqa: PLC0415

        return is_team_over_ai_credit_budget(team.api_token)
    except Exception:
        # A team that is really out of credits still gets a 402 from the gateway, so a failed lookup fails open.
        logger.warning("workflow_ai_decision_credit_lookup_failed", team_id=team.id, exc_info=True)
        return False


def _spread_retry(decision: BucketDecision, budget: Budget) -> int:
    """The bucket names the wait for its next token, which is the same for every waiting caller. A batch
    run would then retry all at once, so the wait spreads over the time a full burst takes to refill."""
    earliest = max(1, decision.retry_after)
    return random.randint(earliest, max(earliest, math.ceil(budget.burst / budget.refill_per_second)))


def _admit(team_id: int) -> AIDecisionThrottled | AIDecisionUnavailable | None:
    team_key = f"{_ADMISSION_KEY}:team:{team_id}"
    team_budget = Budget(
        burst=settings.WORKFLOWS_AI_DECISION_TEAM_BURST, per_hour=settings.WORKFLOWS_AI_DECISION_TEAM_PER_HOUR
    )
    global_budget = Budget(
        burst=settings.WORKFLOWS_AI_DECISION_GLOBAL_BURST, per_hour=settings.WORKFLOWS_AI_DECISION_GLOBAL_PER_HOUR
    )
    try:
        client = get_client(socket_timeout=_REDIS_TIMEOUT_SECONDS, socket_connect_timeout=_REDIS_TIMEOUT_SECONDS)
    except ImproperlyConfigured:
        return AIDecisionUnavailable(reason="redis_unavailable")
    team_decision = consume(team_key, team_budget, client=client)
    if isinstance(team_decision, BucketUnavailable):
        return AIDecisionUnavailable(reason="redis_unavailable")
    if not team_decision.allowed:
        return AIDecisionThrottled(retry_after_seconds=_spread_retry(team_decision, team_budget), source="team")
    global_decision = consume(_ADMISSION_KEY, global_budget, client=client)
    if isinstance(global_decision, BucketUnavailable):
        # No refund against a store that just failed.
        return AIDecisionUnavailable(reason="redis_unavailable")
    if not global_decision.allowed:
        # No decision ran, so the team keeps its token for the retry.
        refund(team_key, team_budget, client=client)
        return AIDecisionThrottled(retry_after_seconds=_spread_retry(global_decision, global_budget), source="global")
    return None


def _decision_question(question: AIDecisionQuestion) -> DecisionQuestion:
    if question.answer_type == AIDecisionAnswerType.YES_NO:
        criteria = {"true": question.yes_means, "false": question.no_means}
        return DecisionQuestion(
            type=DecisionQuestionType.NOUL,
            instructions=question.question,
            criteria={key: value for key, value in criteria.items() if value} or None,
        )
    return DecisionQuestion(type=DecisionQuestionType.CHOICE, instructions=question.question, criteria=question.options)


def _decision_request(call: AIDecisionCall, state: JsonValue) -> DecisionRequest:
    properties = {"action_id": call.action_id}
    if call.hog_flow_id:
        properties["hog_flow_id"] = call.hog_flow_id
    return DecisionRequest(
        team_id=call.team_id,
        state=state,
        questions={_QUESTION_ID: _decision_question(call.question)},
        ai_product="workflows",
        trace_id=call.invocation_id,
        properties=properties,
        privacy_mode=True,
    )


def _gateway_error_outcome(status_code: int) -> AIDecisionOutcome:
    if status_code == 429:
        # The gateway's own Retry-After does not reach this code, so the wait spreads to keep a batch apart.
        retry_after = random.randint(GATEWAY_BUSY_RETRY_AFTER_SECONDS, 2 * GATEWAY_BUSY_RETRY_AFTER_SECONDS)
        return AIDecisionThrottled(retry_after_seconds=retry_after, source="gateway")
    if status_code >= 500:
        return AIDecisionUnavailable(reason="gateway_error", status_code=status_code)
    if status_code == 402:
        return AIDecisionFailed(
            code=AIDecisionErrorCode.QUOTA_EXCEEDED, reason="gateway_status", status_code=status_code
        )
    # 200 is an answer the facade could not read. The model ran, so a retry would pay for the same failure again.
    if status_code == 200:
        return AIDecisionFailed(
            code=AIDecisionErrorCode.MODEL_REFUSED, reason="unreadable_answer", status_code=status_code
        )
    if status_code in (400, 413, 422):
        return AIDecisionFailed(
            code=AIDecisionErrorCode.MODEL_REFUSED, reason="gateway_status", status_code=status_code
        )
    # Any other 4xx means the gateway credential or route is wrong for every decision, which a retry cannot fix.
    return AIDecisionFailed(
        code=AIDecisionErrorCode.GATEWAY_UNAVAILABLE, reason="gateway_status", status_code=status_code
    )


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


def _ask_the_model(request: DecisionRequest, question: AIDecisionQuestion) -> AIDecisionOutcome:
    try:
        result = decision_api.decide_when_available(request, timeout_seconds=GATEWAY_TIMEOUT_SECONDS)
    except DecisionsDisabledError:
        return AIDecisionFailed(code=AIDecisionErrorCode.FEATURE_UNAVAILABLE, reason="region_without_decisions")
    except GatewayNotConfiguredError:
        return AIDecisionFailed(code=AIDecisionErrorCode.GATEWAY_UNAVAILABLE, reason="gateway_not_configured")
    except DecisionGatewayUnreachableError:
        return AIDecisionUnavailable(reason="gateway_unreachable")
    except DecisionGatewayError as error:
        return _gateway_error_outcome(error.status_code)
    probabilities = _probabilities(result, question)
    if probabilities is None:
        return AIDecisionFailed(code=AIDecisionErrorCode.MODEL_REFUSED, reason="answer_does_not_fit_question")
    return AIDecisionAnswered(probabilities=probabilities, model=result.model, input_tokens=result.input_tokens)


def decide(call: AIDecisionCall) -> AIDecisionOutcome:
    team = Team.objects.select_related("organization").get(id=call.team_id)
    enabled = _flag_state(team)
    if enabled is None:
        # A failed decision is final for the person, so a flag that cannot be evaluated asks for a retry.
        return AIDecisionUnavailable(reason="flag_undetermined")
    if not enabled:
        return AIDecisionFailed(code=AIDecisionErrorCode.FEATURE_UNAVAILABLE)
    if not team.organization.is_ai_data_processing_approved:
        return AIDecisionFailed(code=AIDecisionErrorCode.AI_PROCESSING_NOT_APPROVED)
    if _is_over_ai_credit_budget(team):
        return AIDecisionFailed(code=AIDecisionErrorCode.QUOTA_EXCEEDED)
    state = _without_lone_surrogates(call.state)
    if _state_size_bytes(state) > MAX_AI_DECISION_STATE_BYTES:
        return AIDecisionFailed(code=AIDecisionErrorCode.STATE_TOO_LARGE)
    try:
        request = _decision_request(call, state)
    except ValueError:
        # The contract rejects a state it cannot read, such as nesting deeper than its validator follows.
        # The error text quotes the state, so only the cause is kept.
        return AIDecisionFailed(code=AIDecisionErrorCode.MODEL_REFUSED, reason="unreadable_state")
    admission = _admit(team.id)
    if admission is not None:
        return admission
    return _ask_the_model(request, call.question)
