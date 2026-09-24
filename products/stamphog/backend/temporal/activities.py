"""Temporal activities for the stamphog review workflow.

Each activity is keyed only by ``StamphogReviewInput`` (review_run_id + team_id) and
re-loads the ``ReviewRun`` it needs. Bulky data (the PR payload, changed files, fetched
policy files, raw reviewer output) is persisted on ``ReviewRun.output`` between steps
rather than threaded through the workflow, keeping every Temporal payload well under the
~2 MiB limit.

The whole review engine (hard gates, tier classification, author familiarity, and
the LLM reviewer) runs inside the sandbox via the engine's own modules
(``products/stamphog/packages/pr-approval-agent/review_local.py``). The server never
processes repo content. It fetches PR data and the trusted default-branch policy over
the API, ships the engine and injects the policy into the sandbox, and reads back only a
single verdict JSON.
"""

from __future__ import annotations

import os
import json
import time
import shlex
import base64
import random
import threading
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.db import router
from django.utils import timezone
from django.utils.dateparse import parse_datetime

import yaml
import requests
from prometheus_client import Counter
from temporalio import activity

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import AIGatewayConfig, resolve_ai_gateway_config
from posthog.models import User
from posthog.ph_client import ph_scoped_capture
from posthog.temporal.common.utils import asyncify

from products.stamphog.backend.facade.enums import (
    TERMINAL_STATUSES,
    ReviewMode,
    ReviewRunStatus,
    ReviewTrigger,
    ReviewVerdict,
)
from products.stamphog.backend.logic.approvals import dismiss_stale_approvals_for_head
from products.stamphog.backend.logic.audiences import resolve_audiences
from products.stamphog.backend.logic.engine_pregate import (
    ENGINE_DIR,
    PregateOutcome,
    engine_source_files,
    owners_package_files,
    pregate_skip_reason,
    run_engine_pregate,
)
from products.stamphog.backend.logic.familiarity_facts import ReviewHistory, fetch_review_history
from products.stamphog.backend.logic.github_client import StamphogGitHubClient, expected_app_bot_login
from products.stamphog.backend.logic.refusal_summary import summarize_refusal
from products.stamphog.backend.logic.review_trigger import trigger_for_run
from products.stamphog.backend.logic.reviewer import (
    ReviewerInvocation,
    ReviewerVerdict,
    build_reviewer_invocation,
    parse_reviewer_output,
)
from products.stamphog.backend.logic.scrubbing import neutralize_active_markdown, scrub_credentials
from products.stamphog.backend.models import PullRequest, PullRequestAudience, ReviewRun, StamphogRepoConfig
from products.stamphog.backend.temporal.constants import (
    CLONE_STEP_TIMEOUT_SECONDS,
    PREFETCH_DIFF_BLOBS_TIMEOUT_SECONDS,
    REVIEWER_TIMEOUT_SECONDS,
    RUN_REVIEW_TIMEOUT,
    SANDBOX_PHASE_RESERVE_SECONDS,
    STAMPHOG_BOT_EYES_MAX_AGE_SECONDS,
    STAMPHOG_OPTIONAL_POLICY_PATHS,
    STAMPHOG_POLICY_ENTRYPOINT,
    STAMPHOG_POLICY_PATHS,
    STAMPHOG_REVIEW_GUIDANCE_PATH,
    STAMPHOG_REVIEWHOG_LABEL,
    STAMPHOG_SANDBOX_CONTEXT_PATH,
    STAMPHOG_SANDBOX_ENGINE_DIR,
    STAMPHOG_SANDBOX_OWNERS_DIR,
    STAMPHOG_SANDBOX_REPO_DIR,
    STAMPHOG_TRUSTED_REACTOR_BOTS,
    SandboxPhaseError,
)
from products.tasks.backend.facade.sandbox import (
    SandboxBase,
    SandboxConfig,
    SandboxTemplate,
    get_sandbox_class_for_backend,
)

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


# aio_ continues the series the Action-era runs emitted; the engine blob carries the same word.
STAMPHOG_AI_PRODUCT = "aio_stamphog"
# The cap bounds what a leaked token can spend; the TTL must outlive the 30-minute review activity.
_REVIEWER_TOKEN_CAP_USD = "5"
_REVIEWER_TOKEN_TTL_SECONDS = 3600
_MINT_ATTEMPTS = 4
_MINT_TIMEOUT_SECONDS = 3
# Waits of about 1s, 2s and 4s before the retries, plus jitter so a fleet of workers refused at
# once does not come back in step. A Retry-After the gateway sends wins, clamped to the same
# ceiling: the whole mint must stay short against the review activity's start-to-close timeout.
_MINT_BACKOFF_SECONDS = 1.0
_MINT_MAX_BACKOFF_SECONDS = 10.0

AI_GATEWAY_TOKEN_MINTS = Counter(
    "stamphog_ai_gateway_token_mints_total",
    "Scoped-token mint attempts for hosted stamphog reviews",
    labelnames=["result"],
)


def _gateway_root(gateway: AIGatewayConfig) -> str:
    # The config URL carries the OpenAI /v1 base; the token routes hang off the gateway root.
    return gateway.url.rstrip("/").removesuffix("/v1")


def _is_legacy_stamphog_route(url: str) -> bool:
    # The legacy Python gateway resolves the product from the path, so its route ends in the slug.
    return urlparse(url).path.rstrip("/").endswith("/stamphog/v1")


def _connected_user(run: ReviewRun) -> User:
    """The connecting user every sandbox credential is minted under; missing or inactive fails the run."""
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
    return user


def _retry_after_seconds(response: requests.Response) -> float | None:
    """Seconds the gateway asked the caller to wait, from either Retry-After form; None if unusable."""
    header = response.headers.get("Retry-After")
    if not header:
        return None
    try:
        return max(0.0, float(header.strip()))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())


def _mint_backoff_seconds(attempt: int, retry_after: float | None) -> float:
    """What to wait before the next mint attempt: the gateway's own answer, else exponential backoff."""
    if retry_after is not None:
        return min(retry_after, _MINT_MAX_BACKOFF_SECONDS)
    delay = min(_MINT_BACKOFF_SECONDS * 2**attempt, _MINT_MAX_BACKOFF_SECONDS)
    return delay + random.uniform(0, delay / 4)


