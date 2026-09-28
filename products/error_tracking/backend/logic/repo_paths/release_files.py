"""Store the file list of a release commit in object storage, for cymbal-path-resolution to read."""

from collections.abc import Callable
from functools import partial
from typing import Literal
from urllib.parse import urlsplit

from django.conf import settings

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import EgressBudgetExhausted
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration, Integration
from posthog.security.url_validation import is_url_allowed

from products.error_tracking.backend.logic.repo_paths.fetch_budget import GitFetchBudgetOwner, consume_git_fetch_budget
from products.error_tracking.backend.logic.repo_paths.git_lister import (
    GitAuthFailed,
    GitCommitNotFound,
    GitFailed,
    GitFetchTarget,
    GitHostNotAllowed,
    GitRemote,
    GitTimeout,
    GitTooLarge,
    github_auth_header,
    gitlab_auth_header,
    list_repository_files,
)
from products.error_tracking.backend.logic.repo_paths.metrics import record_file_list_size
from products.error_tracking.backend.logic.repo_paths.release_repo import ReleaseRepo, parse_release_repo
from products.error_tracking.backend.logic.repo_paths.slug import RepoSlug
from products.error_tracking.backend.logic.repo_paths.storage import (
    file_list_exists,
    remove_old_file_lists,
    repo_paths_key,
    write_file_list,
)
from products.error_tracking.backend.models import ErrorTrackingRelease

RepoPathsOutcome = Literal[
    "written",
    "exists",
    "no_release",
    "no_git_metadata",
    "short_sha",
    "no_integration",
    "auth_failed",
    "commit_not_found",
    "too_large",
    "host_not_allowed",
    "budget_exhausted",
]

_SOURCE = "error_tracking_repo_paths"
_GITHUB_HOST = "github.com"
# Only what a clone needs, so a leaked token can read this one repository and nothing else.
_GITHUB_TOKEN_PERMISSIONS = {"contents": "read", "metadata": "read"}


class RepoPathsRetryableError(Exception):
    def __init__(self, outcome: Literal["timeout", "error"], message: str) -> None:
        super().__init__(message)
        self.outcome = outcome


@frozen
class _GitSource:
    url: str
    budget_owner: GitFetchBudgetOwner
    # Minting a GitHub token costs an API call, so it happens only after the fetch budget admits the fetch.
    auth_header: Callable[[], str]


def store_release_file_list(team_id: int, release_id: str) -> RepoPathsOutcome:
    """Fetch and store the file list of one release commit.

    Returns the outcome for every result that an immediate retry cannot change. The workflow tries a
    ``budget_exhausted`` job again after the budget frees up. Raises ``RepoPathsRetryableError`` for a
    timeout, an unexpected git failure, or a GitHub server error.
    """
    release = ErrorTrackingRelease.objects.filter(team_id=team_id, id=release_id).first()
    if release is None:
        return "no_release"
    repo = parse_release_repo(release.metadata)
    if not isinstance(repo, ReleaseRepo):
        return repo
    key = repo_paths_key(team_id, repo.slug, repo.commit)
    if file_list_exists(key):
        # A retry after a worker died between the write and the cleanup lands here, so clean up again.
        remove_old_file_lists(team_id, repo.slug, keep=settings.ERROR_TRACKING_REPO_PATHS_KEEP_PER_REPO)
        return "exists"

    try:
        source = _git_source(team_id, repo.slug)
        if source is None:
            return "no_integration"
        if not consume_git_fetch_budget(source.budget_owner, priority=Priority.BATCH):
            return "budget_exhausted"
        remote = GitRemote(url=source.url, auth_header=source.auth_header())
    except (EgressBudgetExhausted, GitHubRateLimitError):
        return "budget_exhausted"
    except GitHubIntegrationError as e:
        if e.status_code is not None and e.status_code >= 500:
            raise RepoPathsRetryableError("error", str(e)) from e
        return "auth_failed"

    target = GitFetchTarget(
        remote=remote,
        commit=repo.commit,
        max_bytes=settings.ERROR_TRACKING_REPO_PATHS_MAX_FETCH_BYTES,
        timeout_seconds=settings.ERROR_TRACKING_REPO_PATHS_FETCH_TIMEOUT_SECONDS,
    )
    try:
        listed = list_repository_files(target)
    except GitAuthFailed:
        return "auth_failed"
    except GitCommitNotFound:
        return "commit_not_found"
    except GitTooLarge:
        return "too_large"
    except GitHostNotAllowed:
        return "host_not_allowed"
    except (GitTimeout, GitFailed) as e:
        raise RepoPathsRetryableError(e.outcome, str(e)) from e

    if len(listed.paths) > settings.ERROR_TRACKING_REPO_PATHS_MAX_PATHS:
        return "too_large"
    write_file_list(key, listed.paths)
    record_file_list_size(len(listed.paths))
    remove_old_file_lists(team_id, repo.slug, keep=settings.ERROR_TRACKING_REPO_PATHS_KEEP_PER_REPO)
    return "written"


def _git_source(team_id: int, slug: RepoSlug) -> _GitSource | None:
    # The URL always comes from the integration. Release metadata is written by the team's CI, so
    # it only selects which of the team's own integrations to use.
    if slug.host == _GITHUB_HOST:
        return _github_source(team_id, slug)
    return _gitlab_source(team_id, slug)


def _github_source(team_id: int, slug: RepoSlug) -> _GitSource | None:
    owner, _, name = slug.path.partition("/")
    if not owner or not name or "/" in name:
        return None
    github = GitHubIntegration.first_for_team_repository(team_id, slug.path, source=_SOURCE, priority=Priority.BATCH)
    installation_id = github.github_installation_id if github is not None else None
    if github is None or not installation_id:
        return None
    return _GitSource(
        url=f"https://{_GITHUB_HOST}/{owner}/{name}.git",
        budget_owner=GitFetchBudgetOwner(provider="github", owner_id=str(installation_id)),
        auth_header=lambda: github_auth_header(
            github.mint_scoped_installation_token(_GITHUB_TOKEN_PERMISSIONS, repositories=[name])
        ),
    )


def _gitlab_source(team_id: int, slug: RepoSlug) -> _GitSource | None:
    for integration in Integration.objects.filter(team_id=team_id, kind="gitlab").order_by("id"):
        config = integration.config or {}
        hostname = config.get("hostname")
        path = config.get("path_with_namespace")
        token = (integration.sensitive_config or {}).get("access_token")
        if not isinstance(hostname, str) or not isinstance(path, str) or not isinstance(token, str) or not token:
            continue
        base = urlsplit(hostname)
        host = (base.hostname or "").lower()
        if base.scheme != "https" or host != slug.host or path.lower() != slug.path.lower():
            continue
        port = f":{base.port}" if base.port else ""
        url = f"https://{host}{port}/{path}.git"
        allowed, _ = is_url_allowed(url)
        if not allowed:
            continue
        return _GitSource(
            url=url,
            budget_owner=GitFetchBudgetOwner(provider="gitlab", owner_id=f"{host}/{config.get('project_id')}"),
            auth_header=partial(gitlab_auth_header, token),
        )
    return None
