"""Collect recent commit activity from a repository's git history.

Boots a short-lived sandbox, makes a minimal history-only clone
(``--shallow-since --filter=blob:none --no-checkout``), runs one
``git log --name-only`` pass, parses it, and destroys the sandbox. No agent
runs; callers get plain data.
"""

import re
import shlex
from dataclasses import dataclass

import structlog

from posthog.egress.limiter.policies import Priority
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
# Hard byte cap on git log output: sandbox.execute reads all stdout into the worker, and
# --max-count bounds commits, not paths — one pathological tree-wide commit could otherwise
# balloon the transfer. ~3x a very active monorepo's real 90-day output (~20MB).
_MAX_LOG_BYTES = 64 * 1024 * 1024

DEFAULT_SINCE_DAYS = 90
# Runaway backstop only — sized well above a very active monorepo's 90-day non-merge count
# (posthog/posthog ≈ 8k). Truncating newest-first would silently drop the window's older
# half, making its contributors look fully stale instead of decayed.
DEFAULT_MAX_COMMITS = 20_000

# Protocol v2 (GitHub) reports the server's refusal as a shallow-info error; v0 names it.
_EMPTY_SHALLOW_WINDOW_RE = re.compile(r"error processing shallow info|no commits selected for shallow requests")


class RepositoryCommitActivityError(Exception):
    pass


@dataclass(frozen=True)
class RepositoryCommitActivity:
    """One commit from the repository's recent default-branch history, newest-first.

    Deliberately no author name/email: commit metadata is attacker-controlled free text
    that could embed the parser's delimiters and forge records. Identity comes from
    GitHub's sha→login attribution; the parsed format contains only sha and date.
    """

    sha: str
    committed_at: str  # ISO 8601 committer date — same axis the --since filter selects on
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
    github = GitHubIntegration.first_for_team_repository(
        team_id, repository, source="repo_commit_activity", priority=Priority.BATCH
    )
    if github is None:
        raise RepositoryCommitActivityError(f"No GitHub integration for team {team_id} can access {repository}")
    github_token = github.get_access_token()

    sandbox = get_sandbox_class().create(
        SandboxConfig(
            name=f"repo-activity-{team_id}",
            # Git-only job, no agent server — the slim image boots faster (stamphog precedent).
            template=SandboxTemplate.SLIM_BASE,
            # The token reaches the clone URL via ${GITHUB_TOKEN} expansion inside the
            # sandbox — never in the command string, which sandbox provider/timeout
            # exceptions carry into logs and exception capture unredacted.
            environment_variables={"GITHUB_TOKEN": github_token},
            snapshot_id=None,
            metadata={"purpose": "repo_commit_activity"},
        )
    )
    try:
        if not _clone_history(sandbox, repository, github_token, since_days):
            return []
        return _read_log(sandbox, repository, since_days, max_commits)
    finally:
        try:
            sandbox.destroy()
        except Exception:
            logger.warning("repo_commit_activity: sandbox destroy failed", sandbox_id=sandbox.id, exc_info=True)


def _clone_history(sandbox: SandboxBase, repository: str, github_token: str, since_days: int) -> bool:
    """Clone the window's history. Return False when the default branch has no commits in the window."""
    result = sandbox.execute(
        _clone_command(repository, f"--shallow-since={shlex.quote(f'{since_days} days')}"),
        timeout_seconds=_CLONE_TIMEOUT_SECONDS,
    )
    if result.exit_code == 0:
        return True
    # Git argv sees the expanded URL, so fatal messages can still echo the token.
    stderr = result.stderr.replace(github_token, "<redacted>") if github_token else result.stderr
    # The server refuses --shallow-since when no commit falls inside the window. Accept an
    # empty result only after a tip-only clone proves the latest commit predates the window.
    if _EMPTY_SHALLOW_WINDOW_RE.search(stderr) and _tip_predates_window(sandbox, repository, since_days):
        logger.info("repo_commit_activity: no commits inside the window", repository=repository, since_days=since_days)
        return False
    raise RepositoryCommitActivityError(
        f"History clone of {repository} failed with exit code {result.exit_code}: {stderr[:300]}"
    )


