"""Temporal activities for the stamphog review workflow.

Each activity is keyed only by ``StamphogReviewInput`` (review_run_id + team_id) and
re-loads the ``ReviewRun`` it needs. Bulky data (the PR payload, changed files, fetched
policy files, raw reviewer output) is persisted on ``ReviewRun.output`` between steps
rather than threaded through the workflow, keeping every Temporal payload well under the
~2 MiB limit.

The whole review engine — hard gates, tier classification, git-blame familiarity, and
the LLM reviewer — runs inside the sandbox via the Action's own modules
(``tools/pr-approval-agent/review_local.py``). The server never processes repo content:
it fetches PR data and the trusted default-branch policy over the API, ships the engine
and injects the policy into the sandbox, and only ever reads back a single verdict JSON.
"""

from __future__ import annotations

import shlex
import base64
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.stamphog.backend.facade.enums import ReviewRunStatus, ReviewVerdict
from products.stamphog.backend.logic.github_client import StamphogGitHubClient
from products.stamphog.backend.logic.reviewer import (
    ReviewerInvocation,
    ReviewerVerdict,
    build_reviewer_invocation,
    parse_reviewer_output,
)
from products.stamphog.backend.models import ReviewRun
from products.stamphog.backend.temporal.constants import (
    STAMPHOG_POLICY_ENTRYPOINT,
    STAMPHOG_POLICY_PATHS,
    STAMPHOG_SANDBOX_CONTEXT_PATH,
    STAMPHOG_SANDBOX_ENGINE_DIR,
    STAMPHOG_SANDBOX_REPO_DIR,
)
from products.tasks.backend.facade.sandbox import SandboxBase, SandboxConfig, get_sandbox_class_for_backend

# The Action's review engine on the server's own checkout. Read as data files at
# runtime (never imported — the directory is hyphenated and lives outside the
# import graph) and shipped into the sandbox checkout. activities.py is at
# products/stamphog/backend/temporal/activities.py, so the repo root is five parents up.
_SERVER_ENGINE_DIR = Path(__file__).resolve().parents[4] / "tools" / "pr-approval-agent"


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
    return (
        ReviewRun.objects.for_team(input.team_id)
        .select_related("pull_request__repo_config")
        .get(id=input.review_run_id)
    )


def _resolve_sandbox_backend() -> str:
    """Map the shared ``SANDBOX_PROVIDER`` setting onto a get_sandbox_class_for_backend key.

    Unset means the production default (Modal); local dev sets ``docker`` or ``MODAL_DOCKER``.
    """
    provider = getattr(settings, "SANDBOX_PROVIDER", None)
    return provider if provider else "modal"


@activity.defn
@asyncify
def fetch_review_context(input: StamphogReviewInput) -> dict:
    """Load the PR, its changed files, the author's merged PRs, and default-branch policy."""
    run = _load_run(input)
    pull_request = run.pull_request
    repo_config = pull_request.repo_config
    repo = repo_config.repository

    client = StamphogGitHubClient(repo_config.installation_id)
    pr = client.get_pr(repo, pull_request.pr_number)
    files = client.get_pr_files(repo, pull_request.pr_number)

    author = (pr.get("user") or {}).get("login") or pull_request.author_login
    author_pr_numbers = client.get_author_merged_pr_numbers(repo, author) if author else []

    policy_files: dict[str, str] = {}
    for path in STAMPHOG_POLICY_PATHS:
        content = client.get_default_branch_file(repo, path)
        if content is not None:
            policy_files[path] = content

    run.output = {
        **(run.output or {}),
        "pr": pr,
        "files": files,
        "policy_files": policy_files,
        "author_pr_numbers": author_pr_numbers,
    }
    run.save(update_fields=["output", "updated_at"])

    activity.logger.info(f"Fetched review context for run {run.id} (pr #{pull_request.pr_number}, {len(files)} files)")
    return {"pr_number": pull_request.pr_number, "file_count": len(files), "head_sha": run.head_sha}


