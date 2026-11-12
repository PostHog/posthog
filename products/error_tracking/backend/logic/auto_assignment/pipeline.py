import time
from collections.abc import Sequence
from enum import StrEnum

import structlog

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.error_tracking.backend.logic.auto_assignment.base import Candidate, Decision, Processor
from products.error_tracking.backend.logic.auto_assignment.evidence import IssueEvidence
from products.error_tracking.backend.logic.auto_assignment.gate import AutoAssignmentConfig, load_auto_assignment_config
from products.error_tracking.backend.logic.auto_assignment.registry import PROCESSORS

logger = structlog.get_logger(__name__)


class ProcessorStatus(StrEnum):
    ACCEPTED = "accepted"
    BELOW_THRESHOLD = "below_threshold"
    NO_CANDIDATE = "no_candidate"
    FAILED = "failed"
    SKIPPED_AI_NOT_APPROVED = "skipped_ai_not_approved"
    SKIPPED_ALREADY_DECIDED = "skipped_already_decided"


@frozen
class ProcessorOutcome:
    processor: str
    status: ProcessorStatus
    candidate: Candidate | None = None
    threshold: float | None = None
    # Time spent in propose(), which includes loading the evidence it needs. None when it did not run.
    duration_ms: float | None = None


@frozen
class PipelineRun:
    decision: Decision | None
    outcomes: tuple[ProcessorOutcome, ...]


def run(
    evidence: IssueEvidence,
    *,
    processors: Sequence[Processor] = PROCESSORS,
    config: AutoAssignmentConfig | None = None,
) -> PipelineRun:
    config = config or load_auto_assignment_config(evidence.team.id)

    decision: Decision | None = None
    outcomes: list[ProcessorOutcome] = []
    for processor in processors:
        if decision is not None:
            outcome = ProcessorOutcome(processor=processor.name, status=ProcessorStatus.SKIPPED_ALREADY_DECIDED)
        else:
            outcome = _evaluate(processor, evidence, config)
            if (
                outcome.status == ProcessorStatus.ACCEPTED
                and outcome.candidate is not None
                and outcome.threshold is not None
            ):
                decision = Decision(candidate=outcome.candidate, threshold=outcome.threshold)
        outcomes.append(outcome)
    return PipelineRun(decision=decision, outcomes=tuple(outcomes))


def _evaluate(processor: Processor, evidence: IssueEvidence, config: AutoAssignmentConfig) -> ProcessorOutcome:
    if processor.sends_data_to_model and not evidence.ai_processing_approved:
        return ProcessorOutcome(processor=processor.name, status=ProcessorStatus.SKIPPED_AI_NOT_APPROVED)
    threshold = processor.threshold(config)
    start = time.monotonic()
    try:
        candidate = processor.propose(evidence, config)
    except Exception as error:
        capture_exception(error, additional_properties={"team_id": evidence.team.id, "processor": processor.name})
        logger.warning(
            "error_tracking_auto_assignment_processor_failed",
            team_id=evidence.team.id,
            issue_id=evidence.issue_id,
            processor=processor.name,
            exc_info=True,
        )
        return ProcessorOutcome(processor=processor.name, status=ProcessorStatus.FAILED, duration_ms=_elapsed_ms(start))
    if candidate is None:
        status = ProcessorStatus.NO_CANDIDATE
    elif candidate.confidence >= threshold:
        status = ProcessorStatus.ACCEPTED
    else:
        status = ProcessorStatus.BELOW_THRESHOLD
    return ProcessorOutcome(
        processor=processor.name,
        status=status,
        candidate=candidate,
        threshold=threshold,
        duration_ms=_elapsed_ms(start),
    )


def _elapsed_ms(start: float) -> float:
    return (time.monotonic() - start) * 1000
