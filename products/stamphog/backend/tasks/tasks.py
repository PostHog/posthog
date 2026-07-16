"""Celery tasks for stamphog — the inbound PR review path.

``process_pull_request_event`` is the durable hand-off from the GitHub webhook:
it dedupes redeliveries, resolves the repo config, upserts the PR-grain
``PullRequest`` row, supersedes any stale in-flight run for the same PR, creates
a fresh ReviewRun, and kicks off the Temporal review workflow once the row commits.
"""

from typing import Any, cast

from django.core.cache import cache
from django.db import IntegrityError, router, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

import structlog
from celery import shared_task

from posthog.egress.github.transport import GitHubRateLimitError

from products.stamphog.backend.facade.enums import TERMINAL_STATUSES, ReviewMode, ReviewRunStatus, ReviewVerdict
from products.stamphog.backend.logic.approvals import dismiss_stale_approvals_for_head
from products.stamphog.backend.logic.audiences import resolve_audience_key
from products.stamphog.backend.logic.github_client import StamphogGitHubClient
from products.stamphog.backend.models import PullRequest, ReviewRun, StamphogRepoConfig
from products.stamphog.backend.temporal.client import execute_stamphog_review_workflow

logger = structlog.get_logger(__name__)

# Redelivery dedup: GitHub retries the same X-GitHub-Delivery on 5xx/timeouts for a
# while, so we swallow repeats within this window (workflow start is idempotent too).
STAMPHOG_PR_EVENT_IDEMPOTENCY_TTL_SECONDS = 6 * 60
STAMPHOG_PR_EVENT_IDEMPOTENCY_KEY_PREFIX = "stamphog:github:pr_event:"

# PR actions worth a (re)review. Anything else (closed, assigned, edited, ...) is dropped.
# `labeled` passes this filter but only ever queues a run for repos in LABEL review mode, when the
# added label is the repo's own trigger label, and under a per-PR cooldown (_review_mode_skip_reason).
# In ALL mode it stays ignored: every label add fires a new delivery id, so toggling any label would
# re-run the sandbox + LLM review without a code change.
RELEVANT_PR_ACTIONS = frozenset({"opened", "synchronize", "ready_for_review", "reopened", "labeled"})

# Actions that (may) move the PR head. When one of these is skipped by the LABEL-mode gate, a prior
# stamphog approval at the old head must still be retracted — the review workflow that normally does it
# is skipped. `reopened` doesn't move the head itself but is included defensively.
_HEAD_CHANGING_ACTIONS = frozenset({"synchronize", "reopened"})

# Approval dismissal message for the LABEL-mode skip path. Unlike the workflow's dismissal, no re-review
# follows here (the trigger label is absent), so the copy tells the author how to re-request one.
_LABEL_SKIP_DISMISS_MESSAGE = (
    "New commits were pushed — dismissing the stamphog approval from an earlier head. "
    "Re-add the trigger label to request a fresh review."
)

_AUTHOR_SKIP_DISMISS_MESSAGE = (
    "New commits were pushed — dismissing the stamphog approval from an earlier head. "
    "The PR author no longer has write access to this repository, so stamphog will not re-review."
)

_UNTRUSTED_SKIP_DISMISS_MESSAGE = (
    "New commits were pushed — dismissing the stamphog approval from an earlier head. "
    "This PR no longer qualifies for automatic review."
)

# Per-PR cooldown for label-triggered re-reviews, so removing/re-adding the trigger label can't spam
# sandbox + LLM runs. Set only when a `labeled` event actually queues a run in LABEL mode.
STAMPHOG_LABEL_REREVIEW_COOLDOWN_SECONDS = 10 * 60
STAMPHOG_LABEL_REREVIEW_KEY_PREFIX = "stamphog:label_rereview:"

# PR body is trimmed to this at capture time so rows (and the digest LLM prompt) stay bounded.
PR_BODY_EXCERPT_MAX_CHARS = 2000

# Only these author associations may be auto-reviewed. A fork/external-contributor PR must never be:
# an auto-approval could satisfy required reviews with zero human in the loop, and anyone could open
# PRs to burn sandbox + LLM credits. (GitHub's association vocabulary; the trusted subset.)
TRUSTED_AUTHOR_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})

# The association gate above is necessary but not sufficient: MEMBER says nothing about repo-level
# access, and COLLABORATOR covers read/triage-only invites. Auto-approval must also require that the
# author can push — otherwise an under-privileged user gets an approval that satisfies branch
# protection. GitHub's legacy permission field folds maintain into write and triage into read.
#
# Asymmetric cache TTLs: a cached ALLOW is a revocation window (a just-removed collaborator could
# still mint an approval until it expires), so it stays short — just enough to absorb a synchronize
# burst. A cached DENY only delays a just-granted collaborator's first review, which is benign.
WRITE_PERMISSIONS = frozenset({"admin", "write"})
_AUTHOR_PERMISSION_ALLOW_CACHE_SECONDS = 60
_AUTHOR_PERMISSION_DENY_CACHE_SECONDS = 10 * 60


