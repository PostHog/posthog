"""
Facade for stamphog.

The ONLY module other products are allowed to import.
Accept ids / frozen dataclasses, call into models, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from ..models import ReviewRun, StamphogRepoConfig
from . import contracts
from .enums import ReviewRunStatus, ReviewVerdict


def _repo_config_to_dto(obj: StamphogRepoConfig) -> contracts.RepoConfigDTO:
    return contracts.RepoConfigDTO(
        id=obj.id,
        team_id=obj.team_id,
        repository=obj.repository,
        enabled=obj.enabled,
        github_installation_id=obj.github_installation_id,
        policy_overrides=obj.policy_overrides,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


def _review_run_to_dto(obj: ReviewRun) -> contracts.ReviewRunDTO:
    return contracts.ReviewRunDTO(
        id=obj.id,
        team_id=obj.team_id,
        repo_config_id=obj.repo_config_id,
        repository=obj.repo_config.repository,
        pr_number=obj.pr_number,
        pr_url=obj.pr_url,
        head_sha=obj.head_sha,
        status=ReviewRunStatus(obj.status),
        verdict=ReviewVerdict(obj.verdict),
        delivery_id=obj.delivery_id,
        gate_result=obj.gate_result,
        output=obj.output,
        error=obj.error,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
        completed_at=obj.completed_at,
    )


def get_repo_config(team_id: int, repository: str) -> contracts.RepoConfigDTO | None:
    obj = StamphogRepoConfig.objects.for_team(team_id).filter(repository=repository).first()
    return _repo_config_to_dto(obj) if obj is not None else None


def get_review_run(team_id: int, review_run_id: str) -> contracts.ReviewRunDTO | None:
    obj = ReviewRun.objects.for_team(team_id).filter(id=review_run_id).select_related("repo_config").first()
    return _review_run_to_dto(obj) if obj is not None else None


def create_review_run(
    *,
    team_id: int,
    repo_config_id: str,
    pr_number: int,
    pr_url: str,
    head_sha: str,
    delivery_id: str | None = None,
) -> contracts.ReviewRunDTO:
    obj = ReviewRun.objects.for_team(team_id).create(
        team_id=team_id,
        repo_config_id=repo_config_id,
        pr_number=pr_number,
        pr_url=pr_url,
        head_sha=head_sha,
        delivery_id=delivery_id,
    )
    return _review_run_to_dto(obj)