def _mint_reviewer_scoped_token(gateway: AIGatewayConfig, run: ReviewRun, user: User) -> str:
    """Per-run ``phe_`` minted with the worker's ``phs_``, which never enters the sandbox.

    Pinned to product and team and capped in spend and lifetime, so a leak buys little. Retries with
    growing backoff on 429, 5xx and network errors; any other refusal is final, and hosted runs have
    no shared-key fallback. A token minted without a requested model pin is revoked and fails the
    run. Kept separate from the tasks and wizard minters: each product owns its failure posture, and
    this cap and TTL are documented invariants rather than ops knobs.
    """
    body: dict[str, object] = {
        "cap_usd": _REVIEWER_TOKEN_CAP_USD,
        "ttl_seconds": _REVIEWER_TOKEN_TTL_SECONDS,
        "product": STAMPHOG_AI_PRODUCT,
        "obo": str(run.team_id),
    }
    if user.distinct_id:
        body["user"] = user.distinct_id
    # An empty entry (a trailing comma) is a mint 400, which fails every review.
    allowed_models = [model.strip() for model in settings.STAMPHOG_REVIEWER_TOKEN_ALLOWED_MODELS if model.strip()]
    if allowed_models:
        body["allowed_models"] = allowed_models
    mint_url = f"{_gateway_root(gateway)}/v1/tokens"
    last_error = ""
    for attempt in range(_MINT_ATTEMPTS):
        retry_after: float | None = None
        try:
            response = requests.post(
                mint_url,
                json=body,
                headers={"Authorization": f"Bearer {gateway.api_key}"},
                timeout=_MINT_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            last_error = type(e).__name__
        else:
            if 200 <= response.status_code < 300:
                try:
                    payload = response.json()
                    token = payload["token"]
                except (ValueError, TypeError, KeyError):
                    payload, token = {}, None
                if token:
                    if allowed_models and not payload.get("allowed_models"):
                        # A gateway that predates the pin field ignores it and mints an unpinned token.
                        _release_reviewer_token(gateway, token)
                        AI_GATEWAY_TOKEN_MINTS.labels(result="unpinned").inc()
                        raise RuntimeError(
                            "The gateway minted the reviewer token without the required model pin; "
                            "the gateway must support allowed_models before the reviewer model list is set"
                        )
                    AI_GATEWAY_TOKEN_MINTS.labels(result="ok").inc()
                    return token
                last_error = "mint response carried no token"
                break
            if response.status_code == 429 or response.status_code >= 500:
                last_error = f"HTTP {response.status_code}"
                retry_after = _retry_after_seconds(response)
            else:
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                break
        if attempt < _MINT_ATTEMPTS - 1:
            time.sleep(_mint_backoff_seconds(attempt, retry_after))
    AI_GATEWAY_TOKEN_MINTS.labels(result="error").inc()
    raise RuntimeError(
        f"Could not mint the sandbox gateway token ({last_error}); hosted reviews require the LLM gateway"
    )


def _release_reviewer_token(gateway: AIGatewayConfig, token: str) -> None:
    """Best-effort revoke of a token the run no longer needs; the TTL outlives the review by design.

    A failure only logs (the token then expires) and never changes the run's outcome.
    """
    try:
        response = requests.post(
            f"{_gateway_root(gateway)}/v1/tokens/revoke",
            json={"token": token},
            headers={"Authorization": f"Bearer {gateway.api_key}"},
            timeout=_MINT_TIMEOUT_SECONDS,
        )
        if not 200 <= response.status_code < 300:
            outcome = f"HTTP {response.status_code}"
        else:
            # The gateway answers 200 with revoked=false when no token matched.
            outcome = "ok" if response.json().get("revoked", True) else "no such token"
    except Exception as e:  # noqa: BLE001 — a revoke failure must never mask the review outcome
        outcome = type(e).__name__
    if outcome != "ok":
        activity.logger.warning(f"Could not revoke the reviewer token ({outcome}); it expires with its TTL")


def _hosted_analytics_properties(run: ReviewRun) -> dict[str, object]:
    properties: dict[str, object] = {
        "stamphog_runtime": "hosted",
        "stamphog_team_id": run.team_id,
        "stamphog_review_run_id": str(run.id),
    }
    # Marks self-driving inbox reviews (never set for human PRs) so analytics can tell the engine's
    # completed events and LLM traces apart from reviews of human PRs.
    if (run.output or {}).get("inbox_review"):
        properties["stamphog_self_driving_review"] = True
    return properties


def _engine_analytics_environment(properties: dict[str, object]) -> dict[str, str]:
    """The env the engine reads to emit its events: the capture key and host, plus the extra properties."""
    env = {key: value for key in ("POSTHOG_API_KEY", "POSTHOG_HOST") if (value := os.environ.get(key))}
    env["STAMPHOG_EXTRA_PROPERTIES"] = json.dumps(properties, separators=(",", ":"))
    return env


def _reviewer_environment(run: ReviewRun) -> tuple[dict[str, str], AIGatewayConfig]:
    """Environment for the in-sandbox reviewer.

    The sandbox holds no GitHub token by design, and no long-lived LLM credential either: the only
    secret it receives is a per-run minted gateway token. A gateway is mandatory for hosted runs —
    the engine's raw-Anthropic fallback exists for a local run, where the env is the developer's
    own, and an org-wide Anthropic key must never ride into a sandbox that runs an LLM over untrusted
    PR content.

    ``AI_GATEWAY_URL`` and ``AI_GATEWAY_API_KEY`` name the Go ai-gateway and the worker's ``phs_``;
    the token is a per-run ``phe_`` the caller revokes once the sandbox is gone. The sandbox sees
    the same two names with the token in place of the key.

    POSTHOG_API_KEY/POSTHOG_HOST let the engine emit its stamphog_review_completed event and LLM
    traces from inside the sandbox. The capture key is a public project write token — the same class of
    token every frontend snippet ships — so its blast radius is event spam, not data access; it's still
    added to llm_env_secrets so persisted output stays tidy. STAMPHOG_EXTRA_PROPERTIES stamps the
    hosted runtime/team/run context onto those events.
    """
    gateway = resolve_ai_gateway_config()
    if gateway is None:
        raise RuntimeError(
            "AI_GATEWAY_URL and AI_GATEWAY_API_KEY must both be set; hosted reviews require the ai-gateway"
        )
    if _is_legacy_stamphog_route(gateway.url):
        raise RuntimeError(
            "AI_GATEWAY_API_KEY is set but AI_GATEWAY_URL is the legacy stamphog route; "
            "the ai-gateway key belongs with the ai-gateway URL"
        )
    token = _mint_reviewer_scoped_token(gateway, run, _connected_user(run))
    env = {
        "STAMPHOG_REPO_DIR": STAMPHOG_SANDBOX_REPO_DIR,
        "AI_GATEWAY_URL": gateway.url,
        "AI_GATEWAY_API_KEY": token,
    }
    return {**env, **_engine_analytics_environment(_hosted_analytics_properties(run))}, gateway


def _sandbox_egress_allowlist(gateway_url: str) -> list[str]:
    """Outbound domains the review sandbox may reach; Modal fences off everything else.

    The sandbox env carries a live (if short-lived, narrowly scoped) credential next to an LLM
    reading untrusted PR content. Output scrubbing covers what the server persists, but nothing else
    stops a prompt-injected reviewer from POSTing what it holds to an arbitrary host — closing egress
    to the hosts a review actually needs removes that channel: github.com for the clone, PyPI for the
    engine's pinned deps, the gateway for LLM calls, and the PostHog capture host for telemetry.
    ``gateway_url`` is the URL handed to the sandbox, so egress cannot drift from the route it calls.
    STAMPHOG_SANDBOX_EXTRA_EGRESS_DOMAINS is the ops escape hatch for a missing legitimate host.
    The docker backend (local dev) ignores the allowlist.
    """
    domains = ["github.com", "pypi.org", "files.pythonhosted.org"]
    for url in (gateway_url, os.environ.get("POSTHOG_HOST", "")):
        host = urlparse(url).hostname
        if host:
            domains.append(host)
    domains.extend(domain.strip() for domain in settings.STAMPHOG_SANDBOX_EXTRA_EGRESS_DOMAINS if domain.strip())
    return list(dict.fromkeys(domains))


def _resolve_sandbox_backend() -> str:
    """Map the shared ``SANDBOX_PROVIDER`` setting onto a get_sandbox_class_for_backend key.

    Unset means the production default (Modal); local dev sets ``docker`` or ``MODAL_DOCKER``.
    """
    provider = getattr(settings, "SANDBOX_PROVIDER", None)
    return provider if provider else "modal"


def _pr_commit_messages(client: StamphogGitHubClient, repo: str, pr_number: int, head_sha: str) -> list[str] | None:
    """The PR's commit messages for the engine's provenance trailers, or None when they are unavailable.

    Provenance is advisory, so a GitHub error leaves it out of the review instead of failing it.
    """
    try:
        return client.get_pr_commit_messages(repo, pr_number, head_sha)
    except Exception:
        activity.logger.warning(f"stamphog: PR commit messages unavailable for {repo}#{pr_number}", exc_info=True)
        return None


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
    # Self-driving runs skip the author's history: the author is the App machine user, so
    # familiarity from its merged PRs would read to the engine as human trust. Without facts the
    # engine only omits the familiarity section from the reviewer prompt; the review proceeds normally.
    is_inbox_review = bool((run.output or {}).get("inbox_review"))
    # The familiarity facts cost a few GraphQL round trips and depend only on the PR and its files,
    # so they are read in a background thread while the fetches below run. fetch_review_history
    # bounds its own time and never raises.
    history_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stamphog-review-history")
    history_future = history_executor.submit(
        fetch_review_history, client, repo, pr, files, include_familiarity=not is_inbox_review
    )
    history_executor.shutdown(wait=False)
    # Reviews feed the engine's prerequisite gate — an active CHANGES_REQUESTED must block auto-approval.
    reviews = client.get_pr_reviews(repo, pull_request.pr_number)
    # Top-level discussion comments are blocker context (a maintainer's "please hold").
    discussion = client.get_pr_discussion(repo, pull_request.pr_number)
    # Inline review threads (GraphQL-only) carry a maintainer's unresolved "do not merge" that the
    # top-level discussion misses; fails closed on truncation/errors, same as get_pr_discussion.
    review_threads = client.get_pr_review_threads(repo, pull_request.pr_number)
    # Head-commit check runs let the engine's migration gate see a passing "Migration risk" check.
    check_runs = client.get_check_runs(repo, run.head_sha)
    commit_messages = _pr_commit_messages(client, repo, pull_request.pr_number, run.head_sha)

    author = (pr.get("user") or {}).get("login") or pull_request.author_login
    # Skipped for self-driving runs, like the familiarity facts above.
    author_pr_numbers = client.get_author_merged_pr_numbers(repo, author) if author and not is_inbox_review else []
    # The engine cannot resolve which of the owning teams the author belongs to. The sandbox holds
    # no token, and the engine learns the owning teams only after it reads the checkout's ownership
    # sources. One bulk lookup here gives the engine every team that the author belongs to, and the
    # engine intersects that list with the teams that own the changed paths. Inbox reviews skip this
    # lookup for the same reason that they skip author_pr_numbers: the author is the App machine
    # user, so its team membership says nothing about who wrote the diff.
    author_team_slugs = client.get_user_team_slugs(repo.split("/")[0], author) if author and not is_inbox_review else []

    policy_files: dict[str, str] = {}
    for path in (*STAMPHOG_POLICY_PATHS, *STAMPHOG_OPTIONAL_POLICY_PATHS):
        content = client.get_default_branch_file(repo, path)
        if content is not None:
            policy_files[path] = content

    history: ReviewHistory = history_future.result()

    run.output = {
        **(run.output or {}),
        "pr": pr,
        "files": files,
        "reviews": reviews,
        "discussion": discussion,
        "review_threads": review_threads,
        "check_runs": check_runs,
        "pr_reactions": client.get_pr_reactions(repo, pull_request.pr_number),
        "policy_files": policy_files,
        "author_pr_numbers": author_pr_numbers,
        "author_team_slugs": author_team_slugs,
        # Always set, null included: its presence tells the engine the server owns familiarity,
        # so a null means "absent" rather than "compute it from git".
        "familiarity_facts": history.familiarity_facts,
        "merge_base_sha": history.merge_base_sha,
        # Always set, null included, for the same reason: the sandbox checkout holds no history,
        # so the engine must not fall back to `git log` for the provenance trailers.
        "commit_messages": commit_messages,
    }
    run.save(update_fields=["output", "updated_at"])

    activity.logger.info(f"Fetched review context for run {run.id} (pr #{pull_request.pr_number}, {len(files)} files)")
    return {"pr_number": pull_request.pr_number, "file_count": len(files), "head_sha": run.head_sha}


@activity.defn
@asyncify
def dismiss_stale_approvals(input: StamphogReviewInput) -> dict:
    """Retract every standing stamphog approval before this run reviews — old-head AND same-head.

    GitHub never auto-dismisses an APPROVE review, so a prior run's approval keeps satisfying
    required reviews after a push (old head) or across a same-head re-review whose fresh verdict
    might refuse. This runs FIRST in the workflow — before context fetch, before the sandbox — on
    purpose: dismiss, then re-review. That ordering is fail-closed — if any later step crashes
    (even the context fetch), the prior approval is already gone rather than left standing over a
    diff or verdict it no longer represents. It needs only the run row, so nothing is fetched first.
    """
    run = _load_run(input)
    if run.status == ReviewRunStatus.SUPERSEDED:
        activity.logger.info(f"Skipping approval dismissal for superseded run {run.id}")
        return {"skipped": "superseded"}

    pull_request = run.pull_request
    repo_config = pull_request.repo_config

    # current_head_sha="" on purpose: a new run voids EVERY standing approval, same-head included.
    # A same-head re-review (label re-add, reopen, ready-for-review) means fresh judgment is
    # pending — if it refuses, an earlier same-head approval must not keep the PR mergeable. The
    # sweep's same-head exclusion remains for the skip paths, where no new review will run and the
    # current-head approval is still the delivered verdict.
    message = "A new stamphog review started for this PR — the fresh verdict replaces this approval."
    dismissed = dismiss_stale_approvals_for_head(input.team_id, pull_request, repo_config, "", message=message)

    # Belt-and-braces GitHub-side sweep (see _sweep_own_github_approvals): the DB sweep above keys off
    # posted_review_id, so an approval this App left on GitHub with NO ReviewRun row carrying its id (a run
    # that approved but crashed before persisting, or any other drift) is invisible to it and would stand
    # forever. keep_review_ids=frozenset() voids everything, regardless of head — the same all-heads
    # semantic the DB sweep uses at workflow start.
    client = StamphogGitHubClient(repo_config.installation_id)
    github_dismissed = _sweep_own_github_approvals(
        client, repo_config, pull_request, message, keep_review_ids=frozenset()
    )

    activity.logger.info(
        f"Dismissed {dismissed} DB-tracked + {github_dismissed} GitHub-side stale approval(s) "
        f"for run {run.id} (pr #{pull_request.pr_number})"
    )
    return {"dismissed": dismissed, "github_dismissed": github_dismissed}


@activity.defn
@asyncify
def signal_review_started(input: StamphogReviewInput) -> dict:
    """Post stamphog's own 👀 on the PR the moment this run commits to reviewing.

    Mirrors the convention this same workflow reads off OTHER bots (``STAMPHOG_TRUSTED_REACTOR_BOTS``,
    ``list_in_flight_reviewer_bots``): a fresh 👀 means "a review is in flight". Emitting it lets other
    tooling (and a human watching the PR) see stamphog is actively working, the same signal every other
    reviewer bot already gives. Runs right after ``dismiss_stale_approvals`` — the moment this run
    commits to reviewing — so the 👀 appears before the (possibly long) context fetch and sandbox run.
    Cosmetic only: ``add_pr_reaction`` fails open (see its docstring), so a reaction hiccup here never
    fails or retries this activity, let alone the review itself. The returned reaction id (if any) rides
    on ``run.output`` so the terminal activities (``post_verdict``, ``mark_review_failed``) can remove it.
    """
    run = _load_run(input)
    if run.status == ReviewRunStatus.SUPERSEDED:
        return {"reaction_id": None}
    pull_request = run.pull_request
    repo_config = pull_request.repo_config
    client = StamphogGitHubClient(repo_config.installation_id)
    reaction_id = client.add_pr_reaction(repo_config.repository, pull_request.pr_number)
    run.output = {**(run.output or {}), "own_eyes_reaction_id": reaction_id}
    run.save(update_fields=["output", "updated_at"])
    return {"reaction_id": reaction_id}


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
    # Exclude stamphog's own bot login: STAMPHOG_TRUSTED_REACTOR_BOTS is a hardcoded set of OTHER
    # reviewer bots' logins, so this app's own 👀 (posted by signal_review_started) can't collide
    # with it today — but that set is just literal strings, not a same-app check, so a future
    # addition or a misconfigured STAMPHOG_GITHUB_APP_SLUG could make stamphog wait out itself.
    own_login = (expected_app_bot_login() or "").lower()
    in_flight = sorted(
        {
            reaction["user"]
            for reaction in reactions
            if reaction.get("content") == "eyes"
            and (login := (reaction.get("user") or "").lower()) in STAMPHOG_TRUSTED_REACTOR_BOTS
            and login != own_login
            and (created := parse_datetime(reaction.get("created_at") or "")) is not None
            and (now - created).total_seconds() <= STAMPHOG_BOT_EYES_MAX_AGE_SECONDS
        }
    )
    if in_flight:
        activity.logger.info(f"Run {run.id}: reviewer bot(s) in flight: {', '.join(in_flight)}")
    return {"in_flight": in_flight}


def _sandbox_deadline() -> float:
    """Monotonic time the sandbox phase has to finish by, measured from Temporal's own clock.

    Temporal starts RUN_REVIEW_TIMEOUT when it hands the activity task to the worker, which can be
    well before this code runs: ``@asyncify`` queues the synchronous body on an executor, and the
    run load, token fetch and invocation build all happen before a sandbox exists. Anchoring on
    ``started_time`` charges every one of those to the budget, so no step is granted time the
    activity itself does not have. A missing ``started_time`` falls back to the full budget, which
    is the behaviour of a worker that is not queueing.
    """
    budget = RUN_REVIEW_TIMEOUT.total_seconds() - SANDBOX_PHASE_RESERVE_SECONDS
    try:
        elapsed = (datetime.now(UTC) - activity.info().started_time).total_seconds()
    except Exception:
        elapsed = 0.0
    # Only an absent or nonsensical start time falls back. An elapsed time past the whole budget is
    # a real answer, and it yields a deadline in the past, so the first step refuses rather than
    # provisioning a sandbox the activity has no time left to use.
    return time.monotonic() + budget - max(elapsed, 0.0)


def _step_timeout(deadline: float, ceiling_seconds: int) -> int:
    """Seconds the next sandbox step may take: its own ceiling, or the rest of the budget.

    Every step inside the review activity shares one deadline, so a step that runs long
    shortens the next one instead of pushing the activity past its start-to-close timeout.
    Temporal kills the activity at that timeout with no verdict and no notice for the author,
    so the phases must not be able to over-commit the budget between them.
    """
    remaining = int(deadline - time.monotonic())
    if remaining <= 0:
        raise RuntimeError("the review budget ran out before the sandbox phase finished")
    return min(ceiling_seconds, remaining)


class _StepTimer:
    """Wall-clock milliseconds per sandbox step, for the run output and the worker log."""

    def __init__(self) -> None:
        self.timings_ms: dict[str, int] = {}

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        # Recorded on failure too, so the log line shows how long the failing step ran.
        started = time.monotonic()
        try:
            yield
        finally:
            self.timings_ms[name] = int((time.monotonic() - started) * 1000)


def _destroy_sandbox_in_background(sandbox: SandboxBase, run_id: str) -> None:
    """Tear the sandbox down on a daemon thread, so the verdict does not wait for it.

    The provider's terminate call blocks until the sandbox is gone, and nothing after the reviewer
    needs the sandbox. A failed or lost teardown only leaves an orphan, and an orphan
    self-terminates when SandboxConfig.ttl_seconds expires. That includes a thread that dies with
    its worker.
    """

    def destroy() -> None:
        try:
            sandbox.destroy()
        except Exception:
            activity.logger.exception(f"Failed to destroy sandbox for run {run_id}")

    threading.Thread(target=destroy, name=f"stamphog-destroy-{run_id}", daemon=True).start()


def _review_invocation(run: ReviewRun, merge_base_sha: str | None) -> ReviewerInvocation:
    """The engine context and command for this run, shared by the pre-check and the sandbox review."""
    output = run.output or {}
    pr = output.get("pr", {})
    return build_reviewer_invocation(
        pr=pr,
        files=output.get("files", []),
        reviews=output.get("reviews", []),
        discussion=output.get("discussion", []),
        review_threads=output.get("review_threads", []),
        check_runs=output.get("check_runs", []),
        pr_reactions=output.get("pr_reactions", []),
        author_pr_numbers=output.get("author_pr_numbers", []),
        author_team_slugs=output.get("author_team_slugs", []),
        # A run whose context predates the server facts gets None, which the engine reads as an
        # absent signal. The sandbox checkout holds no history for it to fall back on.
        familiarity_facts=output.get("familiarity_facts"),
        commit_messages=output.get("commit_messages"),
        base_sha=(pr.get("base") or {}).get("sha") or "",
        merge_base_sha=merge_base_sha,
        head_sha=run.head_sha,
        repo=run.pull_request.repo_config.repository,
        engine_dir=STAMPHOG_SANDBOX_ENGINE_DIR,
        context_path=STAMPHOG_SANDBOX_CONTEXT_PATH,
        # The engine's carve-out for bot-authored drafts keys off this flag alone. It comes only
        # from the run's inbox provenance, stamped after the PR is linked to a signals run.
        self_driving_review=bool(output.get("inbox_review")),
        # Read as a description rather than a permission: the reviewer is told why it was asked,
        # and decides for itself what that means for this diff.
        review_trigger=trigger_for_run(output=output, review_mode=run.pull_request.repo_config.review_mode),
    )


def _fast_refusal_summary(run: ReviewRun, outcome: PregateOutcome) -> str | None:
    """A short LLM note for the refusal, or None, in which case the engine's gate messages stand in.

    Same gateway, token scope and model as the sandbox reviewer. Every failure is soft: the verdict
    is already REFUSED, so the note must never delay or fail it.
    """
    gateway = resolve_ai_gateway_config()
    if gateway is None or _is_legacy_stamphog_route(gateway.url) or outcome.result is None:
        return None
    try:
        token = _mint_reviewer_scoped_token(gateway, run, _connected_user(run))
    except Exception:
        activity.logger.warning(f"Run {run.id}: no gateway token for the refusal summary; using the gate messages")
        return None
    output = run.output or {}
    try:
        return summarize_refusal(
            gateway_root=_gateway_root(gateway),
            token=token,
            model=outcome.summary_model,
            gates=outcome.result.get("gates") or [],
            pr=output.get("pr") or {},
            files=output.get("files") or [],
            attribution={**_hosted_analytics_properties(run), "stamphog_fast_path": True},
        )
    finally:
        _release_reviewer_token(gateway, token)


def _refuse_on_pre_gates(run: ReviewRun) -> dict:
    output = run.output or {}
    skip_reason = pregate_skip_reason(output.get("pr") or {}, output.get("files") or [], run.head_sha)
    if skip_reason is not None:
        activity.logger.info(f"Run {run.id}: pre-gates skipped ({skip_reason})")
        return {"refused": False, "skipped": skip_reason}

    context = json.loads(_review_invocation(run, output.get("merge_base_sha")).context_json)
    # The same trusted set the sandbox injects, so both runs judge the PR under the same policy.
    policy_files = _effective_policy_files(run.pull_request.repo_config.repository, output.get("policy_files", {}))
    timer = _StepTimer()
    # No analytics env on this first run: it only decides, and the posted run below emits the event.
    with timer.step("pregate"):
        outcome = run_engine_pregate(context, policy_files, environment={})
    if not outcome.final_deny:
        return {"refused": False}

    summary = None
    if outcome.needs_summary:
        with timer.step("summary"):
            summary = _fast_refusal_summary(run, outcome)
    if summary:
        context["refusal_reasoning"] = summary
    properties = {
        **_hosted_analytics_properties(run),
        "stamphog_fast_path": True,
        "stamphog_fast_path_summary": "llm" if summary else "gate_messages",
    }
    with timer.step("render"):
        final = run_engine_pregate(context, policy_files, environment=_engine_analytics_environment(properties))
    if not final.final_deny or final.result is None:
        raise RuntimeError("the engine pre-check changed its answer between two runs on the same context")

    # The same last-line JSON contract the sandbox prints, so post_verdict parses it unchanged. The
    # summary is LLM text over PR content, so it gets the same scrub as the sandbox's stdout.
    run.output = {
        **(run.output or {}),
        "reviewer_raw": scrub_credentials(json.dumps(final.result)),
        "reviewer_exit_code": 0,
        "timings_ms": timer.timings_ms,
        "fast_path": True,
    }
    run.save(update_fields=["output", "updated_at"])
    activity.logger.info(f"Pre-gate refusal for run {run.id}; step timings: {timer.timings_ms}")
    return {"refused": True}


@activity.defn
@asyncify
def refuse_on_pre_gates(input: StamphogReviewInput) -> dict:
    """Refuse a PR on its deterministic gates alone, before the bot wait and the sandbox.

    Runs the engine's gate-only pre-check on the stored context (see logic/engine_pregate.py). Only a
    deny the full review would also reach counts, and then the refusal is persisted in the sandbox's
    output shape, so post_verdict and everything after it work unchanged. Everything else, including
    any failure here, returns ``refused: False`` and the run takes the full review path, which runs
    every gate again. This step can therefore only make a refusal faster, never cause one.
    """
    run = _load_run(input)
    if run.status == ReviewRunStatus.SUPERSEDED:
        return {"refused": False, "skipped": "superseded"}
    try:
        return _refuse_on_pre_gates(run)
    except Exception:
        activity.logger.exception(f"Run {run.id}: pre-gates failed; falling through to the full review")
        return {"refused": False, "skipped": "error"}


@activity.defn
@asyncify
def run_review_in_sandbox(input: StamphogReviewInput) -> dict:
    """Provision a sandbox, clone the PR, run the full engine offline, stash its raw output."""
    deadline = _sandbox_deadline()
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
    policy_files = output.get("policy_files", {})

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
    # The context fetch stores the merge base, but it keeps going without one, because familiarity
    # only degrades. The shallow checkout cannot diff without it, so read it again here. A failure
    # raises before the sandbox exists, and the activity retries.
    merge_base_sha = output.get("merge_base_sha") or client.get_merge_base_sha(repo, base_sha, run.head_sha)

    invocation = _review_invocation(run, merge_base_sha)

    sandbox_class = get_sandbox_class_for_backend(_resolve_sandbox_backend())
    environment, gateway = _reviewer_environment(run)
    # Per-run credential, not in the worker env — scrub it explicitly wherever sandbox output
    # is persisted or raised (llm_env_secrets only covers worker-env values).
    gateway_token = environment["AI_GATEWAY_API_KEY"]
    # Every path from here releases the token, including a failed claim read or save.
    try:
        config = SandboxConfig(
            name=f"stamphog-review-{run.id}",
            template=SandboxTemplate.STAMPHOG_REVIEW,
            metadata={"review_run_id": str(run.id)},
            environment_variables=environment,
            outbound_domain_allowlist=_sandbox_egress_allowlist(environment["AI_GATEWAY_URL"]),
        )
        # The steps above cost nothing and keep their own exception type. From here the run makes a
        # sandbox and can run the reviewer, so failures raise SandboxPhaseError, which the retry policy
        # excludes. Both statements stay outside the try below, so the refusal keeps its own type and a
        # failed write stays retryable.
        #
        # Temporal applies the start-to-close timeout and retries a lost worker. Neither path raises a
        # type this code can mark, so the claim is what stops a second sandbox. Read it from the writer,
        # because a stalled attempt holds a copy from before its replacement wrote. Read and then write
        # is not atomic: two attempts in the same instant both pass. A column and a conditional update
        # would close that.
        latest_output = (
            ReviewRun.objects.for_team(input.team_id)
            .using(router.db_for_write(ReviewRun))
            .filter(id=run.id)
            .values_list("output", flat=True)
            .first()
        ) or {}
        if latest_output.get("sandbox_started_at"):
            raise SandboxPhaseError("an earlier attempt already provisioned a sandbox for this run")
        run.output = {**latest_output, "sandbox_started_at": timezone.now().isoformat()}
        run.save(update_fields=["output", "updated_at"])

        timer = _StepTimer()
        # Sandbox creation draws on the same budget as the steps below it, so a slow provision
        # leaves the clone, the prefetch and the reviewer correspondingly less.
        try:
            # Raises when the budget is already gone, so an activity with no time left does not pay
            # for a box the first step would only reject.
            _step_timeout(deadline, CLONE_STEP_TIMEOUT_SECONDS)
            with timer.step("sandbox_create"):
                sandbox = sandbox_class.create(config)
            try:
                with timer.step("clone"):
                    _clone_pr(sandbox, repo, merge_base_sha, run.head_sha, run.pull_request.pr_number, token, deadline)
                with timer.step("prefetch"):
                    _prefetch_review_blobs(sandbox, merge_base_sha, token, deadline)
                # The prefetch swallows its own failure, including a timeout that consumed the rest
                # of the budget. Re-check here, because the three steps below write through the
                # sandbox filesystem API and cannot take a deadline: passing one would switch them
                # to an exec-based write, which is a different mechanism, not a bounded one.
                _step_timeout(deadline, REVIEWER_TIMEOUT_SECONDS)
                with timer.step("ship_engine"):
                    _inject_policy_files(sandbox, policy_files)
                    _ship_engine(sandbox)
                    _write_context(sandbox, invocation)

                command = (
                    f"cd {shlex.quote(STAMPHOG_SANDBOX_REPO_DIR)} && {_harden_reviewer_command(invocation.command)}"
                )
                with timer.step("reviewer"):
                    result = sandbox.execute(command, timeout_seconds=_step_timeout(deadline, REVIEWER_TIMEOUT_SECONDS))
            finally:
                # A destroy failure must not mask a completed review, because the verdict below still
                # has to be persisted and posted.
                with timer.step("destroy_dispatch"):
                    _destroy_sandbox_in_background(sandbox, str(run.id))
                activity.logger.info(f"Sandbox step timings for run {run.id}: {timer.timings_ms}")

            # Scrub stdout before persisting: it can echo the LLM keys the sandbox holds, and it is
            # both stored on run.output and re-read verbatim to render the verdict posted to GitHub.
            run.output = {
                **(run.output or {}),
                "reviewer_raw": scrub_credentials(result.stdout, token, gateway_token),
                "reviewer_exit_code": result.exit_code,
                "timings_ms": timer.timings_ms,
            }
            run.save(update_fields=["output", "updated_at"])

            if result.exit_code != 0:
                # The reviewer reads an untrusted PR head, so its stderr can contain repository content.
                # This message reaches run.error, so keep the stderr in the worker log only.
                activity.logger.error(
                    f"Reviewer exited with code {result.exit_code} for run {run.id}: "
                    f"{scrub_credentials(result.stderr, token, gateway_token)[:500]}"
                )
                raise RuntimeError(f"reviewer exited with code {result.exit_code}")
        except Exception as exc:
            # Give the type only. Every step in this phase touches the sandbox, and anyone with
            # stamphog:read can read run.error without access to the repository. The setup phase above
            # keeps its text, because it fails on our own infrastructure and must stay diagnosable.
            raise SandboxPhaseError(f"the sandbox phase failed with {type(exc).__name__}") from exc
    finally:
        _release_reviewer_token(gateway, gateway_token)

    activity.logger.info(f"Reviewer completed for run {run.id}")
    return {"exit_code": result.exit_code}


def _sweep_own_github_approvals(
    client: StamphogGitHubClient,
    repo_config: StamphogRepoConfig,
    pull_request: PullRequest,
    message: str,
    *,
    keep_review_ids: frozenset[int],
) -> int:
    """Dismiss every one of this App's still-active APPROVE reviews on the PR, except ``keep_review_ids``.

    Asks GitHub for our own still-active approvals and retracts each one regardless of head — the DB sweep
    keys off ``posted_review_id``, so an approval this App left on GitHub with no ReviewRun row carrying its
    id is invisible to it. Identity fails closed without a configured app slug (``list_own_active_approvals``
    returns nothing), and ``dismiss_pr_review`` swallows 422, so re-dismissing an already-retracted review is
    an idempotent no-op. Returns the count dismissed.

    ``keep_review_ids`` spares specific reviews: the terminal-sweep caller passes the persisted approval ids
    of OTHER live runs so a slow run at its own terminal never dismisses a newer run's legit approval.
    ``dismiss_stale_approvals`` passes an empty set — at workflow start every standing approval goes.
    """
    dismissed = 0
    for review in client.list_own_active_approvals(repo_config.repository, pull_request.pr_number):
        review_id = _comment_id(review)
        if review_id is None or review_id in keep_review_ids:
            continue
        client.dismiss_pr_review(repo_config.repository, pull_request.pr_number, review_id, message)
        dismissed += 1
    return dismissed


def _peer_persisted_approval_ids(team_id: int, pull_request: PullRequest, run: ReviewRun) -> frozenset[int]:
    """Persisted approval ids of OTHER live runs on this PR — the terminal sweep's allow-list.

    A run reaching a non-approve terminal re-runs the GitHub-side own-approvals sweep to catch an orphan an
    older, superseded run posted after this (newer) run's startup sweep already ran. But it must never
    dismiss a NEWER run's legitimately posted approval, so keep every ``posted_review_id`` on a run for this
    PR that still holds a live status (not superseded, not failed) — those approvals stand on purpose.

    Writer-pinned: this read gates a GitHub write, and a lagged replica could miss a newer run's freshly
    persisted approval and dismiss it (see CLAUDE.md reader-lag invariant).
    """
    peer_ids = (
        ReviewRun.objects.for_team(team_id)
        .using(router.db_for_write(ReviewRun))
        .filter(pull_request=pull_request, posted_review_id__isnull=False)
        .exclude(id=run.id)
        .exclude(status__in=(ReviewRunStatus.SUPERSEDED, ReviewRunStatus.FAILED))
        .values_list("posted_review_id", flat=True)
    )
    return frozenset(review_id for review_id in peer_ids if review_id is not None)


_TERMINAL_SWEEP_MESSAGE = (
    "This stamphog run finished without approving — retracting an approval an earlier run left standing so "
    "it can't satisfy required reviews over a verdict that no longer approves."
)


def _sweep_orphan_approvals_at_terminal(client: StamphogGitHubClient, run: ReviewRun, team_id: int) -> None:
    """Re-run the GitHub-side own-approvals sweep when a run ends WITHOUT a standing approval of its own.

    Closes the supersession orphan race: an older run can clear post_verdict's final guards, get superseded,
    then land its GitHub approval AFTER the newer run's startup sweep already ran. If the newer run's verdict
    is non-APPROVE (or the run fails), nothing lists our own approvals again, so the orphan satisfies branch
    protection over a refusing verdict until some future run sweeps. Running the sweep at this run's own
    terminal catches it — the run that superseded the orphan-poster is the natural place to clean up.

    ``keep_review_ids`` spares every OTHER live run's persisted approval, so a slow run at terminal can't
    dismiss a newer run's legit approval. UNLIKE the fail-closed STARTUP sweep, this one must not fail or
    retry the terminal transition if GitHub errors: the terminal save has to win, and the approval-integrity
    gap on error here is the pre-existing exposure, strictly no worse than before this sweep existed.
    """
    keep_review_ids = _peer_persisted_approval_ids(team_id, run.pull_request, run)
    try:
        _sweep_own_github_approvals(
            client,
            run.pull_request.repo_config,
            run.pull_request,
            _TERMINAL_SWEEP_MESSAGE,
            keep_review_ids=keep_review_ids,
        )
    except Exception:
        activity.logger.exception(
            f"Run {run.id}: terminal orphan-approval sweep failed; leaving the pre-existing exposure as-is"
        )


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


def _remove_own_eyes_reaction(client: StamphogGitHubClient, run: ReviewRun) -> None:
    """Remove this run's own "review in flight" 👀, if ``signal_review_started`` posted one.

    Called from the terminal activities (``post_verdict``'s completion path, ``mark_review_failed``)
    once this run is done actively reviewing — AFTER this run's terminal save, so the peer check
    below counts only genuinely-other live runs. No id on ``run.output`` means either the signal
    never posted one (fail-open there too) or a later run already adopted/removed it — either way,
    nothing to do. ``remove_pr_reaction`` itself fails open, so this never raises into the caller.

    GitHub keeps ONE 👀 per (user, content) per issue, so overlapping runs share the same reaction
    id: a run created after this one went terminal (a fresh delivery, not a supersession) adopts the
    identical id in its own ``signal_review_started``. Removing it here would strip the in-flight
    signal out from under that still-reviewing peer, so skip when a live peer exists — the last
    standing run removes. Writer-pinned: a lagged replica missing the just-created peer would remove
    under it (reader-lag invariant).
    """
    reaction_id = (run.output or {}).get("own_eyes_reaction_id")
    if not isinstance(reaction_id, int):
        return
    pull_request = run.pull_request
    live_peer_exists = (
        ReviewRun.objects.for_team(run.team_id)
        .using(router.db_for_write(ReviewRun))
        .filter(pull_request=pull_request)
        .exclude(id=run.id)
        .exclude(status__in=TERMINAL_STATUSES)
        .exists()
    )
    if live_peer_exists:
        activity.logger.info(f"Run {run.id}: leaving the shared in-flight reaction for a live peer run")
        return
    client.remove_pr_reaction(pull_request.repo_config.repository, pull_request.pr_number, reaction_id)


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
    # A base retarget (a stacked PR's parent merged, or a manual base switch) rewrites the reviewed
    # diff with the head SHA unchanged, so the head guard alone can't see it. The retarget delivery
    # retracts approvals and queues a fresh run, but that delivery can trail this activity. The SHA
    # is compared too: GitHub pins base.sha at the last PR event rather than tracking the trunk tip,
    # so it only moves when the PR itself was touched — the diff the sandbox reviewed is stale then.
    reviewed_base = (output.get("pr") or {}).get("base") or {}
    current_base = current_pr.get("base") or {}
    reviewed_base_ref = reviewed_base.get("ref") or ""
    reviewed_base_sha = reviewed_base.get("sha") or ""
    current_base_ref = (current_base.get("ref") or "").strip()
    current_base_sha = (current_base.get("sha") or "").strip()
    base_ref_moved = bool(reviewed_base_ref and current_base_ref and reviewed_base_ref != current_base_ref)
    base_sha_moved = bool(reviewed_base_sha and current_base_sha and reviewed_base_sha != current_base_sha)
    drift: tuple[str, str] | None = None
    if current_head and current_head != run.head_sha:
        drift = ("head_moved", f"head moved {run.head_sha} -> {current_head}")
    elif base_ref_moved or base_sha_moved:
        drift = (
            "base_retargeted",
            f"base moved {reviewed_base_ref}@{reviewed_base_sha} -> {current_base_ref}@{current_base_sha}",
        )
    if drift is not None:
        kind, detail = drift
        # Conditional: a retry after the terminal save already committed (e.g. the trailing digest
        # stamp crashed) must not rewrite a delivered COMPLETED outcome to SUPERSEDED — terminal
        # states are history. The stale-approval sweep retires that approval on the next delivery.
        ReviewRun.objects.for_team(input.team_id).filter(id=run.id).exclude(status__in=TERMINAL_STATUSES).update(
            status=ReviewRunStatus.SUPERSEDED, completed_at=timezone.now(), updated_at=timezone.now()
        )
        if run.verdict != ReviewVerdict.APPROVED:
            _dismiss_orphaned_approval(client, run, input.team_id)
        activity.logger.info(f"Skipping verdict for run {run.id}: {detail}")
        return {"verdict": f"skipped_{kind}"}

    parsed = parse_reviewer_output(raw)

    run.gate_result = parsed.gate_result
    # reviewer_raw was scrubbed on the way into the row; this re-scrub covers the worker's own LLM
    # env secrets, the same belt-and-braces the review body gets below.
    run.change_summary = scrub_credentials(parsed.change_summary)
    if parsed.stamphog_version:
        run.output = {**output, "stamphog_version": parsed.stamphog_version}

    update_fields = [
        "gate_result",
        "change_summary",
        "status",
        "verdict",
        "completed_at",
        "verdict_posted_at",
        "updated_at",
    ]
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

    # Computed before the branch chain because two things must agree on it: the trigger label is only
    # stripped for a refusal, and only then may the review tell the author to re-add it.
    is_refusal = parsed.verdict in (ReviewVerdict.REFUSED, ReviewVerdict.ESCALATE)
    strips_label = repo_config.review_mode == ReviewMode.LABEL and is_refusal

    relabel_label = repo_config.trigger_label if strips_label else None

    if parsed.gate_blocked:
        # The deterministic gates denied auto-review — a terminal, non-approval
        # outcome. The engine still rendered a plain-language explanation; post it.
        run.status = ReviewRunStatus.GATED
        run.verdict = ReviewVerdict.WAIT
    elif parsed.verdict == ReviewVerdict.APPROVED:
        # Idempotent under Temporal at-least-once retries: the id is persisted the moment GitHub
        # accepts the review, so a retry after any later crash skips re-approving.
        if run.posted_review_id is None:
            # Adopt-before-post: a prior attempt could have posted the approval to GitHub, then crashed
            # BEFORE the immediate-persist below — leaving an approval with no DB trace that the
            # posted_review_id-keyed sweep can never see. Re-posting would stack a SECOND standing
            # approval. So first ask GitHub whether we already have an active APPROVE pinned to exactly
            # this head; adopt its id instead of posting again if so. Identity fails closed without a
            # configured app slug (list_own_active_approvals returns nothing), so we never adopt another
            # bot's review off a fuzzy match — we post fresh, same as before.
            adopted_review_id: int | None = None
            for review in client.list_own_active_approvals(repo, pull_request.pr_number):
                if (review.get("commit_id") or "") != run.head_sha:
                    continue
                adopted_review_id = _comment_id(review)
                if adopted_review_id is not None:
                    break
            if adopted_review_id is not None:
                run.posted_review_id = adopted_review_id
            else:
                body = scrub_credentials(_verdict_body(parsed, ReviewVerdict.APPROVED, relabel_label))
                review = client.post_approve_review(repo, pull_request.pr_number, body, run.head_sha)
                run.posted_review_id = _comment_id(review)
            # Persist the id immediately, outside the conditional terminal save below: if that save
            # loses to a supersession or this activity crashes, this row is the only record the
            # approval exists — the orphan-dismissal paths and the stale-approval sweep need it. The
            # adopted id must be persisted exactly the same way as a freshly posted one.
            ReviewRun.objects.for_team(input.team_id).filter(id=run.id).update(
                posted_review_id=run.posted_review_id, updated_at=timezone.now()
            )
        run.status = ReviewRunStatus.COMPLETED
        run.verdict = ReviewVerdict.APPROVED
        update_fields.append("posted_review_id")
    else:
        run.status = ReviewRunStatus.COMPLETED
        run.verdict = parsed.verdict

    # One post for every non-approval, keyed off the verdict the run just stored, so the review text
    # and the recorded verdict cannot disagree. The approve branch above posted its own APPROVE.
    if run.verdict != ReviewVerdict.APPROVED:
        _post_non_approval_review(
            client, repo, run, pull_request, input.team_id, _verdict_body(parsed, run.verdict, relabel_label)
        )

    # Keyed off parsed.verdict, not run.verdict: the gate-blocked branch overrides run.verdict to WAIT,
    # but both the label-strip and the ReviewHog handoff below treat a gate-blocked refusal the same
    # as an engine-refused one.
    # Same reading the reviewer got, from the same stamp, so the handoff can't disagree with what
    # the run was told it was.
    trigger = trigger_for_run(output=output, review_mode=repo_config.review_mode)

    # Action parity: in label-triggered mode a refused/escalated verdict strips the trigger label, so
    # the author re-requests the next review by re-adding it.
    # A failure here raises on purpose: the activity retries and the sticky upsert above is idempotent.
    if strips_label:
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

    # Hand a refused/escalated PR to ReviewHog only AFTER the refusal verdict wins the terminal save
    # above — running it before would trigger ReviewHog for a stale refusal that a superseding delivery
    # then overrode (a newer run might approve the same head). Adding the ReviewHog trigger label fires
    # its workflow (review-hog.yml exempts stamphog[bot] from the bot-labeler-skip that would otherwise
    # strip it).
    #
    # Only self-driving runs hand off. A human PR has an author who reads the refusal and decides what
    # to do about it, and in ALL mode the handoff would fire on PRs nobody asked stamphog to look at.
    # A self-driving PR has no such author — the refusal sits unread until Inbox triage — so ReviewHog's
    # deeper review is the next step rather than a second unrequested opinion.
    #
    # This is a secondary, cross-product notification that must never jeopardize the verdict — the
    # refusal is already durably saved, so it is single-shot best-effort: catching every exception (not
    # just StamphogGitHubError) contains the client's own errors plus the GitHubRateLimitError /
    # requests.RequestException the egress layer raises on rate limits and network blips, neither a
    # subclass of StamphogGitHubError. The sticky upsert above is idempotent, so a missed handoff is a
    # missed handoff, not corruption.
    if is_refusal and trigger == ReviewTrigger.SELF_DRIVING.value:
        try:
            client.add_pr_label(repo, pull_request.pr_number, STAMPHOG_REVIEWHOG_LABEL)
        except Exception:
            # Format repo/pr into the message — activity.logger is a stdlib LoggerAdapter that
            # raises TypeError on arbitrary kwargs, which would escape this best-effort catch.
            activity.logger.exception(
                f"stamphog: reviewhog handoff failed for {repo}#{pull_request.pr_number}; verdict still posted"
            )

    # Close the merge-before-approval race only AFTER this run's APPROVED verdict is durably saved. If
    # the PR auto-merged the instant GitHub recorded the approval, the closed webhook may run before this
    # save committed and find no approved run, so it stamps nothing; stamping here (which refreshes
    # merged_at) then catches the merge. Ordering the two the other way — stamp before save — was the bug:
    # the webhook saw no approved run AND the refresh predated the webhook's merged_at, so both missed and
    # a merged+approved PR silently skipped the digest. Idempotent: it no-ops unless merged, digest-enabled,
    # and unstamped, so the closed-webhook path and this path can't double-stamp.
    if run.verdict == ReviewVerdict.APPROVED:
        _stamp_digest_audience_if_merged(repo_config, pull_request, run, current_pr)
    else:
        # This run reached a terminal outcome without a standing approval of its own (gated / refused /
        # escalate / wait). Re-run the GitHub-side sweep now to catch an orphan an older, superseded run
        # posted after this run's startup sweep — see _sweep_orphan_approvals_at_terminal.
        _sweep_orphan_approvals_at_terminal(client, run, input.team_id)

    # The run stopped actively reviewing the moment the terminal save above committed — remove the
    # "review in flight" 👀 now, whichever verdict landed (approved, gated, refused, escalate).
    _remove_own_eyes_reaction(client, run)

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
        # A retry that died between the FAILED save and the notice finds its own run terminal. Keep
        # the status, but post the notice the author is still owed. Only FAILED resumes: every other
        # terminal state belongs to a run that gave a verdict.
        if run.status == ReviewRunStatus.FAILED:
            _post_failure_notice(StamphogGitHubClient(run.pull_request.repo_config.installation_id), run, input.team_id)
        return
    # A prior post_verdict attempt may have approved on GitHub and then exhausted retries before the
    # terminal save — the id is persisted, the verdict is not, and without a future delivery nothing
    # would ever retract the approval on a FAILED run. Dismiss BEFORE marking FAILED: if the
    # dismissal itself fails, this activity retries into a still-non-terminal run and tries again,
    # whereas the reverse order would hit the terminal guard above and orphan the approval forever.
    client = StamphogGitHubClient(run.pull_request.repo_config.installation_id)
    if run.verdict != ReviewVerdict.APPROVED and run.posted_review_id and run.approval_dismissed_at is None:
        _dismiss_orphaned_approval(client, run, input.team_id)
    # Persist only the first line, truncated: run.error is returned by the serializer to anyone with
    # stamphog:read, and raw exception text can embed repository file content (a yaml.YAMLError over
    # .stamphog/policy.yml echoes the offending source lines on its continuation lines). Full detail is
    # already in the worker logs — the workflow logs the complete error before calling this activity.
    # Conditional like every terminal save (the load-time guard above can race an in-flight
    # supersession): a run that just went SUPERSEDED keeps that status, FAILED must not clobber it.
    now = timezone.now()
    marked_failed = (
        ReviewRun.objects.for_team(input.team_id)
        .filter(id=run.id)
        .exclude(status__in=TERMINAL_STATUSES)
        .update(status=ReviewRunStatus.FAILED, error=first_error_line, completed_at=now, updated_at=now)
    )
    # This run is done reviewing (unrecoverably) — clean up its own "review in flight" 👀 too. After
    # the terminal save on purpose: the removal's live-peer check must see this run as terminal, or
    # two concurrently failing runs could each defer to the other and leak the reaction.
    _remove_own_eyes_reaction(client, run)

    # A newer run that FAILS leaves the same supersession-orphan exposure a non-approve post_verdict does:
    # an older, superseded run's approval could have landed after this run's startup sweep, and a FAILED run
    # never lists our approvals again. Sweep after the FAILED save so a GitHub hiccup can't block the
    # terminal transition (the STARTUP sweep is fail-closed; this terminal one is fail-open on purpose).
    _sweep_orphan_approvals_at_terminal(client, run, input.team_id)

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
                "stamphog_review_trigger": trigger_for_run(
                    output=run.output, review_mode=pull_request.repo_config.review_mode
                ),
            },
        )

    # Last, because this step raises. A retry returns through the terminal guard, which posts the
    # notice and nothing else, so the event above must reach PostHog on this attempt.
    if marked_failed:
        _post_failure_notice(client, run, input.team_id)


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