@activity.defn
@asyncify
def run_review_in_sandbox(input: StamphogReviewInput) -> dict:
    """Provision a sandbox, clone the PR, run the full engine offline, stash its raw output."""
    run = _load_run(input)
    repo_config = run.pull_request.repo_config
    repo = repo_config.repository
    output = run.output or {}
    pr = output.get("pr", {})
    files = output.get("files", [])
    policy_files = output.get("policy_files", {})
    author_pr_numbers = output.get("author_pr_numbers", [])

    # Fail closed: without the trusted gate policy the engine would either fall
    # back to an untrusted checkout copy or crash cryptically. Surface it early.
    if STAMPHOG_POLICY_ENTRYPOINT not in policy_files:
        raise RuntimeError(f"target repo {repo} is missing {STAMPHOG_POLICY_ENTRYPOINT} on its default branch")

    base_sha = (pr.get("base") or {}).get("sha") or ""

    run.status = ReviewRunStatus.REVIEWING
    run.save(update_fields=["status", "updated_at"])

    client = StamphogGitHubClient(repo_config.installation_id)
    token = client._get_installation_token()

    invocation = build_reviewer_invocation(
        pr=pr,
        files=files,
        author_pr_numbers=author_pr_numbers,
        base_sha=base_sha,
        head_sha=run.head_sha,
        repo=repo,
        engine_dir=STAMPHOG_SANDBOX_ENGINE_DIR,
        context_path=STAMPHOG_SANDBOX_CONTEXT_PATH,
    )

    sandbox_class = get_sandbox_class_for_backend(_resolve_sandbox_backend())
    config = SandboxConfig(
        name=f"stamphog-review-{run.id}",
        metadata={"review_run_id": str(run.id)},
        environment_variables={"STAMPHOG_REPO_DIR": STAMPHOG_SANDBOX_REPO_DIR},
    )
    sandbox = sandbox_class.create(config)
    try:
        _clone_pr(sandbox, repo, base_sha, run.head_sha, token)
        _inject_policy_files(sandbox, policy_files)
        _ship_engine(sandbox)
        _write_context(sandbox, invocation)

        command = f"cd {shlex.quote(STAMPHOG_SANDBOX_REPO_DIR)} && {_harden_reviewer_command(invocation.command)}"
        result = sandbox.execute(command, timeout_seconds=25 * 60)
    finally:
        sandbox.destroy()

    run.output = {**(run.output or {}), "reviewer_raw": result.stdout, "reviewer_exit_code": result.exit_code}
    run.save(update_fields=["output", "updated_at"])

    if result.exit_code != 0:
        raise RuntimeError(
            f"Reviewer exited with code {result.exit_code}: {_scrub_credentials(result.stderr, token)[:500]}"
        )

    activity.logger.info(f"Reviewer completed for run {run.id}")
    return {"exit_code": result.exit_code}


@activity.defn
@asyncify
def post_verdict(input: StamphogReviewInput) -> dict:
    """Parse the engine output and post the approval or sticky comment."""
    run = _load_run(input)
    pull_request = run.pull_request
    repo_config = pull_request.repo_config
    repo = repo_config.repository
    output = run.output or {}
    raw = output.get("reviewer_raw", "")

    parsed = parse_reviewer_output(raw)
    client = StamphogGitHubClient(repo_config.installation_id)

    run.gate_result = parsed.gate_result
    if parsed.stamphog_version:
        run.output = {**output, "stamphog_version": parsed.stamphog_version}

    update_fields = ["gate_result", "status", "verdict", "completed_at", "verdict_posted_at", "updated_at"]
    if parsed.stamphog_version:
        update_fields.append("output")

    if parsed.gate_blocked:
        # The deterministic gates denied auto-review — a terminal, non-approval
        # outcome. The engine still rendered a plain-language explanation; post it.
        comment = client.upsert_sticky_comment(
            repo, pull_request.pr_number, parsed.review_body or _verdict_comment(parsed)
        )
        pull_request.posted_comment_id = _comment_id(comment)
        pull_request.save(update_fields=["posted_comment_id", "updated_at"])
        run.status = ReviewRunStatus.GATED
        run.verdict = ReviewVerdict.WAIT
    elif parsed.verdict == ReviewVerdict.APPROVED:
        review = client.post_approve_review(
            repo, pull_request.pr_number, parsed.review_body or _approve_comment(parsed), run.head_sha
        )
        run.posted_review_id = _comment_id(review)
        run.status = ReviewRunStatus.COMPLETED
        run.verdict = ReviewVerdict.APPROVED
        update_fields.append("posted_review_id")
    else:
        comment = client.upsert_sticky_comment(
            repo, pull_request.pr_number, parsed.review_body or _verdict_comment(parsed)
        )
        pull_request.posted_comment_id = _comment_id(comment)
        pull_request.save(update_fields=["posted_comment_id", "updated_at"])
        run.status = ReviewRunStatus.COMPLETED
        run.verdict = parsed.verdict

    run.completed_at = timezone.now()
    run.verdict_posted_at = run.completed_at
    run.save(update_fields=update_fields)

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

    The PR head is untrusted, so the engine runs with its working directory inside the
    checkout. Without these flags uv would discover the checkout's own ``uv.toml`` /
    ``pyproject.toml [tool.uv]`` / ``uv.lock`` and let a malicious PR redirect ``index-url``
    to a hostile package index — arbitrary code execution inside a sandbox that holds a live
    installation token. ``--no-config`` ignores discovered uv config, ``--no-project`` ignores
    the surrounding project/lockfile; the engine's own PEP 723 script pins its deps.
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