def _review_skip_reason(pr: dict[str, Any]) -> str | None:
    """Why this PR must not enter the sandbox review path, or None to proceed.

    Cheap, payload-only pre-filters that would otherwise burn a full sandbox + LLM run just to be
    gate-refused inside it. The engine keeps the same bot/draft refusals as defense in depth; this is
    only the early-out. Fork/external PRs are dropped here for security, not just cost (see the
    TRUSTED_AUTHOR_ASSOCIATIONS note).
    """
    if pr.get("draft"):
        # Drafts re-trigger via ready_for_review once opened for review, so reviewing one now is wasted.
        return "draft"
    user = pr.get("user") or {}
    if user.get("type") == "Bot" or "[bot]" in (user.get("login") or ""):
        # Bot authors (dependabot, renovate, ...) always need a human.
        return "bot_author"
    if pr.get("author_association") not in TRUSTED_AUTHOR_ASSOCIATIONS:
        return "untrusted_author_association"
    return None


def _author_lacks_write_permission(repo_config: StamphogRepoConfig, repo: str, pr: dict[str, Any]) -> bool:
    """Whether the PR author's effective repo permission is below write.

    Unlike the payload-only pre-filters this costs a GitHub API call, so it runs last of the gates
    and the result is cached briefly per (repo config, login) to absorb synchronize bursts. Lookup
    errors propagate — the caller retries the delivery rather than failing open or dropping it.
    """
    login = (pr.get("user") or {}).get("login") or ""
    if not login:
        return True
    cache_key = f"stamphog:author_permission:{repo_config.id}:{login}"
    permission = cache.get(cache_key)
    if permission is None:
        permission = StamphogGitHubClient(repo_config.installation_id).get_collaborator_permission(repo, login)
        ttl = (
            _AUTHOR_PERMISSION_ALLOW_CACHE_SECONDS
            if permission in WRITE_PERMISSIONS
            else _AUTHOR_PERMISSION_DENY_CACHE_SECONDS
        )
        cache.set(cache_key, permission, ttl)
    return permission not in WRITE_PERMISSIONS


def _label_cooldown_key(repo_config: StamphogRepoConfig, pr_number: int) -> str:
    return f"{STAMPHOG_LABEL_REREVIEW_KEY_PREFIX}{repo_config.id}:{pr_number}"


def _review_mode_skip_reason(
    repo_config: StamphogRepoConfig, action: str, payload: dict[str, Any], pr: dict[str, Any]
) -> str | None:
    """Why the repo's review mode drops this event, or None to proceed.

    ALL mode reviews every relevant action but ignores `labeled` (any label add would re-run the
    review with no code change). LABEL mode requires the trigger label to be present on the PR for
    every action, and for `labeled` specifically also requires that the trigger label is what was just
    added — plus a per-PR cooldown so label toggling can't spam runs.
    """
    if repo_config.review_mode != ReviewMode.LABEL:
        return "labeled_ignored_in_all_mode" if action == "labeled" else None

    label_names = {(label or {}).get("name") for label in pr.get("labels") or []}
    if repo_config.trigger_label not in label_names:
        return "label_absent"
    if action == "labeled":
        added_label = (payload.get("label") or {}).get("name") or ""
        if added_label != repo_config.trigger_label:
            return "other_label_added"
        if cache.get(_label_cooldown_key(repo_config, pr["number"])) is not None:
            return "label_cooldown"
    return None


def _resolve_repo_config(installation_id: str, repo: str) -> StamphogRepoConfig | None:
    """Resolve the (installation, repo) to its owning config, oldest-wins.

    unscoped(): the team is unknown until this installation->config resolution completes — the one
    genuinely cross-team read on the webhook path; everything after it is for_team-scoped. Oldest
    config wins so a later duplicate registration can't non-deterministically hijack whose team runs.
    Pinned to the writer: a config synced or toggled moments before the webhook may not have
    replicated to the product-DB reader yet, and a miss here silently drops the delivery.
    """
    return (
        StamphogRepoConfig.objects.unscoped()
        .using(router.db_for_write(StamphogRepoConfig))
        .filter(provider="github", installation_id=installation_id, repository=repo)
        .order_by("created_at", "id")
        .first()
    )


def _is_duplicate_pr_event(delivery_id: str) -> bool:
    return cache.get(f"{STAMPHOG_PR_EVENT_IDEMPOTENCY_KEY_PREFIX}{delivery_id}") is not None


def _mark_pr_event_processed(delivery_id: str) -> None:
    cache.set(
        f"{STAMPHOG_PR_EVENT_IDEMPOTENCY_KEY_PREFIX}{delivery_id}",
        True,
        timeout=STAMPHOG_PR_EVENT_IDEMPOTENCY_TTL_SECONDS,
    )


