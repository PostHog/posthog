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
import re
import json
import shlex
import base64
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.db import router
from django.utils import timezone
from django.utils.dateparse import parse_datetime

import yaml
from temporalio import activity

from posthog.models import User
from posthog.ph_client import ph_scoped_capture
from posthog.temporal.common.utils import asyncify
from posthog.temporal.oauth import create_oauth_access_token_for_user

from products.stamphog.backend.facade.enums import TERMINAL_STATUSES, ReviewMode, ReviewRunStatus, ReviewVerdict
from products.stamphog.backend.logic.approvals import dismiss_stale_approvals_for_head
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
    STAMPHOG_BOT_EYES_MAX_AGE_SECONDS,
    STAMPHOG_OPTIONAL_POLICY_PATHS,
    STAMPHOG_POLICY_ENTRYPOINT,
    STAMPHOG_POLICY_PATHS,
    STAMPHOG_REVIEW_GUIDANCE_PATH,
    STAMPHOG_SANDBOX_CONTEXT_PATH,
    STAMPHOG_SANDBOX_ENGINE_DIR,
    STAMPHOG_SANDBOX_OWNERS_DIR,
    STAMPHOG_SANDBOX_REPO_DIR,
    STAMPHOG_TRUSTED_REACTOR_BOTS,
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

# Server-shipped default policy files, the base layer every repo's config sits on. Named by the
# basename of each STAMPHOG_POLICY_PATHS entry (policy.yml / review-guidance.md): a repo with no
# config reviews under these as-is, a repo's policy.yml overlays its sections onto the default's
# (see _effective_policy_files), and a repo's review-guidance.md replaces the default wholesale.
_POLICY_DEFAULTS_DIR = Path(__file__).resolve().parent.parent / "logic" / "policy_defaults"


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
    # Pinned to the writer: every activity re-loads the run the previous step just wrote, and the
    # webhook task committed the row moments before the workflow started — a lagged product-DB
    # reader would miss it (or serve a stale status) and fail the run spuriously.
    return (
        ReviewRun.objects.for_team(input.team_id)
        .using(router.db_for_write(ReviewRun))
        .select_related("pull_request__repo_config")
        .get(id=input.review_run_id)
    )


def _mint_reviewer_gateway_token(run: ReviewRun) -> str:
    """Short-lived OAuth token the sandboxed reviewer presents to the LLM gateway.

    Minted under the user who connected the repo's installation (the same creator-credential model
    tasks uses with ``task.created_by``), under the shared sandbox OAuth app, carrying only
    ``llm_gateway:read`` plus the ``internal_run:read`` provenance marker — the gateway's stamphog
    route sets ``requires_server_credential`` and refuses OAuth tokens without the marker, so a
    user's own Code OAuth token can't reach the route. The marker is passed explicitly instead of
    ``include_internal_scopes=True`` to keep the rest of the internal bundle (``task:write``) out of
    a sandbox that runs an LLM over untrusted PR content. If that PR coaxes the reviewer into
    leaking the token, it buys a few hours of stamphog-route LLM calls and nothing else — the
    worker's own long-lived credential never enters the sandbox. Fails closed when the repo was
    never synced or the connecting user is gone; re-syncing stamps a fresh identity.
    """
    user_id = run.pull_request.repo_config.connected_by_user_id
    if user_id is None:
        raise RuntimeError(
            "Repo config has no connecting user (installation never synced); cannot mint sandbox LLM credentials"
        )
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        raise RuntimeError(
            "The user who connected this installation is missing or deactivated; "
            "re-sync the installation to mint sandbox LLM credentials"
        )
    return create_oauth_access_token_for_user(
        user, run.team_id, scopes=["llm_gateway:read", "internal_run:read"], include_internal_scopes=False
    )


