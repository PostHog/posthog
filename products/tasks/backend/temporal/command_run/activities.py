import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from temporalio import activity

from posthog.models.integration import GitHubIntegration, Integration
from posthog.temporal.common.utils import asyncify, close_db_connections

from products.tasks.backend.models import TaskRun
from products.tasks.backend.services.sandbox import WORKING_DIR, Sandbox
from products.tasks.backend.temporal.observability import log_with_activity_context

if TYPE_CHECKING:
    from products.tasks.backend.services.sandbox import SandboxBase


@dataclass
class RunCommandInSandboxInput:
    run_id: str
    sandbox_id: str
    command: str
    repository: Optional[str] = None
    timeout_seconds: int = 30 * 60


@dataclass
class RunCommandOutput:
    exit_code: int


@dataclass
class CommitAndOpenPrInput:
    run_id: str
    sandbox_id: str
    repository: str
    github_integration_id: int
    branch: str
    commit_message: str
    pr_title: str
    pr_body: str
    base_branch: Optional[str] = None


@dataclass
class OpenPrOutput:
    created_pr: bool
    pr_url: Optional[str] = None
    commit_sha: Optional[str] = None


def open_signed_pr(
    sandbox: "SandboxBase",
    github: GitHubIntegration,
    *,
    repository: str,
    branch: str,
    base_branch: Optional[str],
    commit_headline: str,
    pr_title: str,
    pr_body: str,
) -> OpenPrOutput:
    """Stage the sandbox changes and open a PR backed by a GitHub-signed commit.

    The sandbox image blocks raw git commit/push (only signed commits may leave), so we
    collect the diff and create a verified commit via the GitHub API instead. Returns
    early without a PR when the command left the repo unchanged. Shared by the Temporal
    activity and the local management command so the orchestration lives in one place.
    """
    try:
        github.organization()
    except ValueError as e:
        raise RuntimeError(
            "GitHub integration is not a connected App installation (missing account/org); cannot open a PR."
        ) from e

    is_clean, _ = sandbox.is_git_clean(repository)
    if is_clean:
        return OpenPrOutput(created_pr=False)

    changes = sandbox.stage_and_collect_changes(repository)
    if not changes.additions and not changes.deletions:
        return OpenPrOutput(created_pr=False)

    # GitHub resolves the org from the installation, so it wants the bare repo name.
    repo_name = repository.split("/")[-1]
    resolved_base = base_branch or github.get_default_branch(repo_name)

    branch_result = github.create_branch(repo_name, branch, resolved_base)
    if not branch_result.get("success"):
        raise RuntimeError(f"Failed to create branch: {branch_result.get('error')}")

    commit_result = github.create_signed_commit(
        repository=repo_name,
        branch=branch,
        expected_head_oid=branch_result["sha"],
        headline=commit_headline,
        additions=changes.additions,
        deletions=changes.deletions,
    )
    if not commit_result.get("success"):
        raise RuntimeError(f"Failed to create signed commit: {commit_result.get('error')}")

    pr_result = github.create_pull_request(
        repository=repo_name,
        title=pr_title,
        body=pr_body,
        head_branch=branch,
        base_branch=resolved_base,
    )
    if not pr_result.get("success"):
        raise RuntimeError(f"Failed to open pull request: {pr_result.get('error')}")

    return OpenPrOutput(created_pr=True, pr_url=pr_result["pr_url"], commit_sha=commit_result["commit_sha"])


def resolve_github_integration(github_integration_id: int) -> GitHubIntegration:
    integration = Integration.objects.get(id=github_integration_id)
    github = GitHubIntegration(integration)
    if github.access_token_expired():
        github.refresh_access_token()
    return github


@activity.defn
@asyncify
@close_db_connections
def run_command_in_sandbox(input: RunCommandInSandboxInput) -> RunCommandOutput:
    """Run the cloud run's CLI command inside an already-provisioned sandbox.

    The command runs from the cloned repository's directory so it can mutate the
    checkout directly. Output is streamed to logs only — never returned to the
    caller or stored on the run.
    """
    sandbox = Sandbox.get_by_id(input.sandbox_id)

    command = input.command
    if input.repository:
        org, repo = input.repository.lower().split("/", 1)
        repo_path = f"{WORKING_DIR}/repos/{org}/{repo}"
        command = f"cd {shlex.quote(repo_path)} && {input.command}"

    log_with_activity_context("command_run_started", run_id=input.run_id, repository=input.repository)

    stream = sandbox.execute_stream(command, timeout_seconds=input.timeout_seconds)
    for line in stream.iter_stdout():
        log_with_activity_context("command_run_output", run_id=input.run_id, line=line[:2000])
    result = stream.wait()

    if result.stderr:
        log_with_activity_context("command_run_stderr", run_id=input.run_id, stderr=result.stderr[:4000])
    log_with_activity_context("command_run_finished", run_id=input.run_id, exit_code=result.exit_code)
    return RunCommandOutput(exit_code=result.exit_code)


@activity.defn
@asyncify
@close_db_connections
def commit_and_open_pr(input: CommitAndOpenPrInput) -> OpenPrOutput:
    """Open a PR for the sandbox changes via a GitHub-signed commit and record its URL.

    Returns early without a PR when the command left the repo clean. Only the PR URL and
    commit SHA are written to `TaskRun.output` — logs are never surfaced.
    """
    sandbox = Sandbox.get_by_id(input.sandbox_id)
    github = resolve_github_integration(input.github_integration_id)

    result = open_signed_pr(
        sandbox,
        github,
        repository=input.repository,
        branch=input.branch,
        base_branch=input.base_branch,
        commit_headline=input.commit_message,
        pr_title=input.pr_title,
        pr_body=input.pr_body,
    )

    if not result.created_pr:
        log_with_activity_context("command_run_no_changes", run_id=input.run_id, repository=input.repository)
        return result

    TaskRun.update_output_atomic(input.run_id, {"pr_url": result.pr_url, "commit_sha": result.commit_sha})
    log_with_activity_context("command_run_pr_opened", run_id=input.run_id, pr_url=result.pr_url)
    return result
