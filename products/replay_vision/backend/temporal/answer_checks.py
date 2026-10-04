"""Checks a scan's answer must pass before it is kept.

Jev answers one yes/no question per check, each over its own small state. A check whose question cannot be answered
(Jev unavailable, a timeout, an error) passes. The scan re-asks the model once with every failed check's fix
instruction, and an answer that fails again fails the observation.
"""

import json
import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import structlog
from prometheus_client import Counter
from pydantic import BaseModel

from posthog.dataclasses import frozen

from products.ml_inference.backend.facade import api as decision_api
from products.ml_inference.backend.facade.contracts import DecisionQuestion, DecisionRequest
from products.ml_inference.backend.facade.enums import DecisionQuestionType
from products.replay_vision.backend.error_kinds import FailureKind
from products.replay_vision.backend.temporal.errors import ScannerFailureError
from products.replay_vision.backend.temporal.scanners.base import SignalsResponse

logger = structlog.get_logger(__name__)

CHECK_MODEL = "posthog/hogference/jevk5-fp8-0.2"
_JEV_TIMEOUT_SECONDS = 10.0
_TEXT_FIELDS = ("title", "summary", "reasoning", "notability_reason")
_SIGNAL_FIELDS = ("headline", "description")
_CONCLUSION_FIELDS = ("verdict", "score", "tags", "tags_freeform")
# Interaction events are what an answer's claims about the user rest on; the cap keeps Jev's state small.
_GROUNDING_EVENTS = frozenset({"$pageview", "$screen", "$autocapture", "$rageclick", "$dead_click", "$exception"})
_MAX_GROUNDING_EVENTS = 150

PII = "personal_data"
CONCLUSION = "conclusion_matches_reasoning"
GROUNDED = "claims_match_events"
FORMAT = "follows_question_format"
ON_QUESTION = "answers_the_question"

REPLAY_VISION_ANSWER_CHECKS = Counter(
    "replay_vision_answer_checks_total",
    "Answer checks on scan output, by check and outcome",
    ["check", "outcome", "scanner_type"],
)


@frozen
class CheckFailure:
    check: str
    fix: str


@dataclass(frozen=True)
class CheckContext:
    team_id: int
    question: str
    scanner_type: str
    trace_id: str
    events: list[dict[str, Any]]


@frozen
class _Check:
    name: str
    instructions: str
    # True when a high probability means the answer fails; False when a low one does.
    fails_on_yes: bool
    threshold: float
    fix: str
    state: Callable[[dict[str, Any], CheckContext], dict[str, Any] | None]


_ASKS_FOR_IDENTITY = (
    "The state holds the question a product team gave an AI scanner that watches recorded user sessions. Does the "
    "question ask the scanner to identify who the session belongs to, such as the person's name, email, or their "
    "company?"
)
# Calibrated offline on production answers: the detector caught 96% of answers that repeated the subject's email
# unasked, most other flags were real names, and a question that asks for identity scored 0.86.
_ASKS_FOR_IDENTITY_PROBABILITY = 0.5


def _text_state(answer: dict[str, Any], ctx: CheckContext) -> dict[str, Any] | None:
    text = answer.get("text")
    return {"text": text} if text else None


def _conclusion_state(answer: dict[str, Any], ctx: CheckContext) -> dict[str, Any] | None:
    conclusion = answer.get("conclusion")
    reasoning = (answer.get("text") or {}).get("reasoning")
    return {"reasoning": reasoning, "conclusion": conclusion} if conclusion and reasoning else None


def _grounding_state(answer: dict[str, Any], ctx: CheckContext) -> dict[str, Any] | None:
    text = answer.get("text")
    return {"answer": text, "events": ctx.events} if text and ctx.events else None


def _question_state(answer: dict[str, Any], ctx: CheckContext) -> dict[str, Any] | None:
    text = answer.get("text")
    return {"question": ctx.question, "answer": text} if text and ctx.question.strip() else None


_CHECKS: tuple[_Check, ...] = (
    _Check(
        name=PII,
        instructions=(
            "The state holds the text an AI scanner wrote about one recorded user session. Does the text contain "
            "personal data about a specific person: an email address, a person's name, a username or handle, a "
            "phone number, a street or IP address, payment details, or an account or government ID? Generic "
            "references such as 'the user', 'a customer', or a company or product name are not personal data."
        ),
        fails_on_yes=True,
        threshold=0.8,
        fix=(
            "Your answer includes personal data the question did not ask for. Remove it and refer to people "
            'generically, such as "the user" or "a customer\'s email address".'
        ),
        state=_text_state,
    ),
    _Check(
        name=CONCLUSION,
        instructions=(
            "The state holds the reasoning an AI scanner wrote about one recorded user session and the conclusion "
            "it gave (a verdict, a score, or tags). Does the reasoning support that conclusion?"
        ),
        fails_on_yes=False,
        threshold=0.2,
        fix=(
            "Your conclusion does not follow from your reasoning. Check the evidence again, then make the reasoning "
            "and the conclusion agree."
        ),
        state=_conclusion_state,
    ),
    _Check(
        name=GROUNDED,
        instructions=(
            "The state holds the text an AI scanner wrote about one recorded user session and the session's "
            "recorded interaction events, each with `vid_t`, the second of the video it happened at. Does the text "
            "claim the user did something (opened a page, clicked, submitted, paid, or signed up) that these events "
            "contradict? A claim the events simply do not cover is not a contradiction, because the video can show "
            "what the events miss."
        ),
        fails_on_yes=True,
        threshold=0.8,
        fix=(
            "Your answer says the user did something the session's events contradict. Look up those moments, then "
            "correct or remove the claim."
        ),
        state=_grounding_state,
    ),
    _Check(
        name=FORMAT,
        instructions=(
            "The state holds the question a product team gave an AI scanner and the answer it wrote. Does the "
            "answer follow every formatting requirement the question states, such as a title pattern, a required "
            "structure, a length, or a language? Answer yes when the question states none."
        ),
        fails_on_yes=False,
        threshold=0.2,
        fix="Your answer does not follow the format the question asks for. Keep the content and follow that format.",
        state=_question_state,
    ),
    _Check(
        name=ON_QUESTION,
        instructions=(
            "The state holds the question a product team gave an AI scanner and the answer it wrote about one "
            "recorded user session. Does the answer respond to that question? An answer that says the session "
            "never shows what the question is about still responds to it."
        ),
        fails_on_yes=False,
        threshold=0.2,
        fix=(
            "Your answer does not respond to the question you were given. Answer it, or say that the session never "
            "shows what it is about."
        ),
        state=_question_state,
    ),
)