def _reviewer_environment(run: ReviewRun) -> dict[str, str]:
    """Environment for the in-sandbox reviewer.

    The sandbox holds no GitHub token by design, and no long-lived LLM credential either: the only
    secret it receives is a per-run minted gateway token (see ``_mint_reviewer_gateway_token``). The
    gateway is mandatory for hosted runs — the engine's raw-Anthropic fallback exists for the GitHub
    Action runtime, where the env is the repo's own secrets, and an org-wide Anthropic key must never
    ride into a sandbox that runs an LLM over untrusted PR content. AI_GATEWAY_URL must point at the
    gateway's stamphog product route (``https://<gateway>/stamphog/v1``): that route allowlists the
    sandbox OAuth app the token is minted under, so a token presented anywhere else is refused.

    POSTHOG_API_KEY/POSTHOG_HOST let the engine emit its stamphog_review_completed event and LLM
    traces from inside the sandbox. The capture key is a public project write token — the same class of
    token every frontend snippet ships — so its blast radius is event spam, not data access; it's still
    added to _llm_env_secrets so persisted output stays tidy. STAMPHOG_EXTRA_PROPERTIES stamps the
    hosted runtime/team/run context onto those events (the Action never sets it).
    """
    gateway_url = os.environ.get("AI_GATEWAY_URL")
    if not gateway_url:
        raise RuntimeError("AI_GATEWAY_URL is not configured; hosted reviews require the LLM gateway")
    env = {
        "STAMPHOG_REPO_DIR": STAMPHOG_SANDBOX_REPO_DIR,
        "AI_GATEWAY_URL": gateway_url,
        "AI_GATEWAY_API_KEY": _mint_reviewer_gateway_token(run),
    }
    for key in ("POSTHOG_API_KEY", "POSTHOG_HOST"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    env["STAMPHOG_EXTRA_PROPERTIES"] = json.dumps(
        {
            "stamphog_runtime": "hosted",
            "stamphog_team_id": run.team_id,
            "stamphog_review_run_id": str(run.id),
        },
        separators=(",", ":"),
    )
    return env


def _sandbox_egress_allowlist() -> list[str]:
    """Outbound domains the review sandbox may reach; Modal fences off everything else.

    The sandbox env carries a live (if short-lived, narrowly scoped) credential next to an LLM
    reading untrusted PR content. Output scrubbing covers what the server persists, but nothing else
    stops a prompt-injected reviewer from POSTing what it holds to an arbitrary host — closing egress
    to the hosts a review actually needs removes that channel: github.com for the clone, PyPI for the
    engine's pinned deps, the gateway for LLM calls, and the PostHog capture host for telemetry.
    STAMPHOG_SANDBOX_EXTRA_EGRESS_DOMAINS is the ops escape hatch for a missing legitimate host.
    The docker backend (local dev) ignores the allowlist.
    """
    domains = ["github.com", "pypi.org", "files.pythonhosted.org"]
    for url_env in ("AI_GATEWAY_URL", "POSTHOG_HOST"):
        host = urlparse(os.environ.get(url_env, "")).hostname
        if host:
            domains.append(host)
    domains.extend(settings.STAMPHOG_SANDBOX_EXTRA_EGRESS_DOMAINS)
    return list(dict.fromkeys(domains))


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
    for path in (*STAMPHOG_POLICY_PATHS, *STAMPHOG_OPTIONAL_POLICY_PATHS):
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
        "pr_reactions": client.get_pr_reactions(repo, pull_request.pr_number),
        "policy_files": policy_files,
        "author_pr_numbers": author_pr_numbers,
    }
    run.save(update_fields=["output", "updated_at"])

    activity.logger.info(f"Fetched review context for run {run.id} (pr #{pull_request.pr_number}, {len(files)} files)")
    return {"pr_number": pull_request.pr_number, "file_count": len(files), "head_sha": run.head_sha}


@activity.defn
@asyncify
def dismiss_stale_approvals(input: StamphogReviewInput) -> dict:
    """Retract stamphog approvals posted at an earlier head so a push can't leave one standing.

    GitHub never auto-dismisses an APPROVE review when new commits land, so a prior run's approval at
    an old head keeps satisfying required reviews after a push. This runs FIRST in the workflow — before
    context fetch, before the sandbox — on purpose: dismiss, then re-review. That ordering is fail-closed —
    if any later step crashes (even the context fetch), the stale approval is already gone rather than
    left standing over unreviewed commits. It needs only the run row, so nothing has to be fetched first.
    """
    run = _load_run(input)
    if run.status == ReviewRunStatus.SUPERSEDED:
        activity.logger.info(f"Skipping approval dismissal for superseded run {run.id}")
        return {"skipped": "superseded"}

    pull_request = run.pull_request
    repo_config = pull_request.repo_config

    dismissed = dismiss_stale_approvals_for_head(input.team_id, pull_request, repo_config, run.head_sha)

    activity.logger.info(f"Dismissed {dismissed} stale approval(s) for run {run.id} (pr #{pull_request.pr_number})")
    return {"dismissed": dismissed}


