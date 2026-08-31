"""Canonical public facade for subscription-owned proactive Pulse capabilities."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from posthog.models import Team, User

from products.experiments.backend.facade import PulseExperimentDraftInput

from ..pulse import experiment_drafts, outcome_replays
from . import pulse
from .contracts import (
    EvidenceAuditDTO,
    OutcomeDecisionDTO,
    OutcomeReplayInstructionDTO,
    ProactiveConfigurationOptionsDTO,
    PublicResearchCitationDTO,
    PulseExperimentDraftResultDTO,
    PulseRunHistoryDTO,
)

PulseActionNotFound = pulse.PulseActionNotFound
PulseEvidenceConflict = pulse.PulseEvidenceConflict
PulseEvidenceNotFound = pulse.PulseEvidenceNotFound
PulsePublicResearchUnavailable = pulse.PulsePublicResearchUnavailable
PulseSubscriptionNotFound = pulse.PulseSubscriptionNotFound
PulseValidationError = pulse.PulseValidationError
EvidenceRawContent = pulse.EvidenceRawContent
PulseExperimentDraftConflict = experiment_drafts.PulseExperimentDraftConflict
PulseExperimentDraftNotFound = experiment_drafts.PulseExperimentDraftNotFound
PulseOutcomeReplayNotFound = outcome_replays.PulseOutcomeReplayNotFound


def list_pulse_history(*, team_id: int, team: Team, user: User, subscription_id: int) -> list[PulseRunHistoryDTO]:
    return pulse.list_pulse_history(team_id=team_id, team=team, user=user, subscription_id=subscription_id)


def get_proactive_configuration_options(*, team_id: int, user: User) -> ProactiveConfigurationOptionsDTO:
    return pulse.get_proactive_configuration_options(team_id=team_id, user=user)


def decide_run_action_outcome(
    *, team_id: int, team: Team, user: User, action_id: UUID, decision: Literal["adopted", "dismissed"]
) -> OutcomeDecisionDTO:
    return pulse.decide_run_action_outcome(
        team_id=team_id,
        team=team,
        user=user,
        action_id=action_id,
        decision=decision,
    )


def begin_evidence_tool_call(
    *,
    team_id: int,
    team: Team,
    user: User,
    run_id: UUID,
    tool_call_id: str,
    tool_name: str,
    tool_schema_version: str,
    arguments: object,
    actor_id: int,
    raw_expires_at: datetime,
) -> EvidenceAuditDTO:
    return pulse.begin_evidence_tool_call(
        team_id=team_id,
        team=team,
        user=user,
        run_id=run_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        tool_schema_version=tool_schema_version,
        arguments=arguments,
        actor_id=actor_id,
        raw_expires_at=raw_expires_at,
    )


def complete_evidence_tool_call(
    *,
    team_id: int,
    team: Team,
    user: User,
    run_id: UUID,
    tool_call_id: str,
    result: object,
    result_truncated: bool = False,
) -> EvidenceAuditDTO:
    return pulse.complete_evidence_tool_call(
        team_id=team_id,
        team=team,
        user=user,
        run_id=run_id,
        tool_call_id=tool_call_id,
        result=result,
        result_truncated=result_truncated,
    )


def fail_evidence_tool_call(
    *,
    team_id: int,
    team: Team,
    user: User,
    run_id: UUID,
    tool_call_id: str,
    error_class: str,
) -> EvidenceAuditDTO:
    return pulse.fail_evidence_tool_call(
        team_id=team_id,
        team=team,
        user=user,
        run_id=run_id,
        tool_call_id=tool_call_id,
        error_class=error_class,
    )


def purge_expired_evidence_raw_bodies(*, now: datetime | None = None) -> int:
    return pulse.purge_expired_evidence_raw_bodies(now=now)


def read_evidence_raw_body(*, team_id: int, team: Team, user: User, evidence_id: UUID) -> EvidenceRawContent:
    return pulse.read_evidence_raw_body(team_id=team_id, team=team, user=user, evidence_id=evidence_id)


def research_public_context(
    *,
    team_id: int,
    team: Team,
    user: User,
    run_id: UUID,
    public_subject_id: UUID,
    topic: str,
    tool_call_id: str,
    raw_expires_at: datetime,
) -> PublicResearchCitationDTO:
    return pulse.research_public_context(
        team_id=team_id,
        team=team,
        user=user,
        run_id=run_id,
        public_subject_id=public_subject_id,
        topic=topic,
        tool_call_id=tool_call_id,
        raw_expires_at=raw_expires_at,
    )


def create_pulse_experiment_draft(
    *, team_id: int, task_id: UUID, actor_id: int, input_dto: PulseExperimentDraftInput
) -> PulseExperimentDraftResultDTO:
    return experiment_drafts.create_pulse_experiment_draft(
        team_id=team_id,
        task_id=task_id,
        actor_id=actor_id,
        input_dto=input_dto,
    )


def issue_pulse_experiment_draft_token(*, team_id: int, task_id: UUID) -> str:
    return experiment_drafts.issue_pulse_experiment_draft_token(team_id=team_id, task_id=task_id)


def has_exact_pulse_experiment_draft_scopes(scope: str) -> bool:
    return experiment_drafts.has_exact_pulse_experiment_draft_scopes(scope)


def get_pulse_outcome_replay_instruction(
    *, team_id: int, task_id: UUID, actor_id: int, plan_id: UUID
) -> OutcomeReplayInstructionDTO:
    return outcome_replays.get_outcome_replay_instruction(
        team_id=team_id,
        task_id=task_id,
        actor_id=actor_id,
        plan_id=plan_id,
    )


def has_exact_pulse_analysis_scopes(scope: str) -> bool:
    return outcome_replays.has_exact_pulse_analysis_scopes(scope)


__all__ = [
    "PulseActionNotFound",
    "PulseEvidenceConflict",
    "PulseEvidenceNotFound",
    "PulsePublicResearchUnavailable",
    "PulseSubscriptionNotFound",
    "PulseValidationError",
    "PulseExperimentDraftConflict",
    "PulseExperimentDraftNotFound",
    "PulseOutcomeReplayNotFound",
    "EvidenceRawContent",
    "list_pulse_history",
    "get_proactive_configuration_options",
    "begin_evidence_tool_call",
    "complete_evidence_tool_call",
    "fail_evidence_tool_call",
    "purge_expired_evidence_raw_bodies",
    "read_evidence_raw_body",
    "research_public_context",
    "create_pulse_experiment_draft",
    "has_exact_pulse_experiment_draft_scopes",
    "has_exact_pulse_analysis_scopes",
    "get_pulse_outcome_replay_instruction",
    "issue_pulse_experiment_draft_token",
    "decide_run_action_outcome",
]
