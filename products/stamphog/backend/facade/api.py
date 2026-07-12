"""
Facade for stamphog.

The ONLY module other products are allowed to import.
Accept ids / frozen dataclasses, call into models, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from ..models import DigestChannel, DigestRun, MergedPullRequest, ReviewRun, StamphogRepoConfig
from . import contracts
from .enums import ChannelResolutionSource, DigestRunStatus, ReviewRunStatus, ReviewVerdict


def _repo_config_to_dto(obj: StamphogRepoConfig) -> contracts.RepoConfigDTO:
    return contracts.RepoConfigDTO(
        id=obj.id,
        team_id=obj.team_id,
        provider=obj.provider,
        repository=obj.repository,
        enabled=obj.enabled,
        installation_id=obj.installation_id,
        digest_enabled=obj.digest_enabled,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


def _merged_pr_to_dto(obj: MergedPullRequest) -> contracts.MergedPullRequestDTO:
    return contracts.MergedPullRequestDTO(
        id=obj.id,
        team_id=obj.team_id,
        repo_config_id=obj.repo_config_id,
        repository=obj.repo_config.repository,
        pr_number=obj.pr_number,
        pr_url=obj.pr_url,
        title=obj.title,
        author_login=obj.author_login,
        merged_at=obj.merged_at,
        merge_commit_sha=obj.merge_commit_sha,
        head_branch=obj.head_branch,
        additions=obj.additions,
        deletions=obj.deletions,
        changed_files=obj.changed_files,
        body_excerpt=obj.body_excerpt,
        audience_key=obj.audience_key,
        digest_run_id=obj.digest_run_id,
        delivery_id=obj.delivery_id,
        created_at=obj.created_at,
    )


def _digest_channel_to_dto(obj: DigestChannel) -> contracts.DigestChannelDTO:
    return contracts.DigestChannelDTO(
        id=obj.id,
        team_id=obj.team_id,
        audience_key=obj.audience_key,
        slack_integration_id=obj.slack_integration_id,
        slack_channel_id=obj.slack_channel_id,
        slack_channel_name=obj.slack_channel_name,
        enabled=obj.enabled,
        resolution_source=ChannelResolutionSource(obj.resolution_source),
        last_digest_at=obj.last_digest_at,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


def _digest_run_to_dto(obj: DigestRun) -> contracts.DigestRunDTO:
    return contracts.DigestRunDTO(
        id=obj.id,
        team_id=obj.team_id,
        digest_channel_id=obj.digest_channel_id,
        status=DigestRunStatus(obj.status),
        pr_count=obj.pr_count,
        summary=obj.summary,
        slack_message_ts=obj.slack_message_ts,
        error=obj.error,
        created_at=obj.created_at,
        posted_at=obj.posted_at,
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
        head_branch=obj.head_branch,
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


def get_digest_channel(team_id: int, digest_channel_id: str) -> contracts.DigestChannelDTO | None:
    obj = DigestChannel.objects.for_team(team_id).filter(id=digest_channel_id).first()
    return _digest_channel_to_dto(obj) if obj is not None else None


def get_digest_run(team_id: int, digest_run_id: str) -> contracts.DigestRunDTO | None:
    obj = DigestRun.objects.for_team(team_id).filter(id=digest_run_id).first()
    return _digest_run_to_dto(obj) if obj is not None else None


def get_merged_pull_request(team_id: int, merged_pull_request_id: str) -> contracts.MergedPullRequestDTO | None:
    obj = (
        MergedPullRequest.objects.for_team(team_id)
        .filter(id=merged_pull_request_id)
        .select_related("repo_config")
        .first()
    )
    return _merged_pr_to_dto(obj) if obj is not None else None