@activity.defn
@asyncify
def list_in_flight_reviewer_bots(input: StamphogReviewInput) -> dict:
    """Allowlisted reviewer bots with a fresh 👀 on the PR, refreshing the stored snapshot.

    The Action waits these bots out by polling GitHub from the runner; the hosted sandbox holds no
    token, so the WORKFLOW polls this activity instead, sleeping on durable timers between calls.
    Each call re-fetches the reactions and refreshes ``run.output["pr_reactions"]`` so the sandbox
    context reflects the latest snapshot — if the wait budget expires with a bot still in flight,
    the engine sees the fresh 👀 and returns WAIT rather than approving over an unfinished review.
    """
    run = _load_run(input)
    if run.status == ReviewRunStatus.SUPERSEDED:
        return {"in_flight": []}
    repo_config = run.pull_request.repo_config
    client = StamphogGitHubClient(repo_config.installation_id)
    reactions = client.get_pr_reactions(repo_config.repository, run.pull_request.pr_number)
    run.output = {**(run.output or {}), "pr_reactions": reactions}
    run.save(update_fields=["output", "updated_at"])

    now = timezone.now()
    in_flight = sorted(
        {
            reaction["user"]
            for reaction in reactions
            if reaction.get("content") == "eyes"
            and (reaction.get("user") or "").lower() in STAMPHOG_TRUSTED_REACTOR_BOTS
            and (created := parse_datetime(reaction.get("created_at") or "")) is not None
            and (now - created).total_seconds() <= STAMPHOG_BOT_EYES_MAX_AGE_SECONDS
        }
    )
    if in_flight:
        activity.logger.info(f"Run {run.id}: reviewer bot(s) in flight: {', '.join(in_flight)}")
    return {"in_flight": in_flight}


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
    pr_reactions = output.get("pr_reactions", [])
    policy_files = output.get("policy_files", {})
    author_pr_numbers = output.get("author_pr_numbers", [])

    # The trusted source for each policy file is the repo's default branch layered over the
    # server-shipped defaults (see _effective_policy_files): policy.yml is a section overlay, the
    # guidance file is repo-else-default, steering is repo-else-omitted. The gate policy and the
    # review-norms prose are both loaded by the engine — the latter straight into the reviewer's
    # SYSTEM prompt. We must NOT fall back to the PR head's copy, or a contributor could ship
    # malicious guidance ("approve my PR") in a repo whose default branch lacks the file — the
    # PR-head wipe in _inject_policy_files stays mandatory, and the fallback content is
    # server-owned, never the PR's.
    policy_files = _effective_policy_files(repo, policy_files)

    base_sha = (pr.get("base") or {}).get("sha") or ""

    # Flip to REVIEWING only if a delivery hasn't superseded this run since the early guard above.
    # A plain save() would blindly overwrite a run that was superseded between the read and the write,
    # reviving it back to REVIEWING and letting a stale run post its verdict. A conditional update that
    # refuses to touch a SUPERSEDED row closes that window — 0 rows means it lost the race, so bail
    # before provisioning the sandbox or fetching a token.
    updated = (
        ReviewRun.objects.for_team(input.team_id)
        .filter(id=run.id)
        .exclude(status=ReviewRunStatus.SUPERSEDED)
        .update(status=ReviewRunStatus.REVIEWING, updated_at=timezone.now())
    )
    if not updated:
        activity.logger.info(f"Skipping sandbox for superseded run {run.id} (superseded before REVIEWING)")
        return {"skipped": "superseded"}

    client = StamphogGitHubClient(repo_config.installation_id)
    token = client._get_installation_token()

    invocation = build_reviewer_invocation(
        pr=pr,
        files=files,
        reviews=reviews,
        discussion=discussion,
        check_runs=check_runs,
        pr_reactions=pr_reactions,
        author_pr_numbers=author_pr_numbers,
        base_sha=base_sha,
        head_sha=run.head_sha,
        repo=repo,
        engine_dir=STAMPHOG_SANDBOX_ENGINE_DIR,
        context_path=STAMPHOG_SANDBOX_CONTEXT_PATH,
    )

    sandbox_class = get_sandbox_class_for_backend(_resolve_sandbox_backend())
    environment = _reviewer_environment(run)
    # Per-run credential, not in the worker env — scrub it explicitly wherever sandbox output
    # is persisted or raised (_llm_env_secrets only covers worker-env values).
    gateway_token = environment["AI_GATEWAY_API_KEY"]
    config = SandboxConfig(
        name=f"stamphog-review-{run.id}",
        template=SandboxTemplate.SLIM_BASE,
        metadata={"review_run_id": str(run.id)},
        environment_variables=environment,
        outbound_domain_allowlist=_sandbox_egress_allowlist(),
    )
    sandbox = sandbox_class.create(config)
    try:
        _clone_pr(sandbox, repo, base_sha, run.head_sha, run.pull_request.pr_number, token)
        _inject_policy_files(sandbox, policy_files)
        _ship_engine(sandbox)
        _write_context(sandbox, invocation)

        command = f"cd {shlex.quote(STAMPHOG_SANDBOX_REPO_DIR)} && {_harden_reviewer_command(invocation.command)}"
        result = sandbox.execute(command, timeout_seconds=25 * 60)
    finally:
        # A destroy failure must not mask a completed review — the verdict below still has to be
        # persisted and posted. An orphaned sandbox self-terminates when SandboxConfig.ttl_seconds expires.
        try:
            sandbox.destroy()
        except Exception:
            activity.logger.exception(f"Failed to destroy sandbox for run {run.id}")

    # Scrub stdout before persisting: it can echo the LLM keys the sandbox holds, and it is
    # both stored on run.output and re-read verbatim to render the verdict posted to GitHub.
    run.output = {
        **(run.output or {}),
        "reviewer_raw": _scrub_credentials(result.stdout, token, gateway_token),
        "reviewer_exit_code": result.exit_code,
    }
    run.save(update_fields=["output", "updated_at"])

    if result.exit_code != 0:
        raise RuntimeError(
            f"Reviewer exited with code {result.exit_code}: "
            f"{_scrub_credentials(result.stderr, token, gateway_token)[:500]}"
        )

    activity.logger.info(f"Reviewer completed for run {run.id}")
    return {"exit_code": result.exit_code}


