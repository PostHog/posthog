"""
Facade for stamphog.

The ONLY module other products are allowed to import.
Accept ids / frozen dataclasses, call into models, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from ..models import DigestChannel, DigestRun, PullRequest, ReviewRun, StamphogRepoConfig
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


def _pull_request_to_dto(obj: PullRequest) -> contracts.PullRequestDTO:
    return contracts.PullRequestDTO(
        id=obj.id,
        team_id=obj.team_id,
        repo_config_id=obj.repo_config_id,
        repository=obj.repo_config.repository,
        pr_number=obj.pr_number,
        pr_url=obj.pr_url,
        title=obj.title,
        author_login=obj.author_login,
        head_branch=obj.head_branch,
        body_excerpt=obj.body_excerpt,
        additions=obj.additions,
        deletions=obj.deletions,
        changed_files=obj.changed_files,
        audience_key=obj.audience_key,
        merge_commit_sha=obj.merge_commit_sha,
        merged_at=obj.merged_at,
        digest_run_id=obj.digest_run_id,
        posted_comment_id=obj.posted_comment_id,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
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
        pull_request_id=obj.pull_request_id,
        repository=obj.pull_request.repo_config.repository,
        pr_number=obj.pull_request.pr_number,
        pr_url=obj.pull_request.pr_url,
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


def has_reviewable_repo_config(team_id: int) -> bool:
    """Whether the team has at least one repo hosted reviews can actually run on (synced + enabled).

    "Synced" means the config was bound through the authenticated sync flow: a non-blank
    installation_id AND a connecting user (the principal the sandbox LLM credential is minted
    under — reviews fail closed without one). Drives the Code review scene's Stamphog inbox
    toggle: when this is false, the toggle has nothing to act on and renders disabled.
    """
    return (
        StamphogRepoConfig.objects.for_team(team_id)
        .filter(enabled=True, connected_by_user_id__isnull=False)
        .exclude(installation_id="")
        .exists()
    )


def queue_inbox_pr_review(
    *,
    team_id: int,
    pr_url: str,
    acting_user_id: int,
    signal_report_id: str,
    task_run_id: str,
) -> None:
    """Queue the initial hosted Stamphog review of a self-driving inbox PR (fire-and-forget).

    The programmatic entry for review_hog's inbox trigger: the caller has already resolved the
    acting reviewer and checked their ``stamphog_review_inbox_prs`` toggle. Everything else —
    resolving a synced+enabled repo config for the PR's repository (silent no-op without one),
    fetching the PR, creating the run with inbox provenance, starting the workflow — happens in
    a Celery task so the caller's save path never blocks on GitHub or the product DB.
    """
    # Deferred: the Celery task module drags the GitHub client and temporal client onto the
    # import path, which must stay off this facade's light import surface (review_hog's API
    # serializer imports it for has_reviewable_repo_config).
    from products.stamphog.backend.tasks.tasks import process_inbox_pr_review  # noqa: PLC0415

    process_inbox_pr_review.delay(
        team_id=team_id,
        pr_url=pr_url,
        acting_user_id=acting_user_id,
        signal_report_id=signal_report_id,
        task_run_id=task_run_id,
    )


def get_review_run(team_id: int, review_run_id: str) -> contracts.ReviewRunDTO | None:
    obj = (
        ReviewRun.objects.for_team(team_id).filter(id=review_run_id).select_related("pull_request__repo_config").first()
    )
    return _review_run_to_dto(obj) if obj is not None else None


def create_review_run(
    *,
    team_id: int,
    pull_request_id: str,
    head_sha: str,
    delivery_id: str | None = None,
) -> contracts.ReviewRunDTO:
    # Resolve the PR through the team scope rather than trusting the raw FK id: a caller passing
    # another team's pull_request_id would otherwise create a run whose reads follow the FK across
    # the tenant boundary (get_review_run would surface the other team's repo and PR details).
    pull_request = PullRequest.objects.for_team(team_id).get(id=pull_request_id)
    obj = ReviewRun.objects.for_team(team_id).create(
        team_id=team_id,
        pull_request=pull_request,
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


def get_pull_request(team_id: int, pull_request_id: str) -> contracts.PullRequestDTO | None:
    obj = PullRequest.objects.for_team(team_id).filter(id=pull_request_id).select_related("repo_config").first()
    return _pull_request_to_dto(obj) if obj is not None else None
