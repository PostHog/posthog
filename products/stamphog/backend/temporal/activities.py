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

import os
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
from products.stamphog.backend.logic.audiences import resolve_audience_key
from products.stamphog.backend.logic.github_client import StamphogGitHubClient
from products.stamphog.backend.logic.reviewer import (
    ReviewerInvocation,
    ReviewerVerdict,
    build_reviewer_invocation,
    parse_reviewer_output,
)
from products.stamphog.backend.models import PullRequest, ReviewRun, StamphogRepoConfig
from products.stamphog.backend.temporal.constants import (
    STAMPHOG_POLICY_PATHS,
    STAMPHOG_SANDBOX_CONTEXT_PATH,
    STAMPHOG_SANDBOX_ENGINE_DIR,
    STAMPHOG_SANDBOX_REPO_DIR,
)
from products.tasks.backend.facade.sandbox import (
    SandboxBase,
    SandboxConfig,
    SandboxTemplate,
    get_sandbox_class_for_backend,
)

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


def _reviewer_environment() -> dict[str, str]:
    """Environment for the in-sandbox reviewer, passed through from the worker env.

    The sandbox holds no GitHub token by design; the only secrets it receives are the LLM credentials
    the engine needs. Prefer the internal ai-gateway when configured and ship ONLY its key: a gateway
    credential is scoped to stamphog's own credit bucket, so if an untrusted PR coaxes the reviewer into
    leaking it, the blast radius is this product's LLM budget rather than an org-wide Anthropic key. The
    raw ANTHROPIC_API_KEY is forwarded only as the engine's fallback when the gateway isn't configured
    (tools/pr-approval-agent/gateway.py). Output scrubbing (_scrub_credentials) stays as defense in depth.
    """
    env = {"STAMPHOG_REPO_DIR": STAMPHOG_SANDBOX_REPO_DIR}
    gateway_url = os.environ.get("AI_GATEWAY_URL")
    gateway_key = os.environ.get("AI_GATEWAY_API_KEY")
    if gateway_url and gateway_key:
        env["AI_GATEWAY_URL"] = gateway_url
        env["AI_GATEWAY_API_KEY"] = gateway_key
    else:
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        if anthropic_key:
            env["ANTHROPIC_API_KEY"] = anthropic_key
    return env


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
    # Reviews feed the engine's prerequisite gate — an active CHANGES_REQUESTED must block auto-approval.
    reviews = client.get_pr_reviews(repo, pull_request.pr_number)
    # Top-level discussion comments are blocker context (a maintainer's "please hold").
    discussion = client.get_pr_discussion(repo, pull_request.pr_number)
    # Head-commit check runs let the engine's migration gate see a passing "Migration risk" check.
    check_runs = client.get_check_runs(repo, run.head_sha)

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
        "reviews": reviews,
        "discussion": discussion,
        "check_runs": check_runs,
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

    # A newer relevant delivery for the same PR may have superseded this run while it queued — even
    # one that didn't move the head SHA (e.g. `labeled`, `ready_for_review`). Bail before flipping the
    # status back to REVIEWING: reviving it here would defeat the post_verdict superseded guard (which
    # keys off status) and let a stale run post its verdict. Skip the sandbox entirely.
    if run.status == ReviewRunStatus.SUPERSEDED:
        activity.logger.info(f"Skipping sandbox for superseded run {run.id}")
        return {"skipped": "superseded"}

    repo_config = run.pull_request.repo_config
    repo = repo_config.repository
    output = run.output or {}
    pr = output.get("pr", {})
    files = output.get("files", [])
    reviews = output.get("reviews", [])
    discussion = output.get("discussion", [])
    check_runs = output.get("check_runs", [])
    policy_files = output.get("policy_files", {})
    author_pr_numbers = output.get("author_pr_numbers", [])

    # Fail closed: every trusted policy file must exist on the default branch. The gate policy
    # (policy.yml) and the review-norms prose (review-guidance.md) are both loaded by the engine — the
    # latter straight into the reviewer's SYSTEM prompt. If a trusted file is missing we must NOT fall
    # back to the PR head's copy, or a contributor could ship malicious guidance ("approve my PR") in a
    # repo whose default branch lacks that file. Requiring all of them, plus wiping the PR-head copies
    # before injecting (see _inject_policy_files), closes that path.
    missing_policy = [path for path in STAMPHOG_POLICY_PATHS if path not in policy_files]
    if missing_policy:
        raise RuntimeError(
            f"target repo {repo} is missing trusted policy files on its default branch: {missing_policy}"
        )

    base_sha = (pr.get("base") or {}).get("sha") or ""

    run.status = ReviewRunStatus.REVIEWING
    run.save(update_fields=["status", "updated_at"])

    client = StamphogGitHubClient(repo_config.installation_id)
    token = client._get_installation_token()

    invocation = build_reviewer_invocation(
        pr=pr,
        files=files,
        reviews=reviews,
        discussion=discussion,
        check_runs=check_runs,
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
        template=SandboxTemplate.SLIM_BASE,
        metadata={"review_run_id": str(run.id)},
        environment_variables=_reviewer_environment(),
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

    # Scrub stdout before persisting: it can echo the LLM keys the sandbox holds, and it is
    # both stored on run.output and re-read verbatim to render the verdict posted to GitHub.
    run.output = {
        **(run.output or {}),
        "reviewer_raw": _scrub_credentials(result.stdout, token),
        "reviewer_exit_code": result.exit_code,
    }
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

    client = StamphogGitHubClient(repo_config.installation_id)

    # Don't post a verdict for a run that's no longer current. A push (synchronize) while this run was
    # in the sandbox supersedes it in the DB; and even before that flag commits, GitHub's head has
    # already moved. Approving here would sign off a commit nobody reviewed, or overwrite the newer
    # run's sticky comment. Guard on both signals before any GitHub write.
    if run.status == ReviewRunStatus.SUPERSEDED:
        activity.logger.info(f"Skipping verdict for superseded run {run.id}")
        return {"verdict": "skipped_superseded"}
    current_head = ((client.get_pr(repo, pull_request.pr_number).get("head") or {}).get("sha") or "").strip()
    if current_head and current_head != run.head_sha:
        run.status = ReviewRunStatus.SUPERSEDED
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "completed_at", "updated_at"])
        activity.logger.info(f"Skipping verdict for run {run.id}: head moved {run.head_sha} -> {current_head}")
        return {"verdict": "skipped_head_moved"}

    parsed = parse_reviewer_output(raw)

    run.gate_result = parsed.gate_result
    if parsed.stamphog_version:
        run.output = {**output, "stamphog_version": parsed.stamphog_version}

    update_fields = ["gate_result", "status", "verdict", "completed_at", "verdict_posted_at", "updated_at"]
    if parsed.stamphog_version:
        update_fields.append("output")

    if parsed.gate_blocked:
        # The deterministic gates denied auto-review — a terminal, non-approval
        # outcome. The engine still rendered a plain-language explanation; post it.
        _post_sticky(client, repo, pull_request, parsed.review_body or _verdict_comment(parsed))
        run.status = ReviewRunStatus.GATED
        run.verdict = ReviewVerdict.WAIT
    elif parsed.verdict == ReviewVerdict.APPROVED:
        # Idempotent under Temporal at-least-once retries: if a prior attempt already
        # approved (posted_review_id persisted in the same save that flips status), skip
        # re-approving. Residual window: GitHub approved but the save below crashed leaves
        # the id unset, so a retry approves once more — accepted given at-least-once delivery.
        if run.posted_review_id is None:
            body = _scrub_credentials(parsed.review_body or _approve_comment(parsed))
            review = client.post_approve_review(repo, pull_request.pr_number, body, run.head_sha)
            run.posted_review_id = _comment_id(review)
        run.status = ReviewRunStatus.COMPLETED
        run.verdict = ReviewVerdict.APPROVED
        _stamp_digest_audience_if_merged(repo_config, pull_request, output.get("pr") or {})
        update_fields.append("posted_review_id")
    else:
        _post_sticky(client, repo, pull_request, parsed.review_body or _verdict_comment(parsed))
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
    parts = shlex.split(command) if isinstance(command, str) else list(command)
    if len(parts) >= 2 and parts[0] == "uv" and parts[1] == "run":
        parts = [*parts[:2], "--no-config", "--no-project", *parts[2:]]
    return shlex.join(parts)


