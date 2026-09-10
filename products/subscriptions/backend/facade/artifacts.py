"""Durable, policy-owned claims for one proactive recommendation artifact."""

from __future__ import annotations

import re
import json
import hashlib
from datetime import datetime, timedelta
from typing import Literal, cast
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from rest_framework.exceptions import APIException

from posthog.dataclasses import frozen

from products.experiments.backend.facade import PulseExperimentDraftInput, create_pulse_experiment_draft
from products.subscriptions.backend.models import (
    ProactivePreparedArtifact,
    ProactiveRecommendation,
    ProactiveRecommendationRun,
)
from products.tasks.backend.facade.draft_publication import (
    DraftPublicationLifecycleResult,
    DraftPublicationRequest,
    get_draft_publication,
    get_draft_publication_lifecycle,
    reserve_draft_publication,
)
from products.tasks.backend.facade.repository_authorization import revalidate_staged_repository_binding
from products.tasks.backend.facade.staged_execution import (
    PULSE_EXECUTION_DISABLED_TOOLS,
    PULSE_EXECUTION_NETWORK_EGRESS,
    AdvanceStagedTaskInput,
    StagedCapabilityManifest,
    advance_staged_task,
)

PreparedArtifactKind = Literal["draft_pr", "experiment_draft"]
PreparedArtifactStatus = Literal["preparing", "prepared", "failed"]
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@frozen
class PreparedArtifactClaimInput:
    team_id: int
    run_id: UUID
    actor_id: int


@frozen
class PreparedArtifactFailureInput:
    team_id: int
    artifact_id: UUID
    failure_code: str


@frozen
class PrepareExperimentDraftInput:
    team_id: int
    artifact_id: UUID
    actor_id: int


@frozen
class PrepareDraftPRInput:
    team_id: int
    artifact_id: UUID
    actor_id: int


@frozen
class PreparedExperimentDraftDTO:
    artifact_id: UUID
    experiment_id: int
    feature_flag_id: int
    url: str
    prepared_at: datetime


@frozen
class PreparedDraftPRDTO:
    artifact_id: UUID
    staged_run_id: UUID | None
    publication_id: UUID | None
    prior_artifact_id: UUID | None
    status: PreparedArtifactStatus


@frozen
class PreparedArtifactDTO:
    id: UUID
    recommendation_id: UUID
    kind: PreparedArtifactKind
    status: PreparedArtifactStatus
    input_hash: str


@frozen
class _EligibleArtifact:
    recommendation: ProactiveRecommendation
    kind: PreparedArtifactKind
    input_hash: str


def claim_prepared_artifact(input: PreparedArtifactClaimInput) -> PreparedArtifactDTO | None:
    """Claim the first currently eligible persisted recommendation for one completed run."""
    if not _artifact_preparation_enabled():
        return None
    with transaction.atomic():
        run = (
            ProactiveRecommendationRun.objects.for_team(input.team_id)
            .select_for_update()
            .filter(id=input.run_id)
            .first()
        )
        if run is None:
            raise ValueError("recommendation run was not found")
        if run.actor_id != input.actor_id:
            raise ValueError("artifact actor does not match its recommendation run")

        artifact = (
            ProactivePreparedArtifact.objects.for_team(input.team_id)
            .select_related("recommendation")
            .filter(run_id=run.id)
            .first()
        )
        if artifact is not None:
            if not _matches_durable_replay(artifact=artifact, run=run):
                raise ValueError("artifact replay does not match its durable claim")
            return _artifact_dto(artifact)

        eligible = _select_eligible_artifact(run=run)
        if eligible is None:
            return None
        assert run.artifact_config_hash is not None

        artifact = ProactivePreparedArtifact.objects.for_team(input.team_id).create(
            team_id=input.team_id,
            run=run,
            recommendation=eligible.recommendation,
            kind=eligible.kind,
            artifact_config_hash=run.artifact_config_hash,
            input_hash=eligible.input_hash,
        )
        return _artifact_dto(artifact)


