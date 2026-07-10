"""Temporal activities for the stamphog review workflow.

Each activity is keyed only by ``StamphogReviewInput`` (review_run_id + team_id) and
re-loads the ``ReviewRun`` it needs. Bulky data (the PR payload, changed files, fetched
policy files, raw reviewer output) is persisted on ``ReviewRun.output`` between steps
rather than threaded through the workflow, keeping every Temporal payload well under the
~2 MiB limit.
"""

from __future__ import annotations

import shlex
import base64
from collections.abc import Sequence
from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.stamphog.backend.facade.enums import ReviewRunStatus, ReviewVerdict
from products.stamphog.backend.logic.gates import GateInput, run_gates
from products.stamphog.backend.logic.github_client import StamphogGitHubClient
from products.stamphog.backend.logic.policy import load_policy
from products.stamphog.backend.logic.reviewer import build_reviewer_invocation, parse_reviewer_output
from products.stamphog.backend.models import ReviewRun
from products.stamphog.backend.temporal.constants import (
    STAMPHOG_POLICY_PATHS,
    STAMPHOG_REVIEW_GUIDANCE_PATH,
    STAMPHOG_SANDBOX_REPO_DIR,
)
from products.tasks.backend.facade.sandbox import SandboxBase, SandboxConfig, get_sandbox_class_for_backend


@dataclass
class StamphogReviewInput:
    review_run_id: str
    team_id: int


@dataclass
class MarkReviewFailedInput:
    review_run_id: str
    team_id: int
    error: str


def _load_run(input: StamphogReviewInput) -> ReviewRun:
    return ReviewRun.objects.for_team(input.team_id).select_related("repo_config").get(id=input.review_run_id)


def _resolve_sandbox_backend() -> str:
    """Map the shared ``SANDBOX_PROVIDER`` setting onto a get_sandbox_class_for_backend key.

    Unset means the production default (Modal); local dev sets ``docker`` or ``MODAL_DOCKER``.
    """
    provider = getattr(settings, "SANDBOX_PROVIDER", None)
    return provider if provider else "modal"


@activity.defn
@asyncify
def fetch_review_context(input: StamphogReviewInput) -> dict:
    """Load the PR, its changed files, and default-branch policy files onto the run."""
    run = _load_run(input)
    repo_config = run.repo_config
    repo = repo_config.repository

    client = StamphogGitHubClient(repo_config.installation_id)
    pr = client.get_pr(repo, run.pr_number)
    files = client.get_pr_files(repo, run.pr_number)

    policy_files: dict[str, str] = {}
    for path in STAMPHOG_POLICY_PATHS:
        content = client.get_default_branch_file(repo, path)
        if content is not None:
            policy_files[path] = content

    run.output = {**(run.output or {}), "pr": pr, "files": files, "policy_files": policy_files}
    run.save(update_fields=["output", "updated_at"])

    activity.logger.info(f"Fetched review context for run {run.id} (pr #{run.pr_number}, {len(files)} files)")
    return {"pr_number": run.pr_number, "file_count": len(files), "head_sha": run.head_sha}


@activity.defn
@asyncify
def run_gates_activity(input: StamphogReviewInput) -> dict:
    """Run the pure gate checks; on a block, post a sticky comment and finish the run."""
    run = _load_run(input)
    repo_config = run.repo_config
    output = run.output or {}
    pr = output.get("pr", {})
    files = output.get("files", [])
    policy_files = output.get("policy_files", {})

    policy = load_policy(policy_files)
    gate_input = GateInput(pr=pr, files=files, policy=policy, is_draft=bool(pr.get("draft", False)))
    result = run_gates(gate_input)

    run.gate_result = {
        "passed": result.passed,
        "tier": result.tier,
        "reason": result.reason,
        "details": result.details,
    }

    if not result.passed:
        client = StamphogGitHubClient(repo_config.installation_id)
        comment = client.upsert_sticky_comment(
            repo_config.repository,
            run.pr_number,
            _gate_block_comment(result.tier, result.reason),
        )
        run.status = ReviewRunStatus.COMPLETED
        run.verdict = ReviewVerdict.WAIT
        run.completed_at = timezone.now()
        run.verdict_posted_at = run.completed_at
        run.posted_comment_id = _comment_id(comment)
        run.save(
            update_fields=[
                "gate_result",
                "status",
                "verdict",
                "completed_at",
                "verdict_posted_at",
                "posted_comment_id",
                "updated_at",
            ]
        )
        activity.logger.info(f"Gates blocked run {run.id} at tier {result.tier}: {result.reason}")
        return {"passed": False}

    run.status = ReviewRunStatus.GATED
    run.save(update_fields=["gate_result", "status", "updated_at"])
    return {"passed": True}


