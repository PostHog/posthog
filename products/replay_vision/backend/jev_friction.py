"""Jev friction judgment for the What to watch feed.

The feed's friction component is a keyword regex over the scan's prose (`_FRICTION_RE` in
`watch_feed.py`), which reads negations as friction and matches happy sessions on teams whose
product is about errors. Jev, the shared decision model behind the ml_inference facade, judges the
same prose with a calibrated probability instead. The judgment runs once per observation at scan
time and is stored in `scanner_result`, so the feed's read path stays deterministic and free of
model calls.

Rollout is gated per team by the multivariate `vision-jev-friction-mode` flag:

- `regex-only` (default): no Jev call; the feed ranks friction on the regex.
- `jev-shadow`: Jev runs and its probability is stored, disagreement with the regex is recorded,
  and the feed still ranks friction on the regex.
- `jev-only`: the feed ranks friction on stored probabilities; a row without one (scanned before
  the flag, or during a Jev outage) falls back to the regex.
"""

from __future__ import annotations

import math
from contextlib import suppress
from time import perf_counter
from typing import TYPE_CHECKING, Literal
from uuid import UUID

import structlog
import posthoganalytics
from prometheus_client import Counter, Histogram

from posthog.ph_client import get_feature_flag_or_none

from products.ml_inference.backend.facade import api as decision_api
from products.ml_inference.backend.facade.contracts import DecisionQuestion, DecisionRequest, NoulAnswer
from products.ml_inference.backend.facade.enums import DecisionQuestionType
from products.replay_vision.backend.watch_feed import friction_regex_hit

if TYPE_CHECKING:
    # A runtime import would be circular: the temporal package's __init__ imports the activity that
    # imports this module, and temporal.types sits inside that package.
    from products.replay_vision.backend.temporal.types import ScannerCallOutput

logger = structlog.get_logger(__name__)

FRICTION_MODE_FLAG = "vision-jev-friction-mode"
FrictionMode = Literal["regex-only", "jev-shadow", "jev-only"]
JEV_MODEL = "posthog/hogference/jevk5-fp8-0.2"
JEV_INPUT_USD_PER_MILLION = 0.042
JEV_TIMEOUT_SECONDS = 3.0
# Where the probability splits into a boolean for the shadow-mode disagreement metric only.
# Ranking consumes the probability itself, never this boolean.
FRICTION_DISAGREEMENT_THRESHOLD = 0.5

# User text stays in the request state; these instructions refer to it by field name only, so
# session prose cannot become an instruction (the rule from posthog/llm/system_one.py).
_FRICTION_INSTRUCTIONS = (
    "The state holds prose about one recorded product session: a title, a summary, reasoning, and tags. "
    "Judge whether that prose describes the recorded user experiencing friction: errors, failures, "
    "confusion, rage clicks, dead ends, retries, or giving up. "
    "A session about a product whose subject matter is errors or debugging is not friction on its own; "
    "only the recorded user's own experience counts."
)

_CALLS = Counter(
    "replay_vision_jev_friction_calls",
    "Jev friction judgments by outcome.",
    ["outcome"],
)
_DISAGREEMENTS = Counter(
    "replay_vision_jev_friction_disagreements",
    "Jev friction judgments that disagreed with the regex verdict.",
    ["regex_verdict", "jev_verdict"],
)
_LATENCY = Histogram(
    "replay_vision_jev_friction_latency_seconds",
    "Jev friction judgment wall-clock latency.",
    buckets=(0.05, 0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4),
)
_INPUT_TOKENS = Counter(
    "replay_vision_jev_friction_input_tokens",
    "Jev input tokens reported by the decision gateway.",
)
_ESTIMATED_COST = Counter(
    "replay_vision_jev_friction_estimated_cost_usd",
    "Jev input-token cost at the gateway catalog price.",
)


