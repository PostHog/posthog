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


def decisions_enabled(team_id: int) -> bool:
    """DEBUG bypasses the flag: the analytics SDK is disabled in local dev, where the surface has to be exercisable."""
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


def decide(
    request: DecisionRequest,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    transport: httpx.BaseTransport | None = None,
) -> DecisionResult:
    config = resolve_ai_gateway_config()
    if config is None:
        raise GatewayNotConfiguredError("AI_GATEWAY_URL and AI_GATEWAY_API_KEY must be configured")
    headers = {"Authorization": f"Bearer {config.api_key}"}
    headers.update(ai_gateway_headers(ai_product="ml_inference", distinct_id=team_distinct_id(request.team_id)) or {})
    with httpx.Client(trust_env=False, timeout=timeout_seconds, transport=transport) as client:
        response = client.post(decision_url(config.url), json=_wire_body(request), headers=headers)
    if response.status_code != 200:
        raise DecisionGatewayError(response.status_code, response.text[:500])
    try:
        payload = response.json()
    except ValueError as error:
        raise DecisionGatewayError(200, "decision response is not JSON") from error
    return parse_result(payload)


def _wire_body(request: DecisionRequest) -> dict[str, Any]:
    questions: dict[str, dict[str, Any]] = {}
    for question_id, question in request.questions.items():
        wire: dict[str, Any] = {"type": question.type.value, "instructions": question.instructions}
        if question.criteria:
            wire["criteria"] = question.criteria
        questions[question_id] = wire
    return {"model": request.model, "state": request.state, "questions": questions}


def parse_result(payload: Any) -> DecisionResult:
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
    try:
        parsed = {question_id: _parse_answer(answer) for question_id, answer in answers.items()}
        return DecisionResult(
            model=model, answers=parsed, input_tokens=input_tokens, latency_ms=payload.get("latency_ms")
        )
    except (ValueError, TypeError, KeyError) as error:
        raise DecisionGatewayError(200, f"decision response has an unreadable answer: {error}") from error


def _parse_answer(answer: Any) -> DecisionAnswer:
    if not isinstance(answer, dict):
        raise ValueError(f"answer is not an object: {answer!r}")
    if DecisionQuestionType.NOUL.value in answer:
        return NoulAnswer(probability=answer["noul"])
    if DecisionQuestionType.CHOICE.value in answer:
        return ChoiceAnswer(
            choice=answer["choice"], confidence=answer["confidence"], probabilities=answer["probabilities"]
        )
    if DecisionQuestionType.SCORE.value in answer:
        return ScoreAnswer(
            score=answer["score"], confidence=answer["confidence"], probabilities=answer["probabilities"]
        )
    raise ValueError(f"decision answer has no recognised type: {sorted(answer)}")