def answer_parts(output: BaseModel) -> dict[str, Any]:
    """The text a step wrote, keyed by field, and its conclusion. Signals land under `signal_N_<field>` keys."""
    text = {
        field: value
        for field in _TEXT_FIELDS
        if isinstance(value := getattr(output, field, None), str) and value.strip()
    }
    if isinstance(output, SignalsResponse):
        for index, signal in enumerate(output.signals):
            for field in _SIGNAL_FIELDS:
                if (value := getattr(signal, field)).strip():
                    text[f"signal_{index}_{field}"] = value
    conclusion = {
        field: value for field in _CONCLUSION_FIELDS if (value := getattr(output, field, None)) not in (None, "", [])
    }
    return {"text": text, "conclusion": conclusion}


def grounding_events(events: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """The interaction events an answer's claims can be checked against, trimmed to what a check reads."""
    picked = [
        event
        for event in events
        if event.get("event") in _GROUNDING_EVENTS or not event.get("event", "$").startswith("$")
    ]
    keep = ("vid_t", "event", "$current_url", "elements_chain_texts")
    return [{key: event[key] for key in keep if key in event} for event in picked[:_MAX_GROUNDING_EVENTS]]


def _yes_probability(ctx: CheckContext, state: dict[str, Any], instructions: str) -> float | None:
    if not decision_api.decisions_available_here():
        return None
    try:
        result = decision_api.decide_when_available(
            DecisionRequest(
                team_id=ctx.team_id,
                state=json.loads(json.dumps(state, default=str)),
                questions={"q": DecisionQuestion(type=DecisionQuestionType.NOUL, instructions=instructions)},
                model=CHECK_MODEL,
                ai_product="replay_vision",
                trace_id=ctx.trace_id,
                # The state is recording-derived, which stays out of the internal AI observability project.
                privacy_mode=True,
            ),
            timeout_seconds=_JEV_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning("replay_vision.answer_checks.unavailable", team_id=ctx.team_id, exc_info=True)
        return None
    return getattr(result.answers.get("q"), "probability", None)


def _run_check(check: _Check, answer: dict[str, Any], ctx: CheckContext) -> bool | None:
    """True when the answer fails the check; None when the check does not apply or Jev could not answer."""
    state = check.state(answer, ctx)
    if state is None:
        return None
    probability = _yes_probability(ctx, state, check.instructions)
    if probability is None:
        return None
    return probability >= check.threshold if check.fails_on_yes else probability < check.threshold


def asks_for_identity(ctx: CheckContext) -> bool:
    if not ctx.question.strip():
        return False
    probability = _yes_probability(ctx, {"question": ctx.question}, _ASKS_FOR_IDENTITY)
    return probability is not None and probability >= _ASKS_FOR_IDENTITY_PROBABILITY


async def check_answer(output: BaseModel, ctx: CheckContext, *, checks: Sequence[str]) -> list[CheckFailure]:
    """Run the named checks that apply to `output` side by side; return the ones it fails."""
    selected = [check for check in _CHECKS if check.name in checks]
    if PII in checks and await asyncio.to_thread(asks_for_identity, ctx):
        record_check(PII, "identity_asked", ctx.scanner_type)
        selected = [check for check in selected if check.name != PII]
    answer = answer_parts(output)
    results = await asyncio.gather(*(asyncio.to_thread(_run_check, check, answer, ctx) for check in selected))
    failures: list[CheckFailure] = []
    for check, failed in zip(selected, results):
        record_check(check.name, "skipped" if failed is None else "failed" if failed else "passed", ctx.scanner_type)
        if failed:
            failures.append(CheckFailure(check=check.name, fix=check.fix))
    return failures


def fix_instruction(failures: Sequence[CheckFailure]) -> str:
    lines = "\n".join(f"- {failure.fix}" for failure in failures)
    return (
        f"Your answer did not pass these checks:\n{lines}\n\n"
        "Fix your answer. Look up any moment you need to. Then return the complete answer again in the same JSON "
        "format."
    )


def failure_after_fix(failures: Sequence[CheckFailure]) -> ScannerFailureError:
    """The error for an answer that still fails after the fix turn. Personal data gets its own kind."""
    names = sorted(failure.check for failure in failures)
    if PII in names:
        return ScannerFailureError(
            "The answer still included personal data the scanner didn't ask for after it was asked to remove it.",
            kind=FailureKind.PII_DETECTED,
        )
    return ScannerFailureError(
        f"The answer still failed these checks after it was asked to fix them: {', '.join(names)}.",
        kind=FailureKind.ANSWER_CHECK_FAILED,
    )


def record_check(check: str, outcome: str, scanner_type: str) -> None:
    REPLAY_VISION_ANSWER_CHECKS.labels(check=check, outcome=outcome, scanner_type=scanner_type).inc()