@frozen
class _GitCredential:
    """The installation token in the two shapes a sandbox git command needs.

    Both are strings, so they are named rather than returned as a pair — handing the secret to the
    shell, or the command prefix to the scrubber, would be silent either way.
    """

    # The ``git`` prefix to run GitHub-facing commands with.
    command: str
    # The raw credential, for scrub_credentials to strip from anything the command echoes back.
    secret: str = field(repr=False)


def _git_credential(token: str) -> _GitCredential:
    """Build the git invocation that carries the installation token.

    The token rides in a per-invocation ``http.extraheader`` rather than in the remote URL, so git
    never writes it to ``.git/config`` inside the checkout the reviewer reads. Every command that
    talks to GitHub from the sandbox builds its git invocation here, so that property holds for all
    of them rather than for whichever one was written first.
    """
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return _GitCredential(
        command=f"git -c http.extraheader={shlex.quote(f'AUTHORIZATION: basic {basic}')}",
        secret=basic,
    )


def _clone_pr(
    sandbox: SandboxBase,
    repo: str,
    merge_base_sha: str,
    head_sha: str,
    pr_number: int,
    token: str,
    deadline: float,
) -> None:
    """Fetch the PR head with its files and the merge base without them, then check out the head.

    The review needs the head tree, which the reviewer explores, and the merge base, which the
    engine diffs against. It needs no history: the server reads familiarity and the commit
    trailers from GitHub. So both commits arrive at depth 1. The head comes in one full pack,
    which is faster than a blobless fetch whose checkout then asks for every file. The merge base
    brings only its trees, and _prefetch_review_blobs then fetches the few old-side files that
    the diff reads.

    The ``--filter`` on the merge-base fetch turns the checkout into a partial clone, which makes
    origin a promisor remote: git then fetches a missing object on demand. The engine runs git
    without the credential, so on a private repository that on-demand fetch fails. Every object
    the engine reads must therefore arrive here or in the prefetch. The checkout runs with
    ``GIT_NO_LAZY_FETCH``, so a missing object fails it rather than a silent fetch of a commit this
    run did not ask for.

    The head is fetched through ``pull/<n>/head`` rather than the bare sha: a fork PR's
    head commit only exists in the base repo through that ref, so a bare-sha fetch fails
    for member-authored fork PRs (the only fork PRs that pass the webhook's author gate).
    If the head moved since this run was queued, the fetched commit is not ``head_sha`` and
    the clone fails, so the superseding run takes over. A stale sha must not be reviewed
    against a newer pull ref.

    The remote stays a clean, tokenless URL. See _git_credential for how the token reaches git.
    """
    credential = _git_credential(token)
    auth = credential.command
    repo_url = f"https://github.com/{repo}.git"
    repo_dir = shlex.quote(STAMPHOG_SANDBOX_REPO_DIR)

    def _execute_or_raise(command: str, failure_prefix: str) -> None:
        # sandbox.execute failures raised by the Docker/Modal layer can embed the full command string —
        # including the AUTHORIZATION: basic <token> header — in the exception text, which then flows into
        # Temporal failure details and run.error. Scrub any raised exception (from None so the unscrubbed
        # original context isn't chained), and keep scrubbing stderr on a non-zero exit.
        try:
            result = sandbox.execute(command, timeout_seconds=_step_timeout(deadline, CLONE_STEP_TIMEOUT_SECONDS))
        except Exception as exc:
            raise RuntimeError(scrub_credentials(str(exc), token, credential.secret)) from None
        if result.exit_code != 0:
            raise RuntimeError(f"{failure_prefix}: {scrub_credentials(result.stderr, token, credential.secret)[:500]}")

    fetch_head = (
        f"rm -rf {repo_dir} && git init --quiet {repo_dir} && cd {repo_dir} && "
        f"git remote add origin {shlex.quote(repo_url)} && "
        f"{auth} fetch --quiet --depth=1 --no-tags origin {shlex.quote(f'pull/{pr_number}/head')} && "
        f'fetched=$(git rev-parse FETCH_HEAD) && if [ "$fetched" != {shlex.quote(head_sha)} ]; then '
        f'echo "the PR head is now $fetched" >&2; exit 1; fi'
    )
    _execute_or_raise(fetch_head, f"Failed to fetch the PR head {head_sha}")

    checkout = (
        f"cd {repo_dir} && "
        f"{auth} fetch --quiet --depth=1 --no-tags --filter=blob:none origin {shlex.quote(merge_base_sha)} && "
        f"GIT_NO_LAZY_FETCH=1 git checkout --quiet --detach {shlex.quote(head_sha)}"
    )
    _execute_or_raise(checkout, f"Failed to check out {head_sha}")