def _tip_predates_window(sandbox: SandboxBase, repository: str, since_days: int) -> bool:
    target_path = sandbox_repo_path(repository)
    command = (
        f"{_clone_command(repository, '--depth=1')} && "
        f"git -C {shlex.quote(target_path)} log -1 --since={shlex.quote(f'{since_days} days')} --format=%H"
    )
    result = sandbox.execute(command, timeout_seconds=_CLONE_TIMEOUT_SECONDS)
    return result.exit_code == 0 and not result.stdout.strip()


def _clone_command(repository: str, history_option: str) -> str:
    # `repository` passed first_for_team_repository's safe-path check, so it's plain
    # owner/repo and safe inside double quotes. The token placeholder expands from the
    # sandbox environment; the command string itself never contains the credential.
    org, repo = repository.split("/")
    repo_url = f'"https://x-access-token:${{GITHUB_TOKEN}}@github.com/{org}/{repo}.git"'
    target_path = sandbox_repo_path(repository)
    org_path = f"{WORKING_DIR}/repos/{org}"
    return (
        f"rm -rf {shlex.quote(target_path)} && "
        f"mkdir -p {shlex.quote(org_path)} && "
        f"cd {shlex.quote(org_path)} && "
        f"git clone --single-branch --no-checkout --filter=blob:none "
        f"{history_option} {repo_url} {shlex.quote(repo)}"
    )


def _read_log(
    sandbox: SandboxBase, repository: str, since_days: int, max_commits: int
) -> list[RepositoryCommitActivity]:
    target_path = sandbox_repo_path(repository)
    # %cd (committer date): the same axis --since filters on, and when the change landed.
    # No free-form fields (%an/%ae): commit metadata can embed the delimiters and forge
    # records; sha and date are further shape-validated in _parse_log.
    pretty = f"{_RECORD_SEP}%H{_FIELD_SEP}%cd"
    log_command = (
        f"git -C {shlex.quote(target_path)} log "
        # --no-renames: inexact rename detection compares blob contents, which a blobless
        # clone fetches over the network per candidate pair; a rename crediting both the
        # old and new path's areas is also better data for activity mapping.
        f"--since={shlex.quote(f'{since_days} days')} --no-merges --no-renames --max-count={max_commits} "
        f"--date=iso-strict --pretty=format:{shlex.quote(pretty)} --name-only"
    )
    # Stage to a file and ship at most _MAX_LOG_BYTES+1 back: the worker reads all stdout
    # into memory, so the byte cap is enforced sandbox-side. The sentinel extra byte
    # distinguishes "exactly at the limit" from "truncated"; && preserves git's exit code.
    command = f"{log_command} > /tmp/repo-activity.log && head -c {_MAX_LOG_BYTES + 1} /tmp/repo-activity.log"
    result = sandbox.execute(command, timeout_seconds=_LOG_TIMEOUT_SECONDS)
    if result.exit_code != 0:
        raise RepositoryCommitActivityError(
            f"git log of {repository} failed with exit code {result.exit_code}: {result.stderr[:300]}"
        )
    if len(result.stdout.encode()) > _MAX_LOG_BYTES:
        raise RepositoryCommitActivityError(
            f"git log of {repository} exceeded {_MAX_LOG_BYTES} bytes; refusing to build a truncated map"
        )
    return _parse_log(result.stdout)


_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}|Z)$")


def _parse_log(stdout: str) -> list[RepositoryCommitActivity]:
    commits: list[RepositoryCommitActivity] = []
    for record in stdout.split(_RECORD_SEP):
        if not record.strip():
            continue
        header, _, body = record.partition("\n")
        fields = header.split(_FIELD_SEP)
        if len(fields) != 2:
            continue
        sha, committed_at = (field.strip() for field in fields)
        # Strict shape validation: only records that look exactly like git's own output
        # join against GitHub attribution.
        if not _SHA_RE.match(sha) or not _ISO_DATE_RE.match(committed_at):
            continue
        paths = [line.strip() for line in body.splitlines() if line.strip()]
        commits.append(RepositoryCommitActivity(sha=sha, committed_at=committed_at, paths=paths))
    return commits