def mark_prepared_artifact_failed(input: PreparedArtifactFailureInput) -> PreparedArtifactDTO:
    """Record a bounded local preparation failure without touching its recommendation run."""
    if not input.failure_code:
        raise ValueError("artifact failure code is required")
    if not _artifact_preparation_enabled():
        artifact = ProactivePreparedArtifact.objects.for_team(input.team_id).get(id=input.artifact_id)
        return _artifact_dto(artifact)
    with transaction.atomic():
        current = (
            ProactivePreparedArtifact.objects.for_team(input.team_id)
            .select_for_update()
            .filter(id=input.artifact_id)
            .first()
        )
        if current is None:
            raise ValueError("prepared artifact was not found")
        if current.status == ProactivePreparedArtifact.Status.PREPARING:
            current.status = ProactivePreparedArtifact.Status.FAILED
            current.failure_code = input.failure_code[:128]
            current.save(update_fields=["status", "failure_code", "updated_at"])
        return _artifact_dto(current)


def prepare_experiment_draft(input: PrepareExperimentDraftInput) -> PreparedExperimentDraftDTO:
    """Complete one claimed experiment draft, preserving exact prepared replays."""
    if not _artifact_preparation_enabled():
        raise ValueError("proactive artifact preparation is disabled")
    with transaction.atomic():
        artifact = (
            ProactivePreparedArtifact.objects.for_team(input.team_id)
            .select_for_update()
            .select_related("recommendation", "run")
            .filter(id=input.artifact_id)
            .first()
        )
        if artifact is None:
            raise ValueError("prepared artifact was not found")
        if artifact.run.actor_id != input.actor_id:
            raise ValueError("artifact actor does not match its recommendation run")
        if artifact.kind != ProactivePreparedArtifact.Kind.EXPERIMENT_DRAFT:
            raise ValueError("prepared artifact is not an experiment draft")
        if artifact.status == ProactivePreparedArtifact.Status.PREPARED:
            return _prepared_experiment_dto(artifact)
        if artifact.status != ProactivePreparedArtifact.Status.PREPARING:
            raise ValueError("prepared artifact is not awaiting experiment preparation")
        if not _matches_durable_replay(artifact=artifact, run=artifact.run):
            raise ValueError("artifact replay does not match its durable claim")

        result = create_pulse_experiment_draft(
            _pulse_experiment_draft_input(artifact=artifact, actor_id=input.actor_id)
        )
        artifact.experiment_id = result.experiment_id
        artifact.feature_flag_id = result.feature_flag_id
        artifact.url = result.url
        artifact.prepared_at = timezone.now()
        artifact.status = ProactivePreparedArtifact.Status.PREPARED
        artifact.failure_code = None
        artifact.save(
            update_fields=[
                "experiment_id",
                "feature_flag_id",
                "url",
                "prepared_at",
                "status",
                "failure_code",
                "updated_at",
            ]
        )
        return _prepared_experiment_dto(artifact)


