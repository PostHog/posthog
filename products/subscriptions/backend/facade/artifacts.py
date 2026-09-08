"""Durable, policy-owned claims for one proactive recommendation artifact."""

from __future__ import annotations

import re
import json
import hashlib
from typing import Literal
from uuid import UUID

from django.db import transaction

from posthog.dataclasses import frozen

from products.subscriptions.backend.models import (
    ProactivePreparedArtifact,
    ProactiveRecommendation,
    ProactiveRecommendationRun,
)
from products.tasks.backend.facade.repository_authorization import revalidate_staged_repository_binding

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

        eligible = _select_eligible_artifact(run=run)
        artifact = ProactivePreparedArtifact.objects.for_team(input.team_id).filter(run_id=run.id).first()
        if artifact is not None:
            if eligible is None or not _matches_replay(artifact=artifact, eligible=eligible, run=run):
                raise ValueError("artifact replay does not match its durable claim")
            return _artifact_dto(artifact)
        if eligible is None:
            return None

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
    with transaction.atomic():
        artifact = (
            ProactivePreparedArtifact.objects.for_team(input.team_id)
            .select_for_update()
            .filter(id=input.artifact_id)
            .first()
        )
        if artifact is None:
            raise ValueError("prepared artifact was not found")
        artifact.status = ProactivePreparedArtifact.Status.FAILED
        artifact.failure_code = input.failure_code[:128]
        artifact.save(update_fields=["status", "failure_code", "updated_at"])
        return _artifact_dto(artifact)


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
                kind=ProactivePreparedArtifact.Kind.EXPERIMENT_DRAFT,
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
            kind=ProactivePreparedArtifact.Kind.DRAFT_PR,
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


def _matches_replay(
    *, artifact: ProactivePreparedArtifact, eligible: _EligibleArtifact, run: ProactiveRecommendationRun
) -> bool:
    return (
        artifact.team_id == run.team_id
        and artifact.run_id == run.id
        and artifact.recommendation_id == eligible.recommendation.id
        and artifact.kind == eligible.kind
        and artifact.artifact_config_hash == run.artifact_config_hash
        and artifact.input_hash == eligible.input_hash
    )


def _artifact_dto(artifact: ProactivePreparedArtifact) -> PreparedArtifactDTO:
    return PreparedArtifactDTO(
        id=artifact.id,
        recommendation_id=artifact.recommendation_id,
        kind=artifact.kind,
        status=artifact.status,
        input_hash=artifact.input_hash,
    )


def _is_sha256(value: str | None) -> bool:
    return value is not None and _SHA256_RE.fullmatch(value) is not None