def friction_mode(team_id: int) -> FrictionMode:
    """The team's arm of the Jev friction experiment. Any flag failure reads as the default arm,
    so the scan pipeline and the feed never fail on flag evaluation."""
    value = get_feature_flag_or_none(
        FRICTION_MODE_FLAG,
        f"team-{team_id}",
        groups={"project": str(team_id)},
        group_properties={"project": {"id": team_id}},
        send_feature_flag_events=False,
    )
    if value == "jev-shadow":
        return "jev-shadow"
    if value == "jev-only":
        return "jev-only"
    return "regex-only"


def judge_scan_friction(team_id: int, observation_id: UUID, output: ScannerCallOutput) -> ScannerCallOutput:
    """Attach Jev's friction probability to a finished scan when the team's flag asks for it.

    Fail-soft by design: any error leaves the output unchanged, so a Jev outage can never fail or
    retry a paid-for scan. A row without a stored probability ranks on the regex.
    """
    try:
        mode = friction_mode(team_id)
        if mode == "regex-only":
            return output
        model_output = output.model_output
        if getattr(model_output, "verdict", None) == "no":
            # The scan judged a non-event. The feed skips these rows for friction for the same
            # reason: a "did not struggle" answer must not read as friction.
            return output
        title = getattr(model_output, "title", "")
        summary = getattr(model_output, "summary", "")
        reasoning = getattr(model_output, "reasoning", "")
        tags = [*getattr(model_output, "tags", []), *getattr(model_output, "tags_freeform", [])]
        prose_parts = [title, summary, reasoning, *tags]
        if not any(part.strip() for part in prose_parts):
            return output
        regex_verdict = friction_regex_hit(prose_parts)
        started = perf_counter()
        try:
            result = decision_api.decide_when_available(
                DecisionRequest(
                    team_id=team_id,
                    state={"title": title, "summary": summary, "reasoning": reasoning, "tags": tags},
                    questions={
                        "friction": DecisionQuestion(
                            type=DecisionQuestionType.NOUL, instructions=_FRICTION_INSTRUCTIONS
                        )
                    },
                    model=JEV_MODEL,
                    ai_product="replay_vision",
                    trace_id=str(observation_id),
                ),
                timeout_seconds=JEV_TIMEOUT_SECONDS,
            )
            answer = result.answers.get("friction")
            if (
                not isinstance(answer, NoulAnswer)
                or not math.isfinite(answer.probability)
                or not 0 <= answer.probability <= 1
            ):
                raise ValueError("Jev returned an invalid friction probability")
        except Exception as error:
            _LATENCY.observe(perf_counter() - started)
            _CALLS.labels(type(error).__name__).inc()
            # The gateway error body can echo the state, which holds recording-derived prose, so
            # only the error type leaves here.
            logger.warning("Jev friction judgment failed", team_id=team_id, error_type=type(error).__name__)
            return output
        _LATENCY.observe(perf_counter() - started)
        _CALLS.labels("ok").inc()
        estimated_cost = result.input_tokens * JEV_INPUT_USD_PER_MILLION / 1_000_000
        _INPUT_TOKENS.inc(result.input_tokens)
        _ESTIMATED_COST.inc(estimated_cost)
        jev_verdict = answer.probability >= FRICTION_DISAGREEMENT_THRESHOLD
        if jev_verdict != regex_verdict:
            _DISAGREEMENTS.labels(str(regex_verdict).lower(), str(jev_verdict).lower()).inc()
        with suppress(Exception):
            posthoganalytics.capture(
                event="replay_vision_jev_friction_evaluated",
                distinct_id=f"team-{team_id}",
                properties={
                    "observation_id": str(observation_id),
                    "mode": mode,
                    "jev_probability": answer.probability,
                    "jev_model": result.model,
                    "regex_verdict": regex_verdict,
                    "disagreement": jev_verdict != regex_verdict,
                    "input_tokens": result.input_tokens,
                    "estimated_cost_usd": estimated_cost,
                },
            )
        return output.model_copy(update={"friction_probability": answer.probability, "friction_model": result.model})
    except Exception:
        logger.exception("Jev friction judgment crashed", team_id=team_id)
        return output