def prepare_draft_pr(input: PrepareDraftPRInput) -> PreparedDraftPRDTO:
    """Advance one claimed code artifact and reserve its Tasks-owned publication."""
    if not _artifact_preparation_enabled():
        raise ValueError("proactive artifact preparation is disabled")
    artifact = (
        ProactivePreparedArtifact.objects.for_team(input.team_id)
        .select_related("recommendation", "run")
        .filter(id=input.artifact_id)
        .first()
    )
    if artifact is None:
        raise ValueError("prepared artifact was not found")
    if artifact.run.actor_id != input.actor_id:
        raise ValueError("artifact actor does not match its recommendation run")
    if artifact.kind != ProactivePreparedArtifact.Kind.DRAFT_PR:
        raise ValueError("prepared artifact is not a draft pull request")
    if artifact.status != ProactivePreparedArtifact.Status.PREPARING:
        return _prepared_draft_pr_dto(artifact)
    if not _matches_durable_replay(artifact=artifact, run=artifact.run):
        raise ValueError("artifact replay does not match its durable claim")

    recorded = _recorded_draft_publication(artifact)
    if recorded is not None:
        return recorded
    linked = _link_open_prior_draft(artifact=artifact)
    if linked is not None:
        return linked
    if artifact.run.staged_run_id is None:
        raise ValueError("draft pull request artifact has no staged task")
    advanced = advance_staged_task(
        AdvanceStagedTaskInput(
            team_id=artifact.team_id,
            caller_id=artifact.run.delivery_id,
            staged_run_id=artifact.run.staged_run_id,
            idempotency_key=f"pulse-artifact-execution:{artifact.id}",
            instruction=_execution_instruction(artifact),
            execution_manifest=StagedCapabilityManifest(
                version=1,
                phase="execution",
                mcp_scope_preset="read_only",
                disabled_tools=PULSE_EXECUTION_DISABLED_TOOLS,
                network_egress=cast(Literal["inherit", "posthog_mcp_only"], PULSE_EXECUTION_NETWORK_EGRESS),
            ),
        )
    )
    publication = reserve_draft_publication(
        _draft_publication_request(artifact=artifact, staged_run_id=advanced.staged_run_id)
    )
    with transaction.atomic():
        current = (
            ProactivePreparedArtifact.objects.for_team(input.team_id)
            .select_for_update(of=("self",))
            .select_related("recommendation", "run")
            .get(id=artifact.id)
        )
        if (
            current.status != ProactivePreparedArtifact.Status.PREPARING
            or not _matches_durable_replay(artifact=current, run=current.run)
            or (current.staged_run_id is not None and current.staged_run_id != advanced.staged_run_id)
            or (current.task_publication_id is not None and current.task_publication_id != publication.publication_id)
        ):
            raise ValueError("draft pull request artifact replay does not match its durable claim")
        current.staged_run_id = advanced.staged_run_id
        current.task_publication_id = publication.publication_id
        current.save(update_fields=["staged_run_id", "task_publication_id", "updated_at"])
        return _prepared_draft_pr_dto(current)


def _recorded_draft_publication(artifact: ProactivePreparedArtifact) -> PreparedDraftPRDTO | None:
    if artifact.task_publication_id is None:
        return None
    if artifact.staged_run_id is None:
        raise ValueError("draft pull request artifact publication has no staged task")
    if artifact.staged_run_id != artifact.run.staged_run_id:
        raise ValueError("draft pull request artifact publication replay does not match its durable claim")
    publication = get_draft_publication(
        team_id=artifact.team_id,
        caller_id=artifact.run.delivery_id,
        publication_id=artifact.task_publication_id,
    )
    if publication.publication_id != artifact.task_publication_id:
        raise ValueError("draft pull request artifact publication replay does not match its durable claim")
    return _prepared_draft_pr_dto(artifact)


def _draft_publication_request(*, artifact: ProactivePreparedArtifact, staged_run_id: UUID) -> DraftPublicationRequest:
    expires_at = artifact.created_at + timedelta(days=7)
    return DraftPublicationRequest(
        team_id=artifact.team_id,
        caller_id=artifact.run.delivery_id,
        staged_run_id=staged_run_id,
        logical_artifact_key=f"pulse-artifact:{artifact.id}",
        commit_message=_commit_message(artifact),
        pr_title=_pr_title(artifact),
        pr_body=_pr_body(artifact),
        starts_before=min(timezone.now() + timedelta(hours=1), expires_at),
        expires_at=expires_at,
    )


