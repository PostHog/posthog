"""Keep personal data the scanner did not ask for out of a scan's answer.

Jev answers two separate questions: whether the scanner's question asks who the session belongs to, and whether
the answer contains personal data. Asked as one question, with the session's identity in view, it could not tell the
two apart. Where Jev is unavailable or errors, the answer passes.
"""

import json
import asyncio
from dataclasses import dataclass
from typing import Any

import structlog
from prometheus_client import Counter
from pydantic import BaseModel

from products.ml_inference.backend.facade import api as decision_api
from products.ml_inference.backend.facade.contracts import DecisionQuestion, DecisionRequest
from products.ml_inference.backend.facade.enums import DecisionQuestionType
from products.replay_vision.backend.error_kinds import FailureKind
from products.replay_vision.backend.temporal.errors import ScannerFailureError

logger = structlog.get_logger(__name__)

PII_CHECK_MODEL = "posthog/hogference/jevk5-fp8-0.2"
# Calibrated offline on production answers: the detector caught 96% of answers that repeated the subject's email
# unasked, most other flags were real names, and a question that asks for identity scored 0.86.
PII_FLAG_PROBABILITY = 0.8
ASKS_FOR_IDENTITY_PROBABILITY = 0.5
_JEV_TIMEOUT_SECONDS = 10.0
_TEXT_FIELDS = ("title", "summary", "reasoning", "notability_reason")

_DETECT_QUESTION = (
    "The state holds the text an AI scanner wrote about one recorded user session. Does the text contain personal data "
    "about a specific person: an email address, a person's name, a username or handle, a phone number, a street or IP "
    "address, payment details, or an account or government ID? Generic references such as 'the user', 'a customer', "
    "or a company or product name are not personal data."
)
_ASKS_QUESTION = (
    "The state holds the question a product team gave an AI scanner that watches recorded user sessions. Does the "
    "question ask the scanner to identify who the session belongs to, such as the person's name, email, or their "
    "company?"
)

PII_FIX_INSTRUCTION = (
    "Your answer includes personal data the question did not ask for. Remove it and refer to people generically, such "
    'as "the user" or "a customer\'s email address". Then return the complete answer again in the same JSON format.'
)

REPLAY_VISION_PII_CHECKS = Counter(
    "replay_vision_pii_checks_total",
    "Personal-data checks on scan answers, by outcome",
    ["outcome", "scanner_type"],
)


@dataclass(frozen=True)
class PiiCheckContext:
    team_id: int
    question: str
    scanner_type: str
    trace_id: str


def answer_text(output: BaseModel) -> dict[str, str]:
    return {
        field: value
        for field in _TEXT_FIELDS
        if isinstance(value := getattr(output, field, None), str) and value.strip()
    }


def _yes_probability(ctx: PiiCheckContext, state: dict[str, Any], instructions: str) -> float | None:
    if not decision_api.decisions_available_here():
        return None
    try:
        result = decision_api.decide_when_available(
            DecisionRequest(
                team_id=ctx.team_id,
                state=json.loads(json.dumps(state, default=str)),
                questions={"q": DecisionQuestion(type=DecisionQuestionType.NOUL, instructions=instructions)},
                model=PII_CHECK_MODEL,
                ai_product="replay_vision",
                trace_id=ctx.trace_id,
                # The state is recording-derived prose, which stays out of the internal AI observability project.
                privacy_mode=True,
            ),
            timeout_seconds=_JEV_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning("replay_vision.pii_check.unavailable", team_id=ctx.team_id, exc_info=True)
        return None
    return getattr(result.answers.get("q"), "probability", None)


def _check(output: BaseModel, ctx: PiiCheckContext) -> str:
    """The check's outcome: `identity_asked`, `clean`, `flagged`, or `unavailable` when Jev could not answer."""
    text = answer_text(output)
    if not text:
        return "clean"
    if ctx.question.strip():
        asks = _yes_probability(ctx, {"question": ctx.question}, _ASKS_QUESTION)
        if asks is None:
            return "unavailable"
        if asks >= ASKS_FOR_IDENTITY_PROBABILITY:
            return "identity_asked"
    detected = _yes_probability(ctx, {"text": text}, _DETECT_QUESTION)
    if detected is None:
        return "unavailable"
    return "flagged" if detected >= PII_FLAG_PROBABILITY else "clean"


async def has_unrequested_pii(output: BaseModel, ctx: PiiCheckContext) -> bool:
    """Whether the answer holds personal data the question did not ask for. Passes when Jev could not answer."""
    outcome = await asyncio.to_thread(_check, output, ctx)
    REPLAY_VISION_PII_CHECKS.labels(outcome=outcome, scanner_type=ctx.scanner_type).inc()
    return outcome == "flagged"


def pii_failure() -> ScannerFailureError:
    return ScannerFailureError(
        "The answer still included personal data the scanner didn't ask for after it was asked to remove it.",
        kind=FailureKind.PII_DETECTED,
    )