@activity.defn
@asyncify
def run_review_in_sandbox(input: StamphogReviewInput) -> dict:
    """Provision a sandbox, clone the PR head, run the reviewer, and stash its raw output."""
    run = _load_run(input)
    repo_config = run.repo_config
    repo = repo_config.repository
    output = run.output or {}
    pr = output.get("pr", {})
    files = output.get("files", [])
    guidance = (output.get("policy_files") or {}).get(STAMPHOG_REVIEW_GUIDANCE_PATH, "")

    run.status = ReviewRunStatus.REVIEWING
    run.save(update_fields=["status", "updated_at"])

    client = StamphogGitHubClient(repo_config.installation_id)
    token = client._get_installation_token()

    invocation = build_reviewer_invocation(pr, files, guidance)

    sandbox_class = get_sandbox_class_for_backend(_resolve_sandbox_backend())
    config = SandboxConfig(
        name=f"stamphog-review-{run.id}",
        metadata={"review_run_id": str(run.id)},
        environment_variables={"STAMPHOG_REPO_DIR": STAMPHOG_SANDBOX_REPO_DIR},
    )
    sandbox = sandbox_class.create(config)
    try:
        _clone_head(sandbox, repo, run.head_sha, token)
        _place_reviewer_files(sandbox, invocation.files)

        command = f"cd {shlex.quote(STAMPHOG_SANDBOX_REPO_DIR)} && {_harden_reviewer_command(invocation.command)}"
        result = sandbox.execute(command, timeout_seconds=25 * 60)
    finally:
        sandbox.destroy()

    run.output = {**(run.output or {}), "reviewer_raw": result.stdout, "reviewer_exit_code": result.exit_code}
    run.save(update_fields=["output", "updated_at"])

    if result.exit_code != 0:
        raise RuntimeError(f"Reviewer exited with code {result.exit_code}: {result.stderr[:500]}")

    activity.logger.info(f"Reviewer completed for run {run.id}")
    return {"exit_code": result.exit_code}


@activity.defn
@asyncify
def post_verdict(input: StamphogReviewInput) -> dict:
    """Parse the reviewer output and post the approval or sticky comment."""
    run = _load_run(input)
    repo_config = run.repo_config
    repo = repo_config.repository
    output = run.output or {}
    raw = output.get("reviewer_raw", "")

    parsed = parse_reviewer_output(raw)
    client = StamphogGitHubClient(repo_config.installation_id)

    if parsed.verdict == ReviewVerdict.APPROVED:
        review = client.post_approve_review(repo, run.pr_number, _approve_comment(parsed), run.head_sha)
        run.posted_review_id = _comment_id(review)
    else:
        comment = client.upsert_sticky_comment(repo, run.pr_number, _verdict_comment(parsed))
        run.posted_comment_id = _comment_id(comment)

    run.status = ReviewRunStatus.COMPLETED
    run.verdict = parsed.verdict
    run.completed_at = timezone.now()
    run.verdict_posted_at = run.completed_at
    run.save(
        update_fields=[
            "status",
            "verdict",
            "completed_at",
            "verdict_posted_at",
            "posted_review_id",
            "posted_comment_id",
            "updated_at",
        ]
    )

    activity.logger.info(f"Posted verdict {parsed.verdict} for run {run.id}")
    return {"verdict": str(parsed.verdict)}


@activity.defn
@asyncify
def mark_review_failed(input: MarkReviewFailedInput) -> None:
    """Mark a run FAILED after an unrecoverable workflow error."""
    run = ReviewRun.objects.for_team(input.team_id).get(id=input.review_run_id)
    run.status = ReviewRunStatus.FAILED
    run.error = input.error
    run.completed_at = timezone.now()
    run.save(update_fields=["status", "error", "completed_at", "updated_at"])