def _upsert_pull_request(repo_config: StamphogRepoConfig, pr_payload: dict[str, Any]) -> PullRequest:
    """Upsert the PR-grain row, refreshing the descriptive fields from a not-older payload.

    Webhook deliveries can arrive out of order, so the refresh is gated on the payload's
    ``updated_at`` clock — an older snapshot must not regress the stored title/branch/body (they
    feed API reads and digest summaries). The gate lives in the UPDATE's WHERE clause so a
    concurrent delivery carrying a newer snapshot wins the write race too.
    """
    team_id = repo_config.team_id
    head = pr_payload.get("head") or {}
    incoming_updated_at = parse_datetime(pr_payload.get("updated_at") or "")
    descriptive = {
        "title": (pr_payload.get("title") or "")[:512],
        "author_login": ((pr_payload.get("user") or {}).get("login") or "")[:255],
        "pr_url": pr_payload.get("html_url", ""),
        "head_branch": head.get("ref", ""),
        "body_excerpt": (pr_payload.get("body") or "")[:PR_BODY_EXCERPT_MAX_CHARS],
    }
    # for_team scopes the lookup, but get_or_create still needs team_id in defaults
    # explicitly — queryset filters don't propagate into row creation.
    pr_obj, created = PullRequest.objects.for_team(team_id).get_or_create(
        repo_config=repo_config,
        pr_number=pr_payload["number"],
        defaults={"team_id": team_id, "payload_updated_at": incoming_updated_at, **descriptive},
    )
    if created:
        return pr_obj
    if incoming_updated_at is None:
        # An unordered payload can't be placed on the clock — keep the stored snapshot.
        return pr_obj
    refreshed = (
        PullRequest.objects.for_team(team_id)
        .filter(id=pr_obj.id)
        .filter(Q(payload_updated_at__isnull=True) | Q(payload_updated_at__lte=incoming_updated_at))
        .update(payload_updated_at=incoming_updated_at, updated_at=timezone.now(), **descriptive)
    )
    if refreshed:
        for field, value in descriptive.items():
            setattr(pr_obj, field, value)
        pr_obj.payload_updated_at = incoming_updated_at
    else:
        # Lost to a newer committed snapshot. Reload the clock so the caller's locked recheck
        # (which compares pr_obj.payload_updated_at) sees the winning value, not the stale read.
        pr_obj.refresh_from_db(fields=["payload_updated_at"])
    return pr_obj


def _start_review_workflow(review_run_id: str, team_id: int) -> None:
    """Start the review workflow, treating an already-live workflow as a no-op.

    The workflow id is derived from ``review_run_id`` (see temporal/client.py) under
    ``ALLOW_DUPLICATE_FAILED_ONLY``, so re-issuing a start for a run whose workflow is
    already running raises ``WorkflowAlreadyStartedError`` — safe to swallow. Any other
    failure (Temporal unreachable) propagates so the caller can retry the Celery task.
    """
    # Deferred so temporalio stays off the Celery/web import path (mirrors temporal/client.py).
    from temporalio.exceptions import WorkflowAlreadyStartedError  # noqa: PLC0415 — keep temporalio off the import path

    try:
        execute_stamphog_review_workflow(review_run_id=review_run_id, team_id=team_id)
    except WorkflowAlreadyStartedError:
        logger.info("stamphog_review_workflow_already_running", review_run_id=review_run_id)


def _resume_existing_delivery_run(delivery_id: str, team_id: int, repo: str) -> bool:
    """If a run already exists for this delivery, resume it and return True; else return False.

    A still-QUEUED run committed its row but never started its workflow (the post-commit start
    failed, e.g. Temporal briefly down), so restart it rather than dropping the PR. Any other status
    already has a live or finished workflow, so it's a no-op. Raises if the restart itself fails, so
    the caller can retry the Celery task.
    """
    # Writer pin: this is a read-after-write recovery path — the first delivery attempt committed
    # the QUEUED row moments ago, and a lagged reader missing it would send the retry down the
    # create path into the unique delivery_id, stranding the queued run with no workflow.
    existing = (
        ReviewRun.objects.for_team(team_id)
        .using(router.db_for_write(ReviewRun))
        .filter(delivery_id=delivery_id)
        .first()
    )
    if existing is None:
        return False
    if existing.status == ReviewRunStatus.QUEUED:
        logger.info(
            "stamphog_pr_event_restarting_queued_run",
            delivery_id=delivery_id,
            review_run_id=str(existing.id),
            repo=repo,
        )
        _start_review_workflow(str(existing.id), team_id)
    else:
        logger.info("stamphog_pr_event_delivery_already_processed", delivery_id=delivery_id, repo=repo)
    return True


def _supersede_prior_runs(pr_obj: PullRequest) -> None:
    """Mark every non-terminal run for this PR as superseded, under a row lock.

    A new push (synchronize) or reopen makes any queued/in-flight run stale — its
    head SHA no longer matches. Locking the rows first keeps two concurrent
    deliveries for the same PR from both leaving a live run behind.
    """
    stale_ids = list(
        ReviewRun.objects.for_team(pr_obj.team_id)
        .select_for_update()
        .filter(pull_request=pr_obj)
        .exclude(status__in=TERMINAL_STATUSES)
        .values_list("id", flat=True)
    )
    if stale_ids:
        ReviewRun.objects.for_team(pr_obj.team_id).filter(id__in=stale_ids).update(
            status=ReviewRunStatus.SUPERSEDED, updated_at=timezone.now()
        )