def _dismiss_orphaned_approval(client: StamphogGitHubClient, run: ReviewRun, team_id: int) -> None:
    """Retract an approval this run posted to GitHub but never recorded as its saved verdict.

    Reaching here means the run is being abandoned (superseded, or its head moved) after
    ``post_approve_review`` succeeded but before the terminal save recorded APPROVED. The
    stale-approval sweep keys off ``posted_review_id`` in the DB, which the superseding delivery
    read before this review existed — the abandoning path itself is the only place left that can
    retract it. Raises on GitHub failure so the activity retries; ``approval_dismissed_at`` keeps
    the retry (and a racing sweep) idempotent.
    """
    if run.posted_review_id is None or run.approval_dismissed_at is not None:
        return
    pull_request = run.pull_request
    client.dismiss_pr_review(
        pull_request.repo_config.repository,
        pull_request.pr_number,
        run.posted_review_id,
        "This review run was superseded before it completed — dismissing its approval; a newer run owns this PR.",
    )
    run.approval_dismissed_at = timezone.now()
    ReviewRun.objects.for_team(team_id).filter(id=run.id).update(
        approval_dismissed_at=run.approval_dismissed_at, updated_at=timezone.now()
    )
    activity.logger.info(f"Run {run.id}: dismissed orphaned approval {run.posted_review_id}")


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
        # A prior attempt may have approved and crashed before the terminal save; the persisted id
        # is the only trace. Durably recorded approvals (verdict saved) are the sweep's job instead.
        if run.verdict != ReviewVerdict.APPROVED:
            _dismiss_orphaned_approval(client, run, input.team_id)
        activity.logger.info(f"Skipping verdict for superseded run {run.id}")
        return {"verdict": "skipped_superseded"}
    current_pr = client.get_pr(repo, pull_request.pr_number)
    current_head = ((current_pr.get("head") or {}).get("sha") or "").strip()
    if current_head and current_head != run.head_sha:
        run.status = ReviewRunStatus.SUPERSEDED
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "completed_at", "updated_at"])
        if run.verdict != ReviewVerdict.APPROVED:
            _dismiss_orphaned_approval(client, run, input.team_id)
        activity.logger.info(f"Skipping verdict for run {run.id}: head moved {run.head_sha} -> {current_head}")
        return {"verdict": "skipped_head_moved"}

    parsed = parse_reviewer_output(raw)

    run.gate_result = parsed.gate_result
    if parsed.stamphog_version:
        run.output = {**output, "stamphog_version": parsed.stamphog_version}

    update_fields = ["gate_result", "status", "verdict", "completed_at", "verdict_posted_at", "updated_at"]
    if parsed.stamphog_version:
        update_fields.append("output")

    # Last look before any GitHub write: a same-head re-review delivery (e.g. a trigger-label re-add)
    # supersedes this run WITHOUT moving the head, so the head guard above can't catch it — only a
    # fresh status read can.
    superseded_now = (
        ReviewRun.objects.for_team(input.team_id)
        .using(router.db_for_write(ReviewRun))
        .filter(id=run.id, status=ReviewRunStatus.SUPERSEDED)
        .exists()
    )
    if superseded_now:
        # Same orphan rule as the guards above: a prior attempt may have posted and persisted the
        # review id, then crashed before the terminal save; a same-head supersession landing here is
        # invisible to the sweep (it excludes same-head approvals), so retract before returning.
        if run.verdict != ReviewVerdict.APPROVED:
            _dismiss_orphaned_approval(client, run, input.team_id)
        activity.logger.info(f"Skipping verdict for run {run.id}: superseded during posting")
        return {"verdict": "skipped_superseded"}

    if parsed.gate_blocked:
        # The deterministic gates denied auto-review — a terminal, non-approval
        # outcome. The engine still rendered a plain-language explanation; post it.
        _post_sticky(
            client, repo, pull_request, _neutralize_active_markdown(parsed.review_body or _verdict_comment(parsed))
        )
        run.status = ReviewRunStatus.GATED
        run.verdict = ReviewVerdict.WAIT
    elif parsed.verdict == ReviewVerdict.APPROVED:
        # Idempotent under Temporal at-least-once retries: the id is persisted the moment GitHub
        # accepts the review, so a retry after any later crash skips re-approving.
        if run.posted_review_id is None:
            body = _neutralize_active_markdown(_scrub_credentials(parsed.review_body or _approve_comment(parsed)))
            review = client.post_approve_review(repo, pull_request.pr_number, body, run.head_sha)
            run.posted_review_id = _comment_id(review)
            # Persist the id immediately, outside the conditional terminal save below: if that save
            # loses to a supersession or this activity crashes, this row is the only record the
            # approval exists — the orphan-dismissal paths and the stale-approval sweep need it.
            ReviewRun.objects.for_team(input.team_id).filter(id=run.id).update(
                posted_review_id=run.posted_review_id, updated_at=timezone.now()
            )
        run.status = ReviewRunStatus.COMPLETED
        run.verdict = ReviewVerdict.APPROVED
        update_fields.append("posted_review_id")
    else:
        _post_sticky(
            client, repo, pull_request, _neutralize_active_markdown(parsed.review_body or _verdict_comment(parsed))
        )
        run.status = ReviewRunStatus.COMPLETED
        run.verdict = parsed.verdict

    # Action parity: in label-triggered mode a refused/escalated verdict strips the trigger label, so
    # the author re-requests the next review by re-adding it. Keyed off parsed.verdict, not run.verdict —
    # the gate-blocked branch overrides run.verdict to WAIT but the Action strips on gate refusals too.
    # A failure here raises on purpose: the activity retries and the sticky upsert above is idempotent.
    if repo_config.review_mode == ReviewMode.LABEL and parsed.verdict in (
        ReviewVerdict.REFUSED,
        ReviewVerdict.ESCALATE,
    ):
        client.remove_pr_label(repo, pull_request.pr_number, repo_config.trigger_label)

    run.completed_at = timezone.now()
    run.verdict_posted_at = run.completed_at
    # Conditional terminal save: a delivery superseding this run between the guards above and here
    # must win — a plain save would write COMPLETED back over SUPERSEDED and resurrect a stale run.
    updated = (
        ReviewRun.objects.for_team(input.team_id)
        .filter(id=run.id)
        .exclude(status=ReviewRunStatus.SUPERSEDED)
        .update(
            **{field: getattr(run, field) for field in update_fields if field != "updated_at"},
            updated_at=timezone.now(),
        )
    )
    if not updated:
        # This run lost the terminal save to a supersession that landed after the last guard. If it
        # already posted an approval, the superseding delivery's dismissal sweep ran before the
        # review existed and can't see it in the DB — retract it here or it stands forever.
        _dismiss_orphaned_approval(client, run, input.team_id)
        activity.logger.info(f"Run {run.id} superseded during verdict posting; verdict not saved")
        return {"verdict": "skipped_superseded"}

    # Close the merge-before-approval race only AFTER this run's APPROVED verdict is durably saved. If
    # the PR auto-merged the instant GitHub recorded the approval, the closed webhook may run before this
    # save committed and find no approved run, so it stamps nothing; stamping here (which refreshes
    # merged_at) then catches the merge. Ordering the two the other way — stamp before save — was the bug:
    # the webhook saw no approved run AND the refresh predated the webhook's merged_at, so both missed and
    # a merged+approved PR silently skipped the digest. Idempotent: it no-ops unless merged, digest-enabled,
    # and unstamped, so the closed-webhook path and this path can't double-stamp.
    if run.verdict == ReviewVerdict.APPROVED:
        _stamp_digest_audience_if_merged(repo_config, pull_request, run, current_pr)

    activity.logger.info(f"Posted verdict {parsed.verdict} for run {run.id}")
    return {"verdict": str(parsed.verdict)}


