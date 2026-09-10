from typing import Literal

from pydantic import BaseModel, Field

from products.replay_vision.backend.temporal.scanners.base import MissionStep, SignalFinding
from products.replay_vision.backend.temporal.scanners.prompt_env import render_prompt

STEP_VERIFY_SIGNALS = "verify_signals"


class SignalAssessment(BaseModel, frozen=True):
    finding_index: int = Field(ge=0)
    verdict: Literal["supported", "unsupported", "inconclusive"]
    evidence_time: int | None = Field(default=None, ge=0)
    url: str | None = None
    reasoning: str = Field(min_length=1)


class SignalAssessmentResponse(BaseModel, frozen=True):
    assessments: list[SignalAssessment] = Field(default_factory=list)


def build_signal_verification_step(signals: list[SignalFinding]) -> MissionStep:
    candidates = [
        {"finding_index": finding_index, **signal.model_dump(exclude={"confidence"})}
        for finding_index, signal in enumerate(signals)
    ]
    return MissionStep(
        name=STEP_VERIFY_SIGNALS,
        instruction=render_prompt("signals_verification_step.jinja", candidates=candidates),
        response_model=SignalAssessmentResponse,
        required=False,
    )


def select_verified_signals(
    signals: list[SignalFinding], response: SignalAssessmentResponse | None
) -> list[SignalFinding]:
    if response is None:
        return []

    assessments: dict[int, SignalAssessment] = {}
    for assessment in response.assessments:
        finding_index = assessment.finding_index
        if finding_index < 0 or finding_index >= len(signals) or finding_index in assessments:
            return []
        assessments[finding_index] = assessment

    return [
        signal
        for finding_index, signal in enumerate(signals)
        if (assessment := assessments.get(finding_index)) is not None
        and assessment.verdict == "supported"
        and assessment.reasoning.strip()
        and signal.url.strip()
        and assessment.url == signal.url
        and assessment.evidence_time is not None
        and signal.start_time <= assessment.evidence_time <= signal.end_time
    ]
