import json
from dataclasses import asdict
from hashlib import sha256
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models import OAuthAccessToken, Team, User
from posthog.temporal.oauth import PULSE_ANALYSIS_SCOPES, create_oauth_access_token_for_user

from products.experiments.backend.facade import (
    PulseExperimentDraftInput,
    create_pulse_experiment_draft_experiment,
    resolve_or_create_pulse_experiment_draft_flag,
)
from products.subscriptions.backend.models import ActionProposal, Artifact, Opportunity, PulseRun, RunAction
from products.subscriptions.backend.pulse.contracts import PulseExperimentDraftResultDTO
from products.tasks.backend.facade import api as tasks_api

PULSE_EXPERIMENT_DRAFT_SCOPE = "pulse_experiment_draft:write"
_PULSE_EXPERIMENT_DRAFT_SCOPES = (*PULSE_ANALYSIS_SCOPES, PULSE_EXPERIMENT_DRAFT_SCOPE)
_REQUEST_DIGEST_KEY = "request_sha256"
_FEATURE_FLAG_KEY = "feature_flag_key"
_FEATURE_FLAG_ID_KEY = "feature_flag_id"


class PulseExperimentDraftNotFound(ValueError):
    pass


class PulseExperimentDraftConflict(ValueError):
    pass


def has_exact_pulse_experiment_draft_scopes(scope: str) -> bool:
    return frozenset(scope.split()) == frozenset(_PULSE_EXPERIMENT_DRAFT_SCOPES)


@frozen
class _PulseExperimentDraftClaim:
    team: Team
    actor: User
    run_id: UUID
    action_id: UUID
    artifact_id: UUID
    task_run_id: UUID
    request_digest: str | None
    feature_flag_key: str | None
    experiment_id: int | None
    feature_flag_id: int | None