@activity.defn
@asyncify
def mark_review_failed(input: MarkReviewFailedInput) -> None:
    """Mark a run FAILED after an unrecoverable workflow error."""
    run = _load_run(StamphogReviewInput(review_run_id=input.review_run_id, team_id=input.team_id))
    # A run that already reached a terminal state stays there: post_verdict saves COMPLETED (with the
    # approval already posted to GitHub) before its trailing digest stamp, so a late failure must not
    # rewrite a delivered outcome to FAILED — record the error for the logs and leave the status alone.
    first_error_line = (input.error.splitlines() or [""])[0][:300]
    if run.status in TERMINAL_STATUSES:
        activity.logger.warning(f"Run {run.id} already {run.status}; keeping it, error was: {first_error_line}")
        return
    # Persist only the first line, truncated: run.error is returned by the serializer to anyone with
    # stamphog:read, and raw exception text can embed repository file content (a yaml.YAMLError over
    # .stamphog/policy.yml echoes the offending source lines on its continuation lines). Full detail is
    # already in the worker logs — the workflow logs the complete error before calling this activity.
    run.status = ReviewRunStatus.FAILED
    run.error = first_error_line
    run.completed_at = timezone.now()
    run.save(update_fields=["status", "error", "completed_at", "updated_at"])

    # Hosted failures were only visible in worker logs; capture them so the dashboards see hosted
    # breakage next to the review-completed events. ph_scoped_capture, not posthoganalytics.capture —
    # the global client's background flush may never run before the worker thread moves on.
    pull_request = run.pull_request
    repo = pull_request.repo_config.repository
    with ph_scoped_capture() as capture:
        capture(
            distinct_id=pull_request.author_login or repo,
            event="stamphog_review_failed",
            properties={
                "stamphog_repo": repo,
                "stamphog_pr_number": pull_request.pr_number,
                "stamphog_team_id": input.team_id,
                "stamphog_runtime": "hosted",
                "stamphog_error": first_error_line,
            },
        )


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
    POSTHOG_API_KEY is a public write token (spam-only blast radius) — scrubbed for tidiness.
    """
    return [
        value
        for key in ("AI_GATEWAY_API_KEY", "ANTHROPIC_API_KEY", "AI_GATEWAY_URL", "POSTHOG_API_KEY")
        if (value := os.environ.get(key))
    ]


# Inline markdown images and raw <img> tags in text GitHub renders — both are removed outright,
# URL included. Reference-style image forms are handled by the ``![`` demotion below.
_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)|<img\b[^>]*>", re.IGNORECASE)


def _neutralize_active_markdown(text: str) -> str:
    """Remove auto-fetched markdown constructs from reviewer-authored text before it reaches GitHub.

    The reviewer LLM reads untrusted PR content, so its output can be prompt-injected. Credential
    scrubbing is exact-string only — a token re-encoded (base64, split) into an image URL slips
    through, and GitHub fetching the image on render (through its camo proxy, no click needed) would
    exfiltrate it OUTSIDE the sandbox egress allowlist.

    Inline images and <img> tags are removed URL-and-all. Every OTHER markdown image form —
    reference ``![a][ref]``, collapsed, shortcut — starts with ``![``, so the trailing demotion to
    ``[`` turns anything left into a plain link, which GitHub never fetches without a click.
    Deliberately a syntax demotion rather than an enumeration of forms: an image form this function's
    author didn't think of still gets demoted. Plain links stay clickable, so legitimate references
    to code and PRs survive.
    """
    return _MARKDOWN_IMAGE_RE.sub("[image removed]", text).replace("![", "[")


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


def _clone_pr(sandbox: SandboxBase, repo: str, base_sha: str, head_sha: str, pr_number: int, token: str) -> None:
    """Clone the repo with full history, then fetch the PR base and head and check out head.

    Full history (no ``--depth``) is required so git-blame familiarity resolves: the
    engine blames ``merge-base(base, head)`` for the diff's base-side lines, which needs
    the merge-base commit AND the file history behind it present with real blobs. A
    shallow clone would truncate blame to the graft boundary (undercounting, which only
    ever weakens the signal — a one-way ratchet — but is still avoidable here).

    The head is fetched through ``pull/<n>/head`` rather than the bare sha: a fork PR's
    head commit only exists in the base repo through that ref, so a bare-sha fetch fails
    for member-authored fork PRs (the only fork PRs that pass the webhook's author gate).
    The base sha is still fetched directly so the merge-base is reachable even when the
    PR targets a non-default branch. If the head moved since this run was queued, the
    checkout of the recorded sha fails and the superseding run takes over — a stale sha
    must not be reviewed against a newer pull ref.

    The installation token is passed via a per-invocation ``http.extraheader`` rather than
    embedded in the remote URL, so git never persists it to ``.git/config`` inside the
    checkout that the engine (and LLM reviewer) reads. The remote stays a clean, tokenless URL.
    """
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    auth = f"git -c http.extraheader={shlex.quote(f'AUTHORIZATION: basic {basic}')}"
    repo_url = f"https://github.com/{repo}.git"

    def _execute_or_raise(command: str, failure_prefix: str) -> None:
        # sandbox.execute failures raised by the Docker/Modal layer can embed the full command string —
        # including the AUTHORIZATION: basic <token> header — in the exception text, which then flows into
        # Temporal failure details and run.error. Scrub any raised exception (from None so the unscrubbed
        # original context isn't chained), and keep scrubbing stderr on a non-zero exit.
        try:
            result = sandbox.execute(command, timeout_seconds=10 * 60)
        except Exception as exc:
            raise RuntimeError(_scrub_credentials(str(exc), token, basic)) from None
        if result.exit_code != 0:
            raise RuntimeError(f"{failure_prefix}: {_scrub_credentials(result.stderr, token, basic)[:500]}")

    clone = (
        f"rm -rf {shlex.quote(STAMPHOG_SANDBOX_REPO_DIR)} && "
        f"{auth} clone --single-branch {shlex.quote(repo_url)} {shlex.quote(STAMPHOG_SANDBOX_REPO_DIR)}"
    )
    _execute_or_raise(clone, f"Failed to clone {repo}")

    fetch_specs = f"{auth} fetch origin {shlex.quote(f'pull/{pr_number}/head')}"
    if base_sha:
        fetch_specs = f"{auth} fetch origin {shlex.quote(base_sha)} && {fetch_specs}"
    checkout = f"cd {shlex.quote(STAMPHOG_SANDBOX_REPO_DIR)} && {fetch_specs} && git checkout {shlex.quote(head_sha)}"
    _execute_or_raise(checkout, f"Failed to check out {head_sha}")


def _read_default_policy_file(path: str) -> str:
    """Read a shipped default by the policy path's basename; missing means a server packaging bug."""
    default_file = _POLICY_DEFAULTS_DIR / Path(path).name
    if not default_file.is_file():
        raise RuntimeError(f"server-shipped default policy file missing: {default_file} (for {path})")
    return default_file.read_text()


def _overlay_policy_yaml(repo: str, default_text: str, repo_text: str | None) -> str:
    """Overlay the repo's policy.yml top-level sections onto the shipped default.

    Lets a repo declare only the sections it wants to change (e.g. just ``size_gate``); each
    present section replaces the default's section wholesale. The engine's strict loader still
    validates the merged doc inside the sandbox, so required sections and the self-governance
    deny can't be dropped by omission, and a full-schema repo file overlays to exactly itself.
    The ``digest:`` key passes through harmlessly (the engine tolerates and ignores it).

    A present-but-unusable repo file (malformed YAML, non-mapping root) fails closed: the repo
    declared *something*, and silently reviewing under pure defaults would be wrong.
    """
    if repo_text is None:
        return default_text
    try:
        overlay = yaml.safe_load(repo_text)
    except yaml.YAMLError as exc:
        raise RuntimeError(f"repo {repo} has malformed YAML in .stamphog/policy.yml: {exc}") from exc
    if not isinstance(overlay, dict):
        raise RuntimeError(f"repo {repo} .stamphog/policy.yml must be a YAML mapping to overlay the defaults")
    merged = {**yaml.safe_load(default_text), **overlay}
    # sort_keys=False keeps the default's section order stable in the dumped doc.
    return yaml.safe_dump(merged, sort_keys=False)


def _effective_policy_files(repo: str, policy_files: dict[str, str]) -> dict[str, str]:
    """The final injection set: the repo's default-branch files layered over the hosted defaults.

    policy.yml: section overlay onto the shipped default (see _overlay_policy_yaml).
    review-guidance.md: the repo's copy if present, else the shipped default.
    Optional paths (steering.md): the repo's copy if present, else omitted — no default exists.
    """
    defaulted = [path for path in STAMPHOG_POLICY_PATHS if path not in policy_files]
    if defaulted:
        activity.logger.info(f"Policy files for {repo} using hosted defaults: {defaulted}")

    effective = {
        STAMPHOG_POLICY_ENTRYPOINT: _overlay_policy_yaml(
            repo,
            _read_default_policy_file(STAMPHOG_POLICY_ENTRYPOINT),
            policy_files.get(STAMPHOG_POLICY_ENTRYPOINT),
        ),
        STAMPHOG_REVIEW_GUIDANCE_PATH: policy_files.get(STAMPHOG_REVIEW_GUIDANCE_PATH)
        or _read_default_policy_file(STAMPHOG_REVIEW_GUIDANCE_PATH),
    }
    for path in STAMPHOG_OPTIONAL_POLICY_PATHS:
        if path in policy_files:
            effective[path] = policy_files[path]
    return effective


def _inject_policy_files(sandbox: SandboxBase, policy_files: dict[str, str]) -> None:
    """Overwrite the checkout's ``.stamphog/*`` policy files with the trusted versions.

    Written AFTER checkout, so the trusted default-branch policy and review norms win
    over whatever the (untrusted) PR head carried. The engine reads them from the tree
    at import via its repo-root walk — this is what makes the run judge the PR against
    our policy, not the PR's own.

    Every policy path's PR-head copy is deleted first — required AND optional: an uninjected
    optional file (a repo with no steering.md) must not leave the PR head's planted copy behind
    for the engine to load, any more than a missing policy.yml would.
    """
    for path in (*STAMPHOG_POLICY_PATHS, *STAMPHOG_OPTIONAL_POLICY_PATHS):
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
    _ship_owners_package(sandbox)


def _ship_owners_package(sandbox: SandboxBase) -> None:
    """Ship the posthog-owners resolver package the engine's ownership format imports.

    The default policy declares a ``hogli-resolver`` ownership source, and gates.py imports
    ``posthog_owners`` from ``tools/owners`` next to the engine dir. Same trust posture as the
    engine: always our copy, wiping whatever the PR head carried at that path. Repos without
    owners.yaml/product.yaml files simply resolve to "no ownership-source match".
    """
    package_dir = _SERVER_ENGINE_DIR.parent / "owners" / "posthog_owners"
    if not package_dir.is_dir():
        raise RuntimeError(f"owners package source dir not found: {package_dir}")
    target = f"{STAMPHOG_SANDBOX_OWNERS_DIR}/posthog_owners"
    quoted = shlex.quote(STAMPHOG_SANDBOX_OWNERS_DIR)
    sandbox.execute(f"rm -rf {quoted} && mkdir -p {shlex.quote(target)}", timeout_seconds=30)
    for path in sorted(package_dir.glob("*.py")):
        sandbox.write_file(f"{target}/{path.name}", path.read_text().encode())


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
    repo_config: StamphogRepoConfig, pull_request: PullRequest, run: ReviewRun, pr_payload: dict
) -> None:
    """Stamp the digest audience if the PR already merged before this approval landed.

    The merge handler only stamps a merged PR's ``audience_key`` when a stamphog-approved run already
    exists. In the merge-before-approval race it records the merge with a blank audience and never
    revisits it, so a just-approved-and-already-merged PR would silently miss the digest. Re-reading the
    merge state here — the moment the approval is saved — closes that race from the approval side,
    without depending on a webhook redelivery. Only stamps digest-enabled repos with no audience yet.

    Head gate, mirroring the webhook side in ``_record_merged_pull_request``: an approval covers one
    commit, so only stamp when the PR's live head (``pr_payload`` is the fresh get_pr from the head-moved
    guard above) is exactly the head this run approved. A PR pushed to a newer head after the approval
    and merged there must not inherit digest eligibility from an approval that never saw that head; skip
    fail-closed if the merged head is unknown or differs.
    """
    merged_head_sha = ((pr_payload.get("head") or {}).get("sha") or "").strip()
    if not merged_head_sha or merged_head_sha != run.head_sha:
        activity.logger.info(
            f"Skipping digest stamp for run {run.id}: merged head {merged_head_sha!r} != approved head {run.head_sha!r}"
        )
        return
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