def _retract_stale_approvals_on_skip(repo_config: StamphogRepoConfig, pr: dict[str, Any], message: str) -> None:
    """Retract a standing stamphog approval when a head-changing event is skipped before the workflow.

    A skipped `synchronize`/`reopened` (missing trigger label, author lost write access) never reaches
    the workflow's dismiss_stale_approvals step, so a prior approval would keep satisfying required
    reviews over the newly pushed, unreviewed commits. Retract it here with the payload's head sha. No
    PR row yet means no prior run, so nothing to do. Raises on failure so the caller can retry — a
    dropped dismissal would leave the stale approval standing. No explicit transaction: the helper's
    per-run saves route to the model's DB on their own, and wrapping the GitHub dismissal in an atomic
    block is what we avoid.
    """
    team_id = repo_config.team_id
    pr_number = pr.get("number")
    if pr_number is None:
        return
    head_sha = (pr.get("head") or {}).get("sha") or ""
    pull_request = PullRequest.objects.for_team(team_id).filter(repo_config=repo_config, pr_number=pr_number).first()
    if pull_request is None:
        return
    dismissed = dismiss_stale_approvals_for_head(team_id, pull_request, repo_config, head_sha, message=message)
    if dismissed:
        logger.info(
            "stamphog_pr_event_skip_dismissed_stale_approvals",
            repo=repo_config.repository,
            pr_number=pr_number,
            dismissed=dismissed,
        )


def _record_merged_pull_request(payload: dict[str, Any], delivery_id: str) -> None:
    """Record merge facts on the PullRequest; stamp the digest audience only if eligible.

    Merge state is truth regardless of approval, so the facts are always recorded once
    the repo config resolves and is enabled. The digest gate (digest_enabled + a
    stamphog-approved run) only decides whether audience_key gets stamped — the digest
    filters on audience_key, so an unstamped merge never reaches Slack. A redelivery
    is a no-op: merged_at already being set means this merge was recorded.
    """
    installation_id = str((payload.get("installation") or {}).get("id", ""))
    repo = (payload.get("repository") or {}).get("full_name", "")
    pr = payload.get("pull_request") or {}
    pr_number = pr.get("number")
    if not installation_id or not repo or not pr_number:
        logger.warning("stamphog_merged_pr_missing_fields", has_installation=bool(installation_id), repo=repo)
        return

    repo_config = _resolve_repo_config(installation_id, repo)
    if not repo_config:
        logger.info("stamphog_merged_pr_repo_not_configured", repo=repo, installation_id=installation_id)
        return
    # A digest-only repo (digest_enabled=True, review enabled=False) still needs its merges captured,
    # otherwise the daily digest has nothing to send. Gate the merge path on either flag; the digest
    # eligibility below still requires digest_enabled specifically.
    if not (repo_config.enabled or repo_config.digest_enabled):
        logger.info("stamphog_merged_pr_repo_disabled", repo=repo)
        return

    team_id = repo_config.team_id
    pr_obj = _upsert_pull_request(repo_config, pr)
    if pr_obj.merged_at is not None:
        logger.info("stamphog_merged_pr_already_recorded", repo=repo, pr_number=pr_number, delivery_id=delivery_id)
        return

    pr_obj.merged_at = parse_datetime(pr.get("merged_at") or "") or timezone.now()
    pr_obj.merge_commit_sha = pr.get("merge_commit_sha") or ""
    pr_obj.additions = pr.get("additions") or 0
    pr_obj.deletions = pr.get("deletions") or 0
    pr_obj.changed_files = pr.get("changed_files") or 0
    update_fields = ["merged_at", "merge_commit_sha", "additions", "deletions", "changed_files", "updated_at"]

    # Digest eligibility: opt-in per repo, and the digest reports what stamphog
    # approved, not everything that merged. Ineligible merges keep their facts but
    # stay out of the digest (blank audience_key).
    #
    # The approval must belong to the commit that actually got merged. pull_request.head.sha
    # is that commit (merge_commit_sha is the synthetic merge commit GitHub creates, not the
    # reviewed head, so it can't be used here). Without this check, a PR approved at an earlier
    # head that's later pushed to and merged without re-review would still count as approved --
    # normally `synchronize` supersedes and re-reviews, so this only closes that narrow gap.
    pr_head_sha = ((pr.get("head") or {}).get("sha") or "").strip()
    if not pr_head_sha:
        logger.warning("stamphog_merged_pr_missing_head_sha", repo=repo, pr_number=pr_number)
        approved = False
    else:
        # Writer pin: an auto-merge fires this webhook the instant GitHub records the approval, so
        # the APPROVED run post_verdict just committed may not have replicated to the reader yet.
        approved = (
            ReviewRun.objects.for_team(team_id)
            .using(router.db_for_write(ReviewRun))
            .filter(pull_request=pr_obj, verdict=ReviewVerdict.APPROVED, head_sha=pr_head_sha)
            .exists()
        )
    # Review-disabled repos can't have approved runs by construction, so digest-only mode
    # (digest on, review off) admits every merge — gating those on approval would silently
    # keep digest-only repos out of Slack forever.
    if repo_config.digest_enabled and (approved or not repo_config.enabled):
        pr_obj.audience_key = resolve_audience_key(repo_config, pr)
        update_fields.append("audience_key")
    else:
        logger.info(
            "stamphog_merged_pr_not_digest_eligible",
            repo=repo,
            pr_number=pr_number,
            digest_enabled=repo_config.digest_enabled,
            approved=approved,
        )
    pr_obj.save(update_fields=update_fields)

    if delivery_id:
        _mark_pr_event_processed(delivery_id)
    logger.info("stamphog_merged_pr_recorded", repo=repo, pr_number=pr_number, team_id=team_id)