def prepare_proactive_artifact_for_run(*, team_id: int, run_id: UUID) -> None:
    """Complete the one artifact selected for a completed run without exposing delivery models."""
    if not _artifact_preparation_enabled():
        return
    run = ProactiveRecommendationRun.objects.for_team(team_id).filter(id=run_id).only("actor_id").first()
    if run is None:
        return
    artifact = claim_prepared_artifact(
        PreparedArtifactClaimInput(team_id=team_id, run_id=run_id, actor_id=run.actor_id)
    )
    if artifact is None:
        return
    try:
        if artifact.kind == "experiment_draft":
            prepare_experiment_draft(
                PrepareExperimentDraftInput(team_id=team_id, artifact_id=artifact.id, actor_id=run.actor_id)
            )
        else:
            prepare_draft_pr(PrepareDraftPRInput(team_id=team_id, artifact_id=artifact.id, actor_id=run.actor_id))
    except (APIException, ValueError) as err:
        mark_prepared_artifact_failed(
            PreparedArtifactFailureInput(
                team_id=team_id, artifact_id=artifact.id, failure_code=type(err).__name__.lower()
            )
        )


def _link_open_prior_draft(*, artifact: ProactivePreparedArtifact) -> PreparedDraftPRDTO | None:
    candidates = list(
        ProactivePreparedArtifact.objects.for_team(artifact.team_id)
        .select_related("run")
        .filter(
            kind=ProactivePreparedArtifact.Kind.DRAFT_PR,
            recommendation__semantic_key=artifact.recommendation.semantic_key,
            run__subscription_id=artifact.run.subscription_id,
            task_publication_id__isnull=False,
        )
        .exclude(id=artifact.id)
        .order_by("-created_at")[:20]
    )
    for candidate in candidates:
        assert candidate.task_publication_id is not None
        try:
            lifecycle: DraftPublicationLifecycleResult = get_draft_publication_lifecycle(
                team_id=artifact.team_id,
                caller_id=candidate.run.delivery_id,
                publication_id=candidate.task_publication_id,
            )
        except Exception:
            continue
        if lifecycle.remote_state != "open":
            continue
        with transaction.atomic():
            current = (
                ProactivePreparedArtifact.objects.for_team(artifact.team_id)
                .select_for_update(of=("self",))
                .select_related("recommendation", "run")
                .get(id=artifact.id)
            )
            if current.status != ProactivePreparedArtifact.Status.PREPARING or not _matches_durable_replay(
                artifact=current, run=current.run
            ):
                raise ValueError("draft pull request artifact replay does not match its durable claim")
            current.prior_artifact_id = candidate.id
            current.url = lifecycle.pr_url
            current.prepared_at = timezone.now()
            current.status = ProactivePreparedArtifact.Status.PREPARED
            current.failure_code = None
            current.save(update_fields=["prior_artifact", "url", "prepared_at", "status", "failure_code", "updated_at"])
            return _prepared_draft_pr_dto(current)
    return None


def _execution_instruction(artifact: ProactivePreparedArtifact) -> str:
    payload = artifact.recommendation.recommendation
    if not isinstance(payload, dict):
        raise ValueError("draft pull request recommendation payload is invalid")
    title = _bounded_recommendation_text(payload, "title")
    target = _bounded_recommendation_text(payload, "target")
    rationale = _bounded_recommendation_text(payload, "rationale")
    return (
        "Implement the selected recommendation in the bound repository.\n\n"
        f"Recommendation: {title}\nTarget: {target}\nRationale: {rationale}\n\n"
        "Run focused tests for the changed code."
    )


def _commit_message(artifact: ProactivePreparedArtifact) -> str:
    return f"feat(pulse): {_bounded_recommendation_text(artifact.recommendation.recommendation, 'title', 440)}"


def _pr_title(artifact: ProactivePreparedArtifact) -> str:
    return f"feat: {_bounded_recommendation_text(artifact.recommendation.recommendation, 'title', 240)}"


def _pr_body(artifact: ProactivePreparedArtifact) -> str:
    title = _bounded_recommendation_text(artifact.recommendation.recommendation, "title", 500)
    target = _bounded_recommendation_text(artifact.recommendation.recommendation, "target", 500)
    return f"## Summary\n\nImplements the selected recommendation: {title}.\n\nTarget: {target}."