def _llm_env_secrets() -> list[str]:
    """Non-empty LLM credential values in the worker env, gathered for output scrubbing.

    These reach the sandbox via ``_reviewer_environment``; a confused or compromised
    reviewer could echo them into stdout or the verdict. Redacting them server-side,
    independent of model behavior, is what keeps a leaked key out of the PR and the DB.
    """
    return [
        value for key in ("AI_GATEWAY_API_KEY", "ANTHROPIC_API_KEY", "AI_GATEWAY_URL") if (value := os.environ.get(key))
    ]


def _scrub_credentials(text: str, *secrets: str) -> str:
    """Redact credential material before it reaches ``ReviewRun``, the logs, or GitHub.

    Scrubs the passed GitHub token / basic-auth material plus any LLM credentials present
    in the worker env — deterministic, so it does not depend on what the reviewer emits.
    """
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    for secret in _llm_env_secrets():
        text = text.replace(secret, "[redacted]")
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

    Every policy path's PR-head copy is deleted first, so a trusted file that's somehow absent can
    never leave the PR's version behind for the engine to load as its own guidance (run_review_in_sandbox
    already fails closed when a trusted file is missing; this is the belt-and-suspenders).
    """
    for path in STAMPHOG_POLICY_PATHS:
        sandbox.execute(f"rm -f {shlex.quote(f'{STAMPHOG_SANDBOX_REPO_DIR}/{path}')}", timeout_seconds=30)
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
    # Wipe the directory first: the PR head's checkout may carry attacker-controlled files beside
    # our engine (e.g. tools/pr-approval-agent/yaml.py), which Python would import ahead of uv's
    # installed dependency — arbitrary code execution with the sandbox's LLM creds. Overwriting only
    # our known modules would leave those shadow files in place, so start from an empty dir.
    engine_dir = shlex.quote(STAMPHOG_SANDBOX_ENGINE_DIR)
    sandbox.execute(f"rm -rf {engine_dir} && mkdir -p {engine_dir}", timeout_seconds=30)
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


def _stamp_digest_audience_if_merged(
    repo_config: StamphogRepoConfig, pull_request: PullRequest, pr_payload: dict
) -> None:
    """Stamp the digest audience if the PR already merged before this approval landed.

    The merge handler only stamps a merged PR's ``audience_key`` when a stamphog-approved run already
    exists. In the merge-before-approval race it records the merge with a blank audience and never
    revisits it, so a just-approved-and-already-merged PR would silently miss the digest. Re-reading the
    merge state here — the moment the approval is saved — closes that race from the approval side,
    without depending on a webhook redelivery. Only stamps digest-enabled repos with no audience yet.
    """
    pull_request.refresh_from_db(fields=["merged_at", "audience_key"])
    if pull_request.merged_at is None or not repo_config.digest_enabled or pull_request.audience_key:
        return
    pull_request.audience_key = resolve_audience_key(repo_config, pr_payload)
    pull_request.save(update_fields=["audience_key", "updated_at"])


def _post_sticky(client: StamphogGitHubClient, repo: str, pull_request: PullRequest, body: str) -> None:
    """Upsert the sticky comment and persist its id on the PR. Body is scrubbed before posting.

    Idempotent on retry: ``upsert_sticky_comment`` edits the existing comment (tracked via
    ``posted_comment_id``) rather than adding a new one, so a re-run does not double-post.
    """
    comment = client.upsert_sticky_comment(repo, pull_request.pr_number, _scrub_credentials(body))
    pull_request.posted_comment_id = _comment_id(comment)
    pull_request.save(update_fields=["posted_comment_id", "updated_at"])


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