def _prefetch_review_blobs(sandbox: SandboxBase, merge_base_sha: str, token: str, deadline: float) -> None:
    """Fetch the old-side blobs of the PR diff, in one request.

    The merge base arrives without file contents, and the engine diffs it against the head before
    it does anything else. Enumerating the missing blobs costs nothing, because the trees are
    already local, and one batched fetch then serves the whole set.

    ``diff --raw`` names the diff set: with rename detection off it compares tree entries, so it
    reads no content and needs no blobs, and it reports the old-side object id of every changed
    file. Asking git rather than the changed-file list from the API keeps this exhaustive — the API
    pages out on a very large PR, and the diff runs before the size gate that would refuse one.
    Gitlinks are dropped because a submodule's commit belongs to another repository and origin
    rejects the whole batch for it; added files are dropped because they have no old side.

    Each of those ids is tested with ``cat-file -e``, whose contract is only its exit status, so the
    result does not depend on how a given git version reports a missing promisor object — some print
    it, some fail the command.

    Best effort. A failure is logged and swallowed, and the engine then reads the missing blobs with
    an on-demand fetch that carries no credential. That works on a public repository and fails the
    engine's diff on a private one, which escalates the review. The shared deadline bounds the time
    either way.

    ``GIT_NO_LAZY_FETCH`` guards the enumeration: without it, the reads would fetch the very
    objects they are supposed to be reporting as missing. ``fetch.negotiationAlgorithm=noop``
    skips the have/want negotiation, which is wasted work when the request names the objects it
    wants outright.
    """
    credential = _git_credential(token)
    oid_file = "/tmp/stamphog-review-oids"
    auth = credential.command
    # diff --raw names the old-side blobs, and cat-file reports which of them are absent. Two
    # changed files can share an old side, hence sort -u.
    diff_oids = (
        "for oid in $("
        f"GIT_NO_LAZY_FETCH=1 git diff --raw --no-renames --abbrev=40 {shlex.quote(merge_base_sha)} HEAD "
        "| grep -v '^:160000' | cut -d' ' -f3 | grep -v '^0*$'"
        '); do GIT_NO_LAZY_FETCH=1 git cat-file -e "$oid" 2>/dev/null || echo "$oid"; done'
    )
    command = (
        f"cd {shlex.quote(STAMPHOG_SANDBOX_REPO_DIR)} && "
        f"{{ {diff_oids}; }} | sort -u > {shlex.quote(oid_file)} && "
        f"if [ -s {shlex.quote(oid_file)} ]; then "
        f"{auth} -c fetch.negotiationAlgorithm=noop fetch origin --no-tags --no-write-fetch-head "
        f"--filter=blob:none --stdin < {shlex.quote(oid_file)}; fi"
    )
    timeout_seconds = _step_timeout(deadline, PREFETCH_DIFF_BLOBS_TIMEOUT_SECONDS)
    try:
        result = sandbox.execute(command, timeout_seconds=timeout_seconds)
    except Exception:
        activity.logger.warning("stamphog: review blob prefetch failed; git will fetch as it reads")
        return
    if result.exit_code != 0:
        # Scrubbed: the command carries the installation token in an http.extraheader, and a git
        # failure can echo the argv back.
        activity.logger.warning(
            f"stamphog: review blob prefetch exited {result.exit_code}; "
            f"git will fetch as it reads: {scrub_credentials(result.stderr, token, credential.secret)[:300]}"
        )


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
        # PyYAML puts the bad tag on the first line, and run.error keeps that line. Anyone with
        # stamphog:read can read it without access to the repository, so log the parser text instead.
        activity.logger.error(f"Malformed YAML in .stamphog/policy.yml for {repo}: {exc}")
        raise RuntimeError(f"repo {repo} has malformed YAML in .stamphog/policy.yml") from exc
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
    files = engine_source_files()
    if "review_local.py" not in files:
        raise RuntimeError(f"engine source dir {ENGINE_DIR} is missing review_local.py")
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
    """Ship the owners-yaml resolver package the engine's ownership format imports.

    The default policy declares a ``hogli-resolver`` ownership source, and gates.py imports
    ``owners_yaml`` from ``tools/owners`` next to the engine dir in the sandbox. Same trust
    posture as the engine: always our copy, which overwrites whatever the PR head carried at that
    path. Repos without
    owners.yaml/product.yaml files simply resolve to "no ownership-source match".
    """
    target = f"{STAMPHOG_SANDBOX_OWNERS_DIR}/owners_yaml"
    quoted = shlex.quote(STAMPHOG_SANDBOX_OWNERS_DIR)
    sandbox.execute(f"rm -rf {quoted} && mkdir -p {shlex.quote(target)}", timeout_seconds=30)
    for name, content in owners_package_files().items():
        sandbox.write_file(f"{target}/{name}", content.encode())


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
    """Stamp the digest audiences if the PR already merged before this approval landed.

    The merge handler only fans out a merged PR's audiences when a stamphog-approved run already
    exists. In the merge-before-approval race it records the merge with no audiences and never
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
    pull_request.refresh_from_db(fields=["merged_at"])
    if pull_request.merged_at is None or not repo_config.digest_enabled:
        return
    if PullRequestAudience.objects.for_team(run.team_id).filter(pull_request=pull_request).exists():
        return
    pull_request.summary_line = run.change_summary
    pull_request.save(update_fields=["summary_line", "updated_at"])
    PullRequestAudience.objects.for_team(run.team_id).bulk_create(
        [
            PullRequestAudience(
                team_id=run.team_id,
                pull_request=pull_request,
                audience_key=audience.key,
                reason=audience.reason,
                owned_files=audience.owned_files,
                owned_file_count=audience.owned_file_count,
            )
            for audience in resolve_audiences(repo_config, run.gate_result)
        ],
        ignore_conflicts=True,
    )


# The review this run posted when it did not approve. Kept out of ``posted_review_id``, which means
# "the APPROVE review this run posted" and drives the retraction sweep — a COMMENT review is not
# dismissable, so listing one there would break it. Nothing queries this, so it stays in ``output``.
NON_APPROVAL_REVIEW_ID_KEY = "non_approval_review_id"


def _post_non_approval_review(
    client: StamphogGitHubClient, repo: str, run: ReviewRun, pull_request: PullRequest, team_id: int, body: str
) -> None:
    """Record a non-approval as its own COMMENT review, and remember it so a retry does not repeat it.

    Same surface as the approval, so the two cannot end up in separate lists disagreeing about the
    same head. Idempotency mirrors the approve path: the id is persisted the moment GitHub accepts
    the review, outside the caller's conditional terminal save, so a crash after this point cannot
    post twice.
    """
    if (run.output or {}).get(NON_APPROVAL_REVIEW_ID_KEY) is not None:
        return
    review = client.post_comment_review(repo, pull_request.pr_number, scrub_credentials(body), run.head_sha)
    run.output = {**(run.output or {}), NON_APPROVAL_REVIEW_ID_KEY: _comment_id(review)}
    ReviewRun.objects.for_team(team_id).filter(id=run.id).update(output=run.output, updated_at=timezone.now())


FAILURE_NOTICE_BODY = (
    "**The review did not complete.**\n\n"
    "Stamphog hit an error and produced no verdict for this commit.\n\n"
    "Push a new commit to try again."
)


def _post_failure_notice(client: StamphogGitHubClient, run: ReviewRun, team_id: int) -> None:
    """Tell the PR that this run gave no verdict, once.

    The notice names a push, because that route works in every mode. A failure keeps the trigger
    label, so a push carries it and starts a run, while a re-added label waits out the per-PR
    cooldown. A self-driving run ignores labels and re-reviews only on synchronize, reopen and base
    retarget.

    The notice gives no error text, because this is a public pull request.

    A newer run at the same head stops the notice. Supersession skips terminal states, so a
    `reopened` delivery can queue a replacement at the unchanged head, and that replacement can
    approve the commit this notice would call unreviewed. A newer run at a different head is not a
    replacement. The read uses the writer, because it gates a GitHub write.

    A GitHub error propagates. If this function hides it, the activity completes, Temporal does not
    retry, and the PR keeps no notice. Raising is safe: the FAILED update is committed, and the retry
    finishes the post through the terminal guard.
    """
    replaced_at_same_head = (
        ReviewRun.objects.for_team(team_id)
        .using(router.db_for_write(ReviewRun))
        .filter(pull_request_id=run.pull_request_id, head_sha=run.head_sha, created_at__gt=run.created_at)
        .exists()
    )
    if replaced_at_same_head:
        activity.logger.info(f"Skipping the failure notice for run {run.id}; a newer run holds the same head")
        return

    _post_non_approval_review(
        client, run.pull_request.repo_config.repository, run, run.pull_request, team_id, FAILURE_NOTICE_BODY
    )


def _comment_id(obj: dict) -> int | None:
    """Pull the numeric id out of a GitHub review/comment response, or None."""
    value = obj.get("id") if isinstance(obj, dict) else None
    return value if isinstance(value, int) else None


# What each verdict means for the author, in the words they need to act on. The engine renders its
# reasoning and a gate table, but never states the outcome, and every gate row reads "✓" even on a
# refusal — so without this line a reader cannot tell an approval from a denial.
_VERDICT_HEADLINES: dict[str, str] = {
    ReviewVerdict.APPROVED: "**Approved.**",
    ReviewVerdict.REFUSED: "**Not approved — this change needs a human reviewer.**",
    ReviewVerdict.ESCALATE: "**Not approved — escalated to a human reviewer.**",
    ReviewVerdict.WAIT: "**Not approved yet — waiting on the conditions below.**",
}


def _verdict_body(parsed: ReviewerVerdict, verdict: str, relabel_label: str | None) -> str:
    """The review body: the outcome in words, what to do next, then whatever the engine rendered.

    ``relabel_label`` is the caller's own label-removal decision rather than a re-derivation of it, so
    the review cannot tell an author to re-add a label the run left in place.

    The engine's ``review_body`` is the rich version (reasoning plus the gate table) and the
    ``reasoning``/``showstoppers`` pair is the fallback when it rendered nothing. The headline is
    prepended to both, so the outcome is stated whichever one is available.
    """
    headline = _VERDICT_HEADLINES.get(verdict, f"**Stamphog review: {verdict}**")
    if relabel_label:
        headline += f"\n\nRe-add the `{relabel_label}` label to request another review once you have addressed this."
    detail = parsed.review_body or _reasoning_detail(parsed)
    return f"{headline}\n\n{neutralize_active_markdown(detail)}".rstrip()


def _reasoning_detail(parsed: ReviewerVerdict) -> str:
    body = parsed.reasoning
    if parsed.showstoppers:
        body += "\n\n**Showstoppers:**\n" + "\n".join(f"- {item}" for item in parsed.showstoppers)
    return body.strip()
