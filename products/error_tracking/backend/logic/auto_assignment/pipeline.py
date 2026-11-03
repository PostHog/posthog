from collections.abc import Sequence
from enum import StrEnum

import structlog

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.error_tracking.backend.logic.auto_assignment import PROCESSORS
from products.error_tracking.backend.logic.auto_assignment.base import Candidate, Decision, Processor
from products.error_tracking.backend.logic.auto_assignment.evidence import IssueEvidence
from products.error_tracking.backend.logic.auto_assignment.gate import (
    AutoAssignmentConfig,
    auto_assignment_enabled,
    load_auto_assignment_config,
)

logger = structlog.get_logger(__name__)


class ProcessorStatus(StrEnum):
    ACCEPTED = "accepted"
    BELOW_THRESHOLD = "below_threshold"
    NO_CANDIDATE = "no_candidate"
    FAILED = "failed"
    SKIPPED_GATE_OFF = "skipped_gate_off"
    SKIPPED_AI_NOT_APPROVED = "skipped_ai_not_approved"
    SKIPPED_ALREADY_DECIDED = "skipped_already_decided"


@frozen
class ProcessorOutcome:
    processor: str
    status: ProcessorStatus
    candidate: Candidate | None = None
    threshold: float | None = None


@frozen
class PipelineRun:
    decision: Decision | None
    outcomes: tuple[ProcessorOutcome, ...]
    similar_issue_lookup_ms: float | None


def run(
    evidence: IssueEvidence,
    *,
    processors: Sequence[Processor] = PROCESSORS,
    config: AutoAssignmentConfig | None = None,
) -> PipelineRun:
    if not auto_assignment_enabled(evidence.team.id):
        return PipelineRun(
            decision=None,
            outcomes=tuple(
                ProcessorOutcome(processor=p.name, status=ProcessorStatus.SKIPPED_GATE_OFF) for p in processors
            ),
            similar_issue_lookup_ms=None,
        )
    config = config or load_auto_assignment_config(evidence.team.id)

    decision: Decision | None = None
    outcomes: list[ProcessorOutcome] = []
    for processor in processors:
        if decision is not None:
            outcomes.append(ProcessorOutcome(processor=processor.name, status=ProcessorStatus.SKIPPED_ALREADY_DECIDED))
            continue
        if processor.sends_data_to_model and not evidence.ai_processing_approved:
            outcomes.append(ProcessorOutcome(processor=processor.name, status=ProcessorStatus.SKIPPED_AI_NOT_APPROVED))
            continue
        threshold = processor.threshold(config)
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
            outcomes.append(ProcessorOutcome(processor=processor.name, status=ProcessorStatus.FAILED))
            continue
        if candidate is None:
            status = ProcessorStatus.NO_CANDIDATE
        elif candidate.confidence >= threshold:
            status = ProcessorStatus.ACCEPTED
            decision = Decision(candidate=candidate, threshold=threshold)
        else:
            status = ProcessorStatus.BELOW_THRESHOLD
        outcomes.append(
            ProcessorOutcome(processor=processor.name, status=status, candidate=candidate, threshold=threshold)
        )

    return PipelineRun(
        decision=decision,
        outcomes=tuple(outcomes),
        similar_issue_lookup_ms=evidence.similar_issue_lookup_ms,
    )
