"""Collect recent commit activity from a repository's git history.

Boots a short-lived sandbox, makes a minimal history-only clone
(``--shallow-since --filter=blob:none --no-checkout``), runs one
``git log --name-only`` pass, parses it, and destroys the sandbox. No agent
runs; callers get plain data.
"""

import shlex
from dataclasses import dataclass

import structlog

from posthog.models.integration import GitHubIntegration

# Import names only — pulling `Sandbox` at module level would trigger the module's lazy
# resolver and drag the modal/temporal runtime onto the Django startup path.
from products.tasks.backend.logic.services.sandbox import (
    WORKING_DIR,
    SandboxBase,
    SandboxConfig,
    SandboxTemplate,
    get_sandbox_class,
    sandbox_repo_path,
)

logger = structlog.get_logger(__name__)

_RECORD_SEP = "\x01"
_FIELD_SEP = "\x1f"

_CLONE_TIMEOUT_SECONDS = 10 * 60
_LOG_TIMEOUT_SECONDS = 3 * 60

DEFAULT_SINCE_DAYS = 90
DEFAULT_MAX_COMMITS = 5000


class RepositoryCommitActivityError(Exception):
    pass


@dataclass(frozen=True)
class RepositoryCommitActivity:
    """One commit from the repository's recent default-branch history, newest-first."""

    sha: str
    author_name: str
    author_email: str
    committed_at: str  # ISO 8601 author date
    paths: list[str]


def collect_repository_commit_activity(
    team_id: int,
    repository: str,
    *,
    since_days: int = DEFAULT_SINCE_DAYS,
    max_commits: int = DEFAULT_MAX_COMMITS,
) -> list[RepositoryCommitActivity]:
    """Return the repository's commits from the last ``since_days`` days, newest-first.

    Raises :class:`RepositoryCommitActivityError` when no GitHub integration can access
    the repository or the clone/log fails.
    """
    repository = repository.strip().lower()
    github = GitHubIntegration.first_for_team_repository(team_id, repository, source="repo_commit_activity")
    if github is None:
        raise RepositoryCommitActivityError(f"No GitHub integration for team {team_id} can access {repository}")
    github_token = github.get_access_token()

    sandbox = get_sandbox_class().create(
        SandboxConfig(
            name=f"repo-activity-{team_id}",
            template=SandboxTemplate.DEFAULT_BASE,
            environment_variables={},
            snapshot_id=None,
            metadata={"purpose": "repo_commit_activity"},
        )
    )
    try:
        _clone_history(sandbox, repository, github_token, since_days)
        return _read_log(sandbox, repository, since_days, max_commits)
    finally:
        try:
            sandbox.destroy()
        except Exception:
            logger.warning("repo_commit_activity: sandbox destroy failed", sandbox_id=sandbox.id, exc_info=True)


def _clone_history(sandbox: SandboxBase, repository: str, github_token: str, since_days: int) -> None:
    org, repo = repository.split("/")
    repo_url = f"https://x-access-token:{github_token}@github.com/{org}/{repo}.git"
    target_path = sandbox_repo_path(repository)
    org_path = f"{WORKING_DIR}/repos/{org}"
    command = (
        f"rm -rf {shlex.quote(target_path)} && "
        f"mkdir -p {shlex.quote(org_path)} && "
        f"cd {shlex.quote(org_path)} && "
        f"git clone --single-branch --no-checkout --filter=blob:none "
        f"--shallow-since={shlex.quote(f'{since_days} days')} {shlex.quote(repo_url)} {shlex.quote(repo)}"
    )
    result = sandbox.execute(command, timeout_seconds=_CLONE_TIMEOUT_SECONDS)
    if result.exit_code != 0:
        raise RepositoryCommitActivityError(
            f"History clone of {repository} failed with exit code {result.exit_code}: {result.stderr[:300]}"
        )


def _read_log(
    sandbox: SandboxBase, repository: str, since_days: int, max_commits: int
) -> list[RepositoryCommitActivity]:
    target_path = sandbox_repo_path(repository)
    pretty = f"{_RECORD_SEP}%H{_FIELD_SEP}%an{_FIELD_SEP}%ae{_FIELD_SEP}%ad"
    command = (
        f"git -C {shlex.quote(target_path)} log "
        f"--since={shlex.quote(f'{since_days} days')} --no-merges --max-count={max_commits} "
        f"--date=iso-strict --pretty=format:{shlex.quote(pretty)} --name-only"
    )
    result = sandbox.execute(command, timeout_seconds=_LOG_TIMEOUT_SECONDS)
    if result.exit_code != 0:
        raise RepositoryCommitActivityError(
            f"git log of {repository} failed with exit code {result.exit_code}: {result.stderr[:300]}"
        )
    return _parse_log(result.stdout)


def _parse_log(stdout: str) -> list[RepositoryCommitActivity]:
    commits: list[RepositoryCommitActivity] = []
    for record in stdout.split(_RECORD_SEP):
        if not record.strip():
            continue
        header, _, body = record.partition("\n")
        fields = header.split(_FIELD_SEP)
        if len(fields) != 4:
            continue
        sha, author_name, author_email, committed_at = (field.strip() for field in fields)
        if not sha or not author_email:
            continue
        paths = [line.strip() for line in body.splitlines() if line.strip()]
        commits.append(
            RepositoryCommitActivity(
                sha=sha,
                author_name=author_name,
                author_email=author_email,
                committed_at=committed_at,
                paths=paths,
            )
        )
    return commits