def _resolve_installation_team_ids(installation_id: str) -> list[int]:
    """Every distinct team carrying this installation.

    An installation's repos can legitimately be split across teams — each team syncs only the repos its
    members can access — so lifecycle events must fan out to all owning teams, not just the oldest
    config's. Resolving to a single (oldest) team would leave other teams' rows live after an uninstall
    and could bind a newly added repo to a team its adder never intended. unscoped(): the owning teams
    are exactly what's being resolved here — the one cross-team read on this path (mirrors
    _resolve_repo_config, writer pin included: a lagged reader returning no teams would silently and
    permanently skip the lifecycle mutation for a just-synced installation).
    """
    return list(
        StamphogRepoConfig.objects.unscoped()
        .using(router.db_for_write(StamphogRepoConfig))
        .filter(provider="github", installation_id=installation_id)
        .values_list("team_id", flat=True)
        .distinct()
    )


def _add_installation_repos(team_id: int, installation_id: str, repos: list[dict[str, Any]]) -> None:
    """Create a disabled config row per newly installed repo, skipping any that already exist.

    Rows start disabled so a repo added on GitHub merely appears in the toggle list — enabling reviews
    stays a human decision. Conflicts (another team owns the triple, or this team already has the repo)
    skip that one repo, never the batch: the same cross-team uniqueness the sync endpoint enforces.
    """
    # Bind the transaction to the model's routed DB (stamphog_db_writer when the product DB is
    # configured, else default) — a bare atomic() would open on the default connection and leave
    # the create running outside any transaction on the product DB.
    write_db = router.db_for_write(StamphogRepoConfig)
    # New rows inherit the connecting user from a sibling of the same installation — webhooks carry
    # no PostHog identity, and the sandbox token for reviews is minted under this user. No sibling
    # with one set means the installation was never synced; the row stays null and reviews fail closed.
    connected_by_user_id = (
        StamphogRepoConfig.objects.for_team(team_id)
        .filter(provider="github", installation_id=installation_id, connected_by_user_id__isnull=False)
        .values_list("connected_by_user_id", flat=True)
        .first()
    )
    for repo in repos:
        full_name = (repo or {}).get("full_name") or ""
        if not full_name:
            continue
        exists = (
            StamphogRepoConfig.objects.unscoped()
            .filter(provider="github", installation_id=installation_id, repository=full_name)
            .exists()
        )
        if exists:
            continue
        try:
            with transaction.atomic(using=write_db):
                StamphogRepoConfig.objects.for_team(team_id).create(
                    team_id=team_id,
                    provider="github",
                    repository=full_name,
                    installation_id=installation_id,
                    enabled=False,
                    digest_enabled=False,
                    connected_by_user_id=connected_by_user_id,
                )
        except IntegrityError:
            logger.info("stamphog_installation_repo_add_conflict", repository=full_name, team_id=team_id)


def _disable_installation_repos(team_id: int, installation_id: str, repos: list[dict[str, Any]]) -> None:
    """Tombstone configs for repos removed from the installation: disable, keep the rows and history."""
    names = [name for repo in repos if (name := (repo or {}).get("full_name"))]
    if not names:
        return
    # updated_at explicitly: auto_now doesn't fire on queryset update().
    disabled = (
        StamphogRepoConfig.objects.for_team(team_id)
        .filter(provider="github", installation_id=installation_id, repository__in=names)
        .update(enabled=False, digest_enabled=False, updated_at=timezone.now())
    )
    logger.info("stamphog_installation_repos_removed", installation_id=installation_id, disabled=disabled)