def _clone_pr(sandbox: SandboxBase, repo: str, base_sha: str, head_sha: str, token: str) -> None:
    """Clone the repo with full history, then fetch the PR base and head and check out head.

    Full history (no ``--depth``) is required so git-blame familiarity resolves: the
    engine blames ``merge-base(base, head)`` for the diff's base-side lines, which needs
    the merge-base commit AND the file history behind it present with real blobs. A
    shallow clone would truncate blame to the graft boundary (undercounting, which only
    ever weakens the signal — a one-way ratchet — but is still avoidable here). Both the
    base and head shas are fetched explicitly so the merge-base is reachable even when the
    PR targets a non-default branch.

    The installation token is passed via a per-invocation ``http.extraheader`` rather than
    embedded in the remote URL, so git never persists it to ``.git/config`` inside the
    checkout that the engine (and LLM reviewer) reads. The remote stays a clean, tokenless URL.
    """
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    auth = f"git -c http.extraheader={shlex.quote(f'AUTHORIZATION: basic {basic}')}"
    repo_url = f"https://github.com/{repo}.git"

    clone = (
        f"rm -rf {shlex.quote(STAMPHOG_SANDBOX_REPO_DIR)} && "
        f"{auth} clone --single-branch {shlex.quote(repo_url)} {shlex.quote(STAMPHOG_SANDBOX_REPO_DIR)}"
    )
    clone_result = sandbox.execute(clone, timeout_seconds=10 * 60)
    if clone_result.exit_code != 0:
        raise RuntimeError(f"Failed to clone {repo}: {_scrub_credentials(clone_result.stderr, token, basic)[:500]}")

    fetch_specs = f"{auth} fetch origin {shlex.quote(head_sha)}"
    if base_sha:
        fetch_specs = f"{auth} fetch origin {shlex.quote(base_sha)} && {fetch_specs}"
    checkout = f"cd {shlex.quote(STAMPHOG_SANDBOX_REPO_DIR)} && {fetch_specs} && git checkout {shlex.quote(head_sha)}"
    checkout_result = sandbox.execute(checkout, timeout_seconds=10 * 60)
    if checkout_result.exit_code != 0:
        raise RuntimeError(
            f"Failed to check out {head_sha}: {_scrub_credentials(checkout_result.stderr, token, basic)[:500]}"
        )


def _inject_policy_files(sandbox: SandboxBase, policy_files: dict[str, str]) -> None:
    """Overwrite the checkout's ``.stamphog/*`` policy files with the trusted versions.

    Written AFTER checkout, so the trusted default-branch policy and review norms win
    over whatever the (untrusted) PR head carried. The engine reads them from the tree
    at import via its repo-root walk — this is what makes the run judge the PR against
    our policy, not the PR's own.
    """
    for path, content in policy_files.items():
        _write_sandbox_file(sandbox, f"{STAMPHOG_SANDBOX_REPO_DIR}/{path}", content)


def _ship_engine(sandbox: SandboxBase) -> None:
    """Ship the Action's review engine into the sandbox checkout at its canonical path.

    Placing it under ``<checkout>/tools/pr-approval-agent`` means the engine's repo-root
    walk lands on the checkout, so it reads the injected trusted policy. The PR head's own
    copy (if any) is overwritten — we always run our version, not the PR's.
    """
    files = _engine_source_files()
    if "review_local.py" not in files:
        raise RuntimeError(f"engine source dir {_SERVER_ENGINE_DIR} is missing review_local.py")
    sandbox.execute(f"mkdir -p {shlex.quote(STAMPHOG_SANDBOX_ENGINE_DIR)}", timeout_seconds=30)
    for name, content in files.items():
        sandbox.write_file(f"{STAMPHOG_SANDBOX_ENGINE_DIR}/{name}", content.encode())


def _engine_source_files() -> dict[str, str]:
    """Read the engine's Python modules from the server checkout (excluding tests/README)."""
    if not _SERVER_ENGINE_DIR.is_dir():
        raise RuntimeError(f"engine source dir not found: {_SERVER_ENGINE_DIR}")
    return {
        path.name: path.read_text()
        for path in sorted(_SERVER_ENGINE_DIR.glob("*.py"))
        if not path.name.startswith("test_")
    }


def _write_context(sandbox: SandboxBase, invocation: ReviewerInvocation) -> None:
    """Write the review context JSON the engine consumes into the checkout."""
    _write_sandbox_file(sandbox, invocation.context_path, invocation.context_json)


def _write_sandbox_file(sandbox: SandboxBase, path: str, content: str) -> None:
    parent = path.rsplit("/", 1)[0] if "/" in path else "."
    sandbox.execute(f"mkdir -p {shlex.quote(parent)}", timeout_seconds=30)
    sandbox.write_file(path, content.encode())


def _comment_id(obj: dict) -> int | None:
    """Pull the numeric id out of a GitHub review/comment response, or None."""
    value = obj.get("id") if isinstance(obj, dict) else None
    return value if isinstance(value, int) else None


def _approve_comment(parsed: ReviewerVerdict) -> str:
    return parsed.reasoning or "Looks good."


def _verdict_comment(parsed: ReviewerVerdict) -> str:
    body = f"**Stamphog review: {parsed.verdict}**\n\n{parsed.reasoning}".rstrip()
    if parsed.showstoppers:
        body += "\n\n**Showstoppers:**\n" + "\n".join(f"- {item}" for item in parsed.showstoppers)
    return body