def _bounded_recommendation_text(payload: object, field: str, maximum: int = 1_000) -> str:
    value = payload.get(field) if isinstance(payload, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("draft pull request recommendation payload is invalid")
    return " ".join(value.split())[:maximum]


def _prepared_draft_pr_dto(artifact: ProactivePreparedArtifact) -> PreparedDraftPRDTO:
    return PreparedDraftPRDTO(
        artifact_id=artifact.id,
        staged_run_id=artifact.staged_run_id,
        publication_id=artifact.task_publication_id,
        prior_artifact_id=artifact.prior_artifact_id,
        status=cast(PreparedArtifactStatus, artifact.status),
    )


def _artifact_preparation_enabled() -> bool:
    return bool(getattr(settings, "PULSE_ARTIFACT_PREPARATION_ENABLED", False))


def _select_eligible_artifact(*, run: ProactiveRecommendationRun) -> _EligibleArtifact | None:
    if run.status != ProactiveRecommendationRun.Status.COMPLETED or not _is_sha256(run.artifact_config_hash):
        return None
    rows = ProactiveRecommendation.objects.for_team(run.team_id).filter(run_id=run.id).order_by("created_at", "id")
    for recommendation in rows:
        recommendation_kind = _recommendation_kind(recommendation.recommendation)
        if recommendation_kind == "experiment":
            return _eligible_artifact(
                run=run,
                recommendation=recommendation,
                kind="experiment_draft",
                binding=None,
            )
        if recommendation_kind not in {"product_change", "instrumentation"}:
            continue
        binding = _valid_repository_binding(run.repository_binding)
        if binding is None or not revalidate_staged_repository_binding(
            team_id=run.team_id,
            actor_id=run.actor_id,
            repository=binding.repository,
            github_integration_id=binding.github_integration_id,
            github_user_integration_id=binding.github_user_integration_id,
            github_installation_id=binding.github_installation_id,
        ):
            continue
        return _eligible_artifact(
            run=run,
            recommendation=recommendation,
            kind="draft_pr",
            binding=binding.canonical_payload,
        )
    return None


@frozen
class _RepositoryBinding:
    repository: str
    base_sha: str
    base_branch: str
    github_integration_id: int
    github_user_integration_id: UUID
    github_installation_id: str
    grant_version: str

    @property
    def canonical_payload(self) -> dict[str, object]:
        return {
            "repository": self.repository,
            "base_sha": self.base_sha,
            "base_branch": self.base_branch,
            "github_integration_id": self.github_integration_id,
            "github_user_integration_id": str(self.github_user_integration_id),
            "github_installation_id": self.github_installation_id,
            "grant_version": self.grant_version,
        }


def _valid_repository_binding(payload: object) -> _RepositoryBinding | None:
    if not isinstance(payload, dict) or set(payload) != {
        "repository",
        "base_sha",
        "base_branch",
        "github_integration_id",
        "github_user_integration_id",
        "github_installation_id",
        "grant_version",
    }:
        return None
    repository = payload["repository"]
    base_sha = payload["base_sha"]
    base_branch = payload["base_branch"]
    github_integration_id = payload["github_integration_id"]
    github_user_integration_id = payload["github_user_integration_id"]
    github_installation_id = payload["github_installation_id"]
    grant_version = payload["grant_version"]
    if not (
        isinstance(repository, str)
        and repository
        and isinstance(base_sha, str)
        and base_sha
        and isinstance(base_branch, str)
        and base_branch
        and type(github_integration_id) is int
        and isinstance(github_user_integration_id, str)
        and isinstance(github_installation_id, str)
        and github_installation_id
        and isinstance(grant_version, str)
        and grant_version
    ):
        return None
    try:
        user_integration_id = UUID(github_user_integration_id)
    except ValueError:
        return None
    return _RepositoryBinding(
        repository=repository,
        base_sha=base_sha,
        base_branch=base_branch,
        github_integration_id=github_integration_id,
        github_user_integration_id=user_integration_id,
        github_installation_id=github_installation_id,
        grant_version=grant_version,
    )


def _eligible_artifact(
    *,
    run: ProactiveRecommendationRun,
    recommendation: ProactiveRecommendation,
    kind: PreparedArtifactKind,
    binding: dict[str, object] | None,
) -> _EligibleArtifact:
    assert run.artifact_config_hash is not None
    payload = {
        "artifact_config_hash": run.artifact_config_hash,
        "kind": kind,
        "recommendation_id": str(recommendation.id),
        "repository_binding": binding,
        "run_id": str(run.id),
    }
    input_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return _EligibleArtifact(recommendation=recommendation, kind=kind, input_hash=input_hash)


def _recommendation_kind(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    kind = payload.get("kind")
    return kind if isinstance(kind, str) else None


def _matches_durable_replay(*, artifact: ProactivePreparedArtifact, run: ProactiveRecommendationRun) -> bool:
    recommendation = artifact.recommendation
    if (
        run.status != ProactiveRecommendationRun.Status.COMPLETED
        or not _is_sha256(run.artifact_config_hash)
        or artifact.team_id != run.team_id
        or artifact.run_id != run.id
        or recommendation.team_id != run.team_id
        or recommendation.run_id != run.id
        or artifact.artifact_config_hash != run.artifact_config_hash
    ):
        return False
    recommendation_kind = _recommendation_kind(recommendation.recommendation)
    if artifact.kind == ProactivePreparedArtifact.Kind.EXPERIMENT_DRAFT and recommendation_kind == "experiment":
        eligible = _eligible_artifact(
            run=run,
            recommendation=recommendation,
            kind="experiment_draft",
            binding=None,
        )
    elif artifact.kind == ProactivePreparedArtifact.Kind.DRAFT_PR and recommendation_kind in {
        "product_change",
        "instrumentation",
    }:
        binding = _valid_repository_binding(run.repository_binding)
        if binding is None:
            return False
        eligible = _eligible_artifact(
            run=run,
            recommendation=recommendation,
            kind="draft_pr",
            binding=binding.canonical_payload,
        )
    else:
        return False
    return artifact.input_hash == eligible.input_hash


def _artifact_dto(artifact: ProactivePreparedArtifact) -> PreparedArtifactDTO:
    return PreparedArtifactDTO(
        id=artifact.id,
        recommendation_id=artifact.recommendation_id,
        kind=cast(PreparedArtifactKind, artifact.kind),
        status=cast(PreparedArtifactStatus, artifact.status),
        input_hash=artifact.input_hash,
    )


def _pulse_experiment_draft_input(*, artifact: ProactivePreparedArtifact, actor_id: int) -> PulseExperimentDraftInput:
    payload = artifact.recommendation.recommendation
    if not isinstance(payload, dict):
        raise ValueError("experiment recommendation payload is invalid")
    title = payload.get("title")
    target = payload.get("target")
    metric_direction = payload.get("metric_direction")
    expected_metric_movement = payload.get("expected_metric_movement")
    if (
        not isinstance(title, str)
        or not isinstance(target, str)
        or not isinstance(metric_direction, str)
        or not isinstance(expected_metric_movement, str)
    ):
        raise ValueError("experiment recommendation payload is invalid")
    return PulseExperimentDraftInput(
        team_id=artifact.team_id,
        actor_id=actor_id,
        artifact_id=artifact.id,
        title=title,
        target=target,
        metric_direction=metric_direction,
        expected_metric_movement=expected_metric_movement,
    )


def _prepared_experiment_dto(artifact: ProactivePreparedArtifact) -> PreparedExperimentDraftDTO:
    if (
        artifact.experiment_id is None
        or artifact.feature_flag_id is None
        or artifact.url is None
        or artifact.prepared_at is None
    ):
        raise ValueError("prepared experiment artifact is incomplete")
    return PreparedExperimentDraftDTO(
        artifact_id=artifact.id,
        experiment_id=artifact.experiment_id,
        feature_flag_id=artifact.feature_flag_id,
        url=artifact.url,
        prepared_at=artifact.prepared_at,
    )


def _is_sha256(value: str | None) -> bool:
    return value is not None and _SHA256_RE.fullmatch(value) is not None