@shared_task(ignore_result=True, max_retries=3, default_retry_delay=5)
def process_installation_event(payload: dict[str, Any], delivery_id: str) -> None:
    """Mirror installation lifecycle changes (repos added/removed, app uninstalled) onto config rows.

    Without this, a repo added to the installation after the initial sync never appears in the toggle
    list until a manual re-sync. `installation_repositories` payloads carry repositories_added/removed;
    a plain `installation` event with action "deleted" means the app was uninstalled.

    An installation's repos can be split across several teams, so removals and uninstalls fan out to
    EVERY owning team (tombstone semantics — rows and history are kept). Auto-adding a newly installed
    repo, on the other hand, is only a convenience for the unambiguous single-team case: when one team
    owns the installation the new repo appears as a disabled row automatically. When multiple teams
    share it, ownership is ambiguous — auto-binding could attach the repo to a team its adder never
    intended — so the add is skipped and left to the authenticated sync flow, which verifies the acting
    user's repo access. Rows always start disabled either way, so enabling reviews stays a human decision.
    """
    if delivery_id and _is_duplicate_pr_event(delivery_id):
        logger.info("stamphog_installation_event_duplicate_skipped", delivery_id=delivery_id)
        return

    installation_id = str((payload.get("installation") or {}).get("id", ""))
    if not installation_id:
        logger.warning("stamphog_installation_event_missing_installation")
        return

    # Retry (don't drop) on a transient DB error: the webhook is already ACKed, and a lifecycle
    # mutation that silently fails here is permanently skipped until a manual resync.
    try:
        team_ids = _resolve_installation_team_ids(installation_id)
    except Exception as e:
        logger.exception("stamphog_installation_team_resolution_failed", delivery_id=delivery_id, error=str(e))
        raise cast(Any, process_installation_event).retry(exc=e)
    if not team_ids:
        # No config carries this installation yet — the user-driven sync flow will bind it to a team.
        logger.info("stamphog_installation_event_unbound", installation_id=installation_id)
        return

    action = payload.get("action", "")
    # Retry on failure like the review path: the webhook is already ACKed, so a transient product-DB
    # blip during the config mutations must not permanently drop the lifecycle event (a repo added on
    # GitHub would then never appear in the toggle list until a manual re-sync). Mark the delivery
    # processed only after the mutations succeed, so a retried delivery still does its work.
    try:
        if "repositories_added" in payload or "repositories_removed" in payload:
            added = payload.get("repositories_added") or []
            if added:
                if len(team_ids) == 1:
                    _add_installation_repos(team_ids[0], installation_id, added)
                else:
                    # Ambiguous ownership: skip the auto-add, defer to the authenticated sync flow.
                    logger.info(
                        "stamphog_installation_repo_add_ambiguous",
                        installation_id=installation_id,
                        team_count=len(team_ids),
                    )
            removed = payload.get("repositories_removed") or []
            for team_id in team_ids:
                _disable_installation_repos(team_id, installation_id, removed)
        elif action == "deleted":
            for team_id in team_ids:
                disabled = (
                    StamphogRepoConfig.objects.for_team(team_id)
                    .filter(provider="github", installation_id=installation_id)
                    .update(enabled=False, digest_enabled=False, updated_at=timezone.now())
                )
                logger.info(
                    "stamphog_installation_uninstalled",
                    installation_id=installation_id,
                    team_id=team_id,
                    disabled=disabled,
                )
        else:
            logger.info("stamphog_installation_event_ignored", action=action)
    except Exception as e:
        logger.exception("stamphog_installation_event_failed", delivery_id=delivery_id, error=str(e))
        raise cast(Any, process_installation_event).retry(exc=e)

    if delivery_id:
        _mark_pr_event_processed(delivery_id)


