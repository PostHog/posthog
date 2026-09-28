"""Decide whether a new release gets a stored file list, and queue the job that stores it."""

from typing import Literal

from django.db import transaction

import structlog

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.ph_client import feature_enabled_or_false

from products.error_tracking.backend.logic.repo_paths.metrics import record_job_outcome
from products.error_tracking.backend.logic.repo_paths.slug import RepoSlug, is_full_commit_sha, repo_slug
from products.error_tracking.backend.models import ErrorTrackingRelease

logger = structlog.get_logger(__name__)

REPO_PATHS_FLAG = "error-tracking-repo-paths"


@frozen
class ReleaseRepo:
    slug: RepoSlug
    commit: str


def parse_release_repo(metadata: object) -> ReleaseRepo | Literal["no_git_metadata", "short_sha"]:
    git = metadata.get("git") if isinstance(metadata, dict) else None
    remote_url = git.get("remote_url") if isinstance(git, dict) else None
    slug = repo_slug(remote_url) if isinstance(remote_url, str) else None
    if git is None or slug is None:
        return "no_git_metadata"
    commit = git.get("commit_id")
    commit = commit.strip().lower() if isinstance(commit, str) else commit
    if not is_full_commit_sha(commit):
        return "short_sha"
    return ReleaseRepo(slug=slug, commit=commit)


def repo_paths_enabled(team_id: int) -> bool:
    # Bucket child environments with their parent project, as the other error tracking flags do.
    project_id = resolve_effective_team_id(team_id)
    return feature_enabled_or_false(
        REPO_PATHS_FLAG,
        str(project_id),
        groups={"project": str(project_id)},
        group_properties={"project": {"id": str(project_id)}},
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )


def schedule_release_file_list(release: ErrorTrackingRelease) -> None:
    """Queue the job that stores the file list of the release commit, once the release commits.

    The flag is checked inside the job, so creating a release never waits on the flags service.
    """
    repo = parse_release_repo(release.metadata)
    if not isinstance(repo, ReleaseRepo):
        record_job_outcome(repo)
        return
    team_id = release.team_id
    release_id = str(release.id)

    def _enqueue() -> None:
        # The task module imports the Temporal package, which loads worker-only modules.
        from products.error_tracking.backend.tasks.tasks import start_error_tracking_repo_paths_job  # noqa: PLC0415

        try:
            start_error_tracking_repo_paths_job.delay(team_id=team_id, release_id=release_id)
        except Exception:
            # The release is saved. A broker outage costs this release its file list, and nothing else.
            logger.exception("error_tracking_repo_paths_enqueue_failed", team_id=team_id, release_id=release_id)

    transaction.on_commit(_enqueue, robust=True)