def _harden_reviewer_command(command: Sequence[str] | str) -> str:
    """Turn the reviewer invocation into a shell string that runs uv in isolation.

    The PR head is untrusted, so the reviewer runs with its working directory inside the
    checkout. Without these flags uv would discover the checkout's own ``uv.toml`` /
    ``pyproject.toml [tool.uv]`` / ``uv.lock`` and let a malicious PR redirect ``index-url``
    to a hostile package index — arbitrary code execution inside a sandbox that holds a live
    installation token. ``--no-config`` ignores discovered uv config, ``--no-project`` ignores
    the surrounding project/lockfile; the reviewer's own PEP 723 script pins its deps.
    """
    parts = list(command) if isinstance(command, (list, tuple)) else shlex.split(command)
    if len(parts) >= 2 and parts[0] == "uv" and parts[1] == "run":
        parts = [*parts[:2], "--no-config", "--no-project", *parts[2:]]
    return shlex.join(parts)


def _scrub_credentials(text: str, *secrets: str) -> str:
    """Redact any credential material before it reaches ``ReviewRun.error`` or the logs."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


def _clone_head(sandbox: SandboxBase, repo: str, head_sha: str, token: str) -> None:
    """Shallow-clone the default branch then fetch and check out the PR head commit.

    The installation token is passed via a per-invocation ``http.extraheader`` rather than
    embedded in the remote URL, so git never persists it to ``.git/config`` inside the
    checkout that the LLM reviewer reads. The remote stays a clean, tokenless URL.
    """
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    auth = f"git -c http.extraheader={shlex.quote(f'AUTHORIZATION: basic {basic}')}"
    repo_url = f"https://github.com/{repo}.git"
    clone = (
        f"rm -rf {shlex.quote(STAMPHOG_SANDBOX_REPO_DIR)} && "
        f"{auth} clone --depth 1 --single-branch {shlex.quote(repo_url)} {shlex.quote(STAMPHOG_SANDBOX_REPO_DIR)}"
    )
    clone_result = sandbox.execute(clone, timeout_seconds=5 * 60)
    if clone_result.exit_code != 0:
        raise RuntimeError(f"Failed to clone {repo}: {_scrub_credentials(clone_result.stderr, token, basic)[:500]}")

    checkout = (
        f"cd {shlex.quote(STAMPHOG_SANDBOX_REPO_DIR)} && "
        f"{auth} fetch --depth 1 origin {shlex.quote(head_sha)} && "
        f"git checkout FETCH_HEAD"
    )
    checkout_result = sandbox.execute(checkout, timeout_seconds=5 * 60)
    if checkout_result.exit_code != 0:
        raise RuntimeError(
            f"Failed to check out {head_sha}: {_scrub_credentials(checkout_result.stderr, token, basic)[:500]}"
        )


def _place_reviewer_files(sandbox: SandboxBase, reviewer_files: dict[str, str]) -> None:
    """Write each reviewer prompt/instruction file into the sandbox at its absolute path."""
    for path, content in reviewer_files.items():
        parent = path.rsplit("/", 1)[0] if "/" in path else "."
        sandbox.execute(f"mkdir -p {shlex.quote(parent)}", timeout_seconds=30)
        sandbox.write_file(path, content.encode())


def _comment_id(obj: dict) -> int | None:
    """Pull the numeric id out of a GitHub review/comment response, or None."""
    value = obj.get("id") if isinstance(obj, dict) else None
    return value if isinstance(value, int) else None


def _gate_block_comment(tier: str, reason: str) -> str:
    return f"Stamphog did not auto-review this PR.\n\n**Reason ({tier}):** {reason}"


def _approve_comment(parsed: object) -> str:
    reasoning = getattr(parsed, "reasoning", "") or "Looks good."
    return reasoning


def _verdict_comment(parsed: object) -> str:
    reasoning = getattr(parsed, "reasoning", "") or ""
    showstoppers = getattr(parsed, "showstoppers", None) or []
    body = f"**Stamphog review: {getattr(parsed, 'verdict', 'unknown')}**\n\n{reasoning}"
    if showstoppers:
        body += "\n\n**Showstoppers:**\n" + "\n".join(f"- {item}" for item in showstoppers)
    return body
