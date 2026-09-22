from typing import Any
from urllib.parse import urlparse, urlunparse

from django.conf import settings

import httpx
import structlog
import posthoganalytics

from posthog.llm.gateway_client import (
    GatewayNotConfiguredError,
    ai_gateway_headers,
    resolve_ai_gateway_config,
    team_distinct_id,
)
from posthog.models import Team

from ..facade.contracts import (
    ChoiceAnswer,
    DecisionAnswer,
    DecisionGatewayError,
    DecisionGatewayUnreachableError,
    DecisionQuestion,
    DecisionRequest,
    DecisionResult,
    NoulAnswer,
    ScoreAnswer,
)
from ..facade.enums import DecisionQuestionType

logger = structlog.get_logger(__name__)

DECISIONS_FEATURE_FLAG = "ml-inference-decisions"
DECISION_PATH = "/v1/systemone"
DEFAULT_TIMEOUT_SECONDS = 30.0


def decisions_available_here() -> bool:
    """Dark launch: local development and the US cloud only, so no flag or setting can bring it up in the EU."""
    return bool(settings.DEBUG) or (settings.CLOUD_DEPLOYMENT or "").upper() == "US"


def decisions_enabled(team_id: int) -> bool:
    """DEBUG bypasses the flag: the analytics SDK is disabled in local dev, where the surface has to be exercisable."""
    if not decisions_available_here():
        return False
    if settings.DEBUG:
        return True
    try:
        team = Team.objects.only("uuid", "organization_id").get(id=team_id)
        return bool(
            posthoganalytics.feature_enabled(
                DECISIONS_FEATURE_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id)},
                group_properties={"organization": {"id": str(team.organization_id)}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception("ml_inference_decisions_flag_check_failed", team_id=team_id)
        return False


def decision_url(gateway_url: str) -> str:
    """The gateway URL setting carries the OpenAI base path; the decision route hangs off the origin."""
    parsed = urlparse(gateway_url)
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[: -len("/v1")]
    return urlunparse(parsed._replace(path=path + DECISION_PATH, params="", query="", fragment=""))


def carries_credentials_safely(gateway_url: str) -> bool:
    """The bearer only travels in clear to a loopback gateway, which is the local development setup."""
    parsed = urlparse(gateway_url)
    return parsed.scheme == "https" or parsed.hostname in {"localhost", "127.0.0.1", "::1"}


def decide(
    request: DecisionRequest,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    transport: httpx.BaseTransport | None = None,
) -> DecisionResult:
    config = resolve_ai_gateway_config()
    if config is None:
        raise GatewayNotConfiguredError("AI_GATEWAY_URL and AI_GATEWAY_API_KEY must be configured")
    if not carries_credentials_safely(config.url):
        raise GatewayNotConfiguredError("AI_GATEWAY_URL must use https unless it points at this machine")
    headers = {"Authorization": f"Bearer {config.api_key}"}
    headers.update(ai_gateway_headers(ai_product="ml_inference", distinct_id=team_distinct_id(request.team_id)) or {})
    try:
        with httpx.Client(trust_env=False, timeout=timeout_seconds, transport=transport) as client:
            response = client.post(decision_url(config.url), json=_wire_body(request), headers=headers)
    except httpx.RequestError as error:
        raise DecisionGatewayUnreachableError(f"decision gateway unreachable: {error.__class__.__name__}") from error
    if response.status_code != 200:
        raise DecisionGatewayError(response.status_code, response.text[:500])
    try:
        payload = response.json()
    except ValueError as error:
        raise DecisionGatewayError(200, "decision response is not JSON") from error
    return parse_result(payload, request.questions)


def _wire_body(request: DecisionRequest) -> dict[str, Any]:
    questions: dict[str, dict[str, Any]] = {}
    for question_id, question in request.questions.items():
        wire: dict[str, Any] = {"type": question.type.value, "instructions": question.instructions}
        if question.criteria:
            wire["criteria"] = question.criteria
        questions[question_id] = wire
    return {"model": request.model, "state": request.state, "questions": questions}


def parse_result(payload: Any, questions: dict[str, DecisionQuestion]) -> DecisionResult:
    """A 200 that is not a decision is a contract break, not an empty decision, so it fails like a refusal."""
    if not isinstance(payload, dict):
        raise DecisionGatewayError(200, "decision response is not a JSON object")
    answers = payload.get("answers")
    usage = payload.get("usage")
    model = payload.get("model")
    if not isinstance(answers, dict) or not isinstance(usage, dict) or not isinstance(model, str) or not model:
        raise DecisionGatewayError(200, f"decision response is missing model, answers, or usage: {sorted(payload)}")
    input_tokens = usage.get("input_tokens")
    if not isinstance(input_tokens, int):
        raise DecisionGatewayError(200, "decision response usage has no input_tokens")
    if set(answers) != set(questions):
        raise DecisionGatewayError(
            200, f"decision response answers {sorted(answers)} do not match the questions {sorted(questions)}"
        )
    try:
        parsed = {
            question_id: _parse_answer(answer, questions[question_id].type) for question_id, answer in answers.items()
        }
        return DecisionResult(
            model=model, answers=parsed, input_tokens=input_tokens, latency_ms=payload.get("latency_ms")
        )
    except (ValueError, TypeError, KeyError) as error:
        raise DecisionGatewayError(200, f"decision response has an unreadable answer: {error}") from error


def _parse_answer(answer: Any, question_type: DecisionQuestionType) -> DecisionAnswer:
    if not isinstance(answer, dict):
        raise ValueError(f"answer is not an object: {answer!r}")
    variants = {variant.value for variant in DecisionQuestionType} & set(answer)
    if variants != {question_type.value}:
        raise ValueError(f"answer to a {question_type.value} question carries {sorted(variants) or 'no variant'}")
    match question_type:
        case DecisionQuestionType.NOUL:
            return NoulAnswer(probability=answer["noul"])
        case DecisionQuestionType.CHOICE:
            return ChoiceAnswer(
                choice=answer["choice"], confidence=answer["confidence"], probabilities=answer["probabilities"]
            )
        case DecisionQuestionType.SCORE:
            return ScoreAnswer(
                score=answer["score"], confidence=answer["confidence"], probabilities=answer["probabilities"]
            )
        case _:
            raise ValueError(f"unknown question type {question_type!r}")