def _request_digest(input_dto: PulseExperimentDraftInput) -> str:
    encoded = json.dumps(asdict(input_dto), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return sha256(encoded).hexdigest()


def _artifact_metadata(artifact: Artifact) -> dict[str, object]:
    if not isinstance(artifact.metadata, dict):
        raise PulseExperimentDraftConflict("The experiment draft reservation is invalid.")
    return dict(artifact.metadata)


def _load_locked_claim(
    *,
    team_id: int,
    task_id: UUID,
    actor_id: int | None,
    request_digest: str | None,
    reserve_request: bool,
) -> _PulseExperimentDraftClaim:
    binding = tasks_api.resolve_staged_task_capability_binding(
        team_id=team_id,
        task_id=task_id,
        required_capability="experiment_draft",
    )
    if binding is None or (actor_id is not None and actor_id != binding.actor_id):
        raise PulseExperimentDraftNotFound("Experiment draft reservation not found.")
    team = Team.objects.select_for_update(of=("self",)).filter(id=team_id).first()
    actor = User.objects.select_for_update(of=("self",)).filter(id=binding.actor_id, is_active=True).first()
    if team is None or actor is None:
        raise PulseExperimentDraftNotFound("Experiment draft reservation not found.")
    run = PulseRun.objects.for_team(team_id).select_for_update().filter(id=binding.caller_id).first()
    if run is None:
        raise PulseExperimentDraftNotFound("Experiment draft reservation not found.")
    artifact = (
        Artifact.objects.for_team(team_id)
        .select_for_update()
        .filter(run=run, kind=Artifact.Kind.EXPERIMENT_DRAFT)
        .first()
    )
    if artifact is None:
        raise PulseExperimentDraftNotFound("Experiment draft reservation not found.")
    action = (
        RunAction.objects.for_team(team_id).select_for_update().filter(id=artifact.action_id).first()
        if artifact.action_id is not None
        else None
    )
    proposal = None
    opportunity = None
    if action is not None:
        if action.proposal_id is not None:
            proposal = (
                ActionProposal.objects.for_team(team_id).select_for_update().filter(id=action.proposal_id).first()
            )
        if action.opportunity_id is not None:
            opportunity = (
                Opportunity.objects.for_team(team_id).select_for_update().filter(id=action.opportunity_id).first()
            )
    flags = run.config_snapshot.get("flags") if isinstance(run.config_snapshot, dict) else None
    snapshot_actor_id = run.config_snapshot.get("actor_id") if isinstance(run.config_snapshot, dict) else None
    if (
        action is None
        or proposal is None
        or opportunity is None
        or run.status != PulseRun.Status.EXECUTING
        or run.finished_at is not None
        or run.task_id != task_id
        or run.execution_task_run_id != binding.task_run_id
        or snapshot_actor_id != binding.actor_id
        or not isinstance(flags, dict)
        or flags.get("allow_experiment_draft") is not True
        or artifact.team_id != team_id
        or artifact.task_id != task_id
        or artifact.execution_task_run_id != binding.task_run_id
        or artifact.opportunity_id != action.opportunity_id
        or artifact.proposal_id != action.proposal_id
        or action.team_id != team_id
        or action.run_id != run.id
        or action.kind not in {RunAction.Kind.EXPERIMENT_DRAFT, RunAction.Kind.COMBINED}
        or proposal.team_id != team_id
        or proposal.opportunity_id != action.opportunity_id
        or proposal.kind != action.kind
        or opportunity.team_id != team_id
        or not action.implementation_selected
        or action.status not in {RunAction.Status.EXECUTING, RunAction.Status.COMPLETED}
        or artifact.status not in {Artifact.Status.RESERVED, Artifact.Status.CREATING, Artifact.Status.VERIFIED}
        or (action.status == RunAction.Status.COMPLETED and artifact.status != Artifact.Status.VERIFIED)
    ):
        raise PulseExperimentDraftNotFound("Experiment draft reservation not found.")

    metadata = _artifact_metadata(artifact)
    stored_digest = metadata.get(_REQUEST_DIGEST_KEY)
    stored_flag_key = metadata.get(_FEATURE_FLAG_KEY)
    stored_flag_id = metadata.get(_FEATURE_FLAG_ID_KEY)
    if stored_digest is not None and not isinstance(stored_digest, str):
        raise PulseExperimentDraftConflict("The experiment draft reservation is invalid.")
    if stored_flag_key is not None and not isinstance(stored_flag_key, str):
        raise PulseExperimentDraftConflict("The experiment draft reservation is invalid.")
    if stored_flag_id is not None and (not isinstance(stored_flag_id, int) or isinstance(stored_flag_id, bool)):
        raise PulseExperimentDraftConflict("The experiment draft reservation is invalid.")
    if request_digest is not None and stored_digest is not None and stored_digest != request_digest:
        raise PulseExperimentDraftConflict("The experiment draft request does not match its reservation.")
    if artifact.status == Artifact.Status.VERIFIED and (
        artifact.experiment_id is None or stored_digest is None or stored_flag_id is None or stored_flag_key is None
    ):
        raise PulseExperimentDraftConflict("The verified experiment draft is incomplete.")
    if artifact.status != Artifact.Status.VERIFIED and artifact.experiment_id is not None:
        raise PulseExperimentDraftConflict("The experiment draft reservation is invalid.")
    if reserve_request:
        if request_digest is None:
            raise PulseExperimentDraftConflict("The experiment draft request is missing.")
        if stored_digest is None:
            stored_digest = request_digest
            stored_flag_key = f"pulse-exp-{artifact.id.hex}"
            metadata[_REQUEST_DIGEST_KEY] = stored_digest
            metadata[_FEATURE_FLAG_KEY] = stored_flag_key
            artifact.metadata = metadata
            artifact.status = Artifact.Status.CREATING
            artifact.failure_code = None
            artifact.save(update_fields=["metadata", "status", "failure_code", "updated_at"])
        elif stored_flag_key is None:
            raise PulseExperimentDraftConflict("The experiment draft reservation is invalid.")
    return _PulseExperimentDraftClaim(
        team=team,
        actor=actor,
        run_id=run.id,
        action_id=action.id,
        artifact_id=artifact.id,
        task_run_id=binding.task_run_id,
        request_digest=stored_digest,
        feature_flag_key=stored_flag_key,
        experiment_id=artifact.experiment_id,
        feature_flag_id=stored_flag_id,
    )


def issue_pulse_experiment_draft_token(*, team_id: int, task_id: UUID) -> str:
    with transaction.atomic():
        claim = _load_locked_claim(
            team_id=team_id,
            task_id=task_id,
            actor_id=None,
            request_digest=None,
            reserve_request=False,
        )
        OAuthAccessToken.objects.filter(sandbox_task_id=task_id).delete()
        return create_oauth_access_token_for_user(
            claim.actor,
            team_id,
            scopes=list(_PULSE_EXPERIMENT_DRAFT_SCOPES),
            include_internal_scopes=False,
            application="array",
            sandbox_task_id=task_id,
        )


def create_pulse_experiment_draft(
    *,
    team_id: int,
    task_id: UUID,
    actor_id: int,
    input_dto: PulseExperimentDraftInput,
) -> PulseExperimentDraftResultDTO:
    digest = _request_digest(input_dto)
    with transaction.atomic():
        claim = _load_locked_claim(
            team_id=team_id,
            task_id=task_id,
            actor_id=actor_id,
            request_digest=digest,
            reserve_request=True,
        )
        if claim.experiment_id is not None and claim.feature_flag_id is not None:
            return PulseExperimentDraftResultDTO(
                artifact_id=claim.artifact_id,
                action_id=claim.action_id,
                experiment_id=claim.experiment_id,
                feature_flag_id=claim.feature_flag_id,
                status="verified",
                created=False,
            )
        if claim.feature_flag_key is None:
            raise PulseExperimentDraftConflict("The experiment draft reservation is invalid.")

    feature_flag = resolve_or_create_pulse_experiment_draft_flag(
        team=claim.team,
        user=claim.actor,
        feature_flag_key=claim.feature_flag_key,
        input_dto=input_dto,
    )

    with transaction.atomic():
        claim = _load_locked_claim(
            team_id=team_id,
            task_id=task_id,
            actor_id=actor_id,
            request_digest=digest,
            reserve_request=True,
        )
        if claim.experiment_id is not None and claim.feature_flag_id is not None:
            return PulseExperimentDraftResultDTO(
                artifact_id=claim.artifact_id,
                action_id=claim.action_id,
                experiment_id=claim.experiment_id,
                feature_flag_id=claim.feature_flag_id,
                status="verified",
                created=False,
            )
        if claim.feature_flag_key != feature_flag.key:
            raise PulseExperimentDraftConflict("The experiment draft feature flag binding changed.")
        experiment = create_pulse_experiment_draft_experiment(
            team=claim.team,
            user=claim.actor,
            feature_flag_id=feature_flag.id,
            feature_flag_key=feature_flag.key,
            input_dto=input_dto,
        )
        artifact = Artifact.objects.for_team(team_id).select_for_update().get(id=claim.artifact_id)
        action = RunAction.objects.for_team(team_id).select_for_update().get(id=claim.action_id)
        metadata = _artifact_metadata(artifact)
        metadata[_FEATURE_FLAG_ID_KEY] = feature_flag.id
        artifact.metadata = metadata
        artifact.experiment_id = experiment.id
        artifact.status = Artifact.Status.VERIFIED
        artifact.verified_at = timezone.now()
        artifact.failure_code = None
        artifact.save(
            update_fields=[
                "metadata",
                "experiment_id",
                "status",
                "verified_at",
                "failure_code",
                "updated_at",
            ]
        )
        if action.kind == RunAction.Kind.EXPERIMENT_DRAFT:
            action.status = RunAction.Status.COMPLETED
            action.save(update_fields=["status", "updated_at"])
        return PulseExperimentDraftResultDTO(
            artifact_id=artifact.id,
            action_id=action.id,
            experiment_id=experiment.id,
            feature_flag_id=feature_flag.id,
            status="verified",
            created=True,
        )