@shared_task(ignore_result=True, max_retries=3, default_retry_delay=5)
def process_pull_request_event(payload: dict[str, Any], delivery_id: str) -> None:
    """Turn one verified pull_request webhook delivery into a queued ReviewRun."""
    if delivery_id and _is_duplicate_pr_event(delivery_id):
        logger.info("stamphog_pr_event_duplicate_skipped", delivery_id=delivery_id)
        return

    action = payload.get("action", "")
    # Merged PRs feed the digest, not the review path — handle before the relevance drop below,
    # which discards "closed" entirely. An unmerged close is a no-op.
    if action == "closed":
        if (payload.get("pull_request") or {}).get("merged"):
            # Retry on failure like the review path below: the webhook is already ACKed, so a transient
            # product-DB blip during the upsert/save must not silently drop the merge from the digest.
            try:
                _record_merged_pull_request(payload, delivery_id)
            except Exception as e:
                logger.exception("stamphog_merged_pr_record_failed", delivery_id=delivery_id, error=str(e))
                raise cast(Any, process_pull_request_event).retry(exc=e)
        else:
            logger.info("stamphog_pr_event_closed_unmerged_ignored")
        return

    if action not in RELEVANT_PR_ACTIONS:
        logger.info("stamphog_pr_event_action_ignored", action=action)
        return

    installation_id = str((payload.get("installation") or {}).get("id", ""))
    repo = (payload.get("repository") or {}).get("full_name", "")
    pr = payload.get("pull_request") or {}
    pr_number = pr.get("number")
    if not installation_id or not repo or not pr_number:
        logger.warning(
            "stamphog_pr_event_missing_fields",
            has_installation=bool(installation_id),
            repo=repo,
            pr_number=pr_number,
        )
        return

    # Cheap pre-sandbox drops (drafts, bots, fork/external authors) before we resolve config or spend a
    # sandbox. Only affects the review path — the merged/closed digest capture returned above already.
    skip_reason = _review_skip_reason(pr)
    if skip_reason is not None:
        # A head-changing event skipped here still invalidates any standing approval — the author may
        # have lost their trusted association, or the PR flipped to draft, since the approval was
        # granted. Same hazard as the mode/permission skips below: without retraction the old approval
        # keeps satisfying required reviews over the newly pushed commits. Retry (don't drop) on
        # failure so a transient blip can't leave the stale approval live.
        if action in _HEAD_CHANGING_ACTIONS:
            # Retry (don't drop) the whole lookup+retraction: the webhook is ACKed, so a transient
            # DB error on either step would otherwise silently skip the dismissal.
            try:
                skip_repo_config = _resolve_repo_config(installation_id, repo)
                # No .enabled filter: a disabled repo's standing approval must not survive a push either.
                if skip_repo_config is not None:
                    _retract_stale_approvals_on_skip(skip_repo_config, pr, _UNTRUSTED_SKIP_DISMISS_MESSAGE)
            except Exception as e:
                logger.exception(
                    "stamphog_pr_event_untrusted_skip_dismiss_failed", delivery_id=delivery_id, error=str(e)
                )
                raise cast(Any, process_pull_request_event).retry(exc=e)
        logger.info("stamphog_pr_event_skipped", repo=repo, pr_number=pr_number, reason=skip_reason)
        if delivery_id:
            _mark_pr_event_processed(delivery_id)
        return

    # Creation is guarded against cross-team duplicates (see StamphogRepoConfigViewSet). Retry (don't
    # drop) on a transient DB error: this is the first DB touch on the main path, and the webhook was
    # already ACKed, so an unhandled blip here would silently lose the delivery.
    try:
        repo_config = _resolve_repo_config(installation_id, repo)
    except Exception as e:
        logger.exception("stamphog_pr_event_config_resolution_failed", delivery_id=delivery_id, error=str(e))
        raise cast(Any, process_pull_request_event).retry(exc=e)
    if not repo_config:
        logger.info("stamphog_pr_event_repo_not_configured", repo=repo, installation_id=installation_id)
        return
    if not repo_config.enabled:
        # Disabling a repo opts out of reviews, but a standing approval from before the disable must
        # still not survive new commits — same retraction as every other head-changing skip path.
        if action in _HEAD_CHANGING_ACTIONS:
            try:
                _retract_stale_approvals_on_skip(repo_config, pr, _UNTRUSTED_SKIP_DISMISS_MESSAGE)
            except Exception as e:
                logger.exception(
                    "stamphog_pr_event_disabled_skip_dismiss_failed", delivery_id=delivery_id, error=str(e)
                )
                raise cast(Any, process_pull_request_event).retry(exc=e)
        logger.info("stamphog_pr_event_repo_disabled", repo=repo)
        if delivery_id:
            _mark_pr_event_processed(delivery_id)
        return

    mode_skip_reason = _review_mode_skip_reason(repo_config, action, payload, pr)
    if mode_skip_reason is not None:
        # Safety net before dropping the event: a LABEL-mode head change skipped for a missing trigger
        # label still invalidates any standing approval. Retract it before marking the delivery processed,
        # and retry (don't drop) on failure so a transient blip can't leave the stale approval live.
        if action in _HEAD_CHANGING_ACTIONS and repo_config.review_mode == ReviewMode.LABEL:
            try:
                _retract_stale_approvals_on_skip(repo_config, pr, _LABEL_SKIP_DISMISS_MESSAGE)
            except Exception as e:
                logger.exception("stamphog_pr_event_label_skip_dismiss_failed", delivery_id=delivery_id, error=str(e))
                raise cast(Any, process_pull_request_event).retry(exc=e)
        logger.info("stamphog_pr_event_skipped", repo=repo, pr_number=pr_number, reason=mode_skip_reason)
        if delivery_id:
            _mark_pr_event_processed(delivery_id)
        return

    # author_association alone can't prove push access (see WRITE_PERMISSIONS), so the last gate before
    # spending a run verifies it against the repo. Retry (don't drop) on lookup failure: fail-open would
    # let a transient GitHub blip mint approvals for under-privileged authors, and dropping would lose
    # legitimate reviews to the same blip.
    try:
        author_below_write = _author_lacks_write_permission(repo_config, repo, pr)
    except GitHubRateLimitError as e:
        # Honor GitHub's own backoff hint: the default 5s retry delay lands inside the same rate
        # window and burns the attempt budget without ever succeeding.
        logger.warning("stamphog_pr_event_author_permission_rate_limited", delivery_id=delivery_id)
        raise cast(Any, process_pull_request_event).retry(exc=e, countdown=max(e.retry_after or 0, 60))
    except Exception as e:
        logger.exception("stamphog_pr_event_author_permission_failed", delivery_id=delivery_id, error=str(e))
        raise cast(Any, process_pull_request_event).retry(exc=e)
    if author_below_write:
        # Same stale-approval hazard as the label skip: a head change that never reaches the workflow
        # must not leave an approval from an earlier head satisfying required reviews.
        if action in _HEAD_CHANGING_ACTIONS:
            try:
                _retract_stale_approvals_on_skip(repo_config, pr, _AUTHOR_SKIP_DISMISS_MESSAGE)
            except Exception as e:
                logger.exception("stamphog_pr_event_author_skip_dismiss_failed", delivery_id=delivery_id, error=str(e))
                raise cast(Any, process_pull_request_event).retry(exc=e)
        logger.info("stamphog_pr_event_skipped", repo=repo, pr_number=pr_number, reason="author_below_write")
        if delivery_id:
            _mark_pr_event_processed(delivery_id)
        return

    team_id = repo_config.team_id

    # Recovery fast path: a run for this delivery already exists (a redelivery/Celery retry that
    # slipped past the cache dedup). If it's still QUEUED, its earlier attempt committed the row but
    # never started the workflow (Temporal was briefly down and the post-commit start failed) — so
    # restart it here instead of silently dropping the PR. Any other status has a live/finished
    # workflow, so this is a plain no-op. Doing this before the create also keeps the recovery off
    # the post-IntegrityError path, where the aborted transaction can't run further queries.
    if delivery_id:
        try:
            resumed = _resume_existing_delivery_run(delivery_id, team_id, repo)
        except Exception as e:
            logger.exception("stamphog_pr_event_restart_queued_run_failed", delivery_id=delivery_id, error=str(e))
            raise cast(Any, process_pull_request_event).retry(exc=e)
        if resumed:
            _mark_pr_event_processed(delivery_id)
            return

    # Out-of-order guard: GitHub can deliver (or fan out) an older PR snapshot after a newer one.
    # pull_request.updated_at is monotonic per PR, so a payload strictly older than the one we last
    # applied is stale — superseding the current run for it would cancel the up-to-date review and start
    # one against an outdated head, leaving the PR unreviewed until the next push. Drop it; the newer
    # delivery already queued the correct run. Equal timestamps proceed (a redelivery of the current head).
    incoming_updated_at = parse_datetime(pr.get("updated_at") or "")
    if incoming_updated_at is not None:
        stored_updated_at = (
            PullRequest.objects.for_team(team_id)
            .filter(repo_config=repo_config, pr_number=pr_number)
            .values_list("payload_updated_at", flat=True)
            .first()
        )
        if stored_updated_at is not None and incoming_updated_at < stored_updated_at:
            logger.info("stamphog_pr_event_stale_payload", repo=repo, pr_number=pr_number, action=action)
            if delivery_id:
                _mark_pr_event_processed(delivery_id)
            return

    # Bind the transaction and its on_commit hook to the model's routed DB. A bare atomic() opens on
    # the default connection, so when the product DB is configured the select_for_update in
    # _supersede_prior_runs and this create would run outside any transaction, and on_commit would fire
    # against the wrong connection.
    write_db = router.db_for_write(ReviewRun)
    try:
        with transaction.atomic(using=write_db):
            pr_obj = _upsert_pull_request(repo_config, pr)
            # Race-safe recheck of the stale-payload guard. The check above runs before this
            # transaction, so two concurrent deliveries can both pass it; the older one would then
            # still supersede the newer run. _upsert_pull_request's conditional refresh UPDATE takes
            # the PR row lock when this payload is current (held to commit, serializing deliveries)
            # and reloads the winning clock when it lost, so once it returns pr_obj carries
            # max(previous, incoming). A stored value strictly newer than this payload means a newer
            # delivery already committed its run — bail before supersede/create so we don't cancel
            # the up-to-date review for a stale head.
            if (
                incoming_updated_at is not None
                and pr_obj.payload_updated_at is not None
                and pr_obj.payload_updated_at > incoming_updated_at
            ):
                logger.info("stamphog_pr_event_stale_payload_locked", repo=repo, pr_number=pr_number, action=action)
                if delivery_id:
                    _mark_pr_event_processed(delivery_id)
                return
            _supersede_prior_runs(pr_obj)
            head = pr.get("head") or {}
            review_run = ReviewRun.objects.for_team(team_id).create(
                team_id=team_id,
                pull_request=pr_obj,
                head_sha=head.get("sha", ""),
                delivery_id=delivery_id or None,
                status=ReviewRunStatus.QUEUED,
            )
            # Only start the workflow once the row is durably committed — an aborted
            # transaction must not leave a workflow chasing a run that never existed.
            review_run_id = str(review_run.id)
            # Let a post-commit start failure propagate: it lands in the `except Exception`
            # below and retries the Celery task. The retry re-enters through the recovery fast
            # path above and restarts the still-QUEUED run — the durable recovery for a
            # committed-but-unstarted run.
            transaction.on_commit(lambda: _start_review_workflow(review_run_id, team_id), using=write_db)
    except IntegrityError:
        # The unique delivery_id already has a run — two near-simultaneous deliveries raced past the
        # fast-path check and both tried to create. Resume the winner's run: if it committed QUEUED but
        # its post-commit workflow start failed, restart it here instead of marking the delivery done
        # and stranding a run no workflow ever picks up. The aborted transaction is already rolled back,
        # so these reads run clean.
        if delivery_id:
            try:
                _resume_existing_delivery_run(delivery_id, team_id, repo)
            except Exception as e:
                logger.exception("stamphog_pr_event_restart_queued_run_failed", delivery_id=delivery_id, error=str(e))
                raise cast(Any, process_pull_request_event).retry(exc=e)
            _mark_pr_event_processed(delivery_id)
        return
    except Exception as e:
        logger.exception("stamphog_pr_event_create_run_failed", repo=repo, pr_number=pr_number, error=str(e))
        raise cast(Any, process_pull_request_event).retry(exc=e)

    # Arm the cooldown only once a label-triggered run actually queued, so a skipped or failed
    # attempt doesn't block the next legitimate label add.
    if action == "labeled" and repo_config.review_mode == ReviewMode.LABEL:
        cache.set(_label_cooldown_key(repo_config, pr_number), True, timeout=STAMPHOG_LABEL_REREVIEW_COOLDOWN_SECONDS)

    logger.info(
        "stamphog_pr_event_queued",
        repo=repo,
        pr_number=pr_number,
        action=action,
        review_run_id=review_run_id,
    )

    if delivery_id:
        _mark_pr_event_processed(delivery_id)
