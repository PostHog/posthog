"""Celery tasks for stamphog — the inbound PR review path.

``process_pull_request_event`` is the durable hand-off from the GitHub webhook:
it dedupes redeliveries, resolves the repo config, upserts the PR-grain
``PullRequest`` row, supersedes any stale in-flight run for the same PR, creates
a fresh ReviewRun, and kicks off the Temporal review workflow once the row commits.
"""

from typing import Any, cast

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

import structlog
from celery import shared_task

from products.stamphog.backend.facade.enums import ReviewRunStatus, ReviewVerdict
from products.stamphog.backend.logic.audiences import resolve_audience_key
from products.stamphog.backend.models import PullRequest, ReviewRun, StamphogRepoConfig
from products.stamphog.backend.temporal.client import execute_stamphog_review_workflow

logger = structlog.get_logger(__name__)

# Redelivery dedup: GitHub retries the same X-GitHub-Delivery on 5xx/timeouts for a
# while, so we swallow repeats within this window (workflow start is idempotent too).
STAMPHOG_PR_EVENT_IDEMPOTENCY_TTL_SECONDS = 6 * 60
STAMPHOG_PR_EVENT_IDEMPOTENCY_KEY_PREFIX = "stamphog:github:pr_event:"

# PR actions worth a (re)review. Anything else (closed, assigned, edited, ...) is dropped.
RELEVANT_PR_ACTIONS = frozenset({"opened", "synchronize", "ready_for_review", "reopened", "labeled"})

# A run in one of these states is done and must not be superseded.
TERMINAL_STATUSES = frozenset({ReviewRunStatus.COMPLETED, ReviewRunStatus.FAILED, ReviewRunStatus.SUPERSEDED})

# PR body is trimmed to this at capture time so rows (and the digest LLM prompt) stay bounded.
PR_BODY_EXCERPT_MAX_CHARS = 2000


def _resolve_repo_config(installation_id: str, repo: str) -> StamphogRepoConfig | None:
    """Resolve the (installation, repo) to its owning config, oldest-wins.

    unscoped(): the team is unknown until this installation->config resolution completes — the one
    genuinely cross-team read on the webhook path; everything after it is for_team-scoped. Oldest
    config wins so a later duplicate registration can't non-deterministically hijack whose team runs.
    """
    return (
        StamphogRepoConfig.objects.unscoped()
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
    """Upsert the PR-grain row, refreshing the descriptive fields from the payload."""
    team_id = repo_config.team_id
    head = pr_payload.get("head") or {}
    # for_team scopes the lookup, but update_or_create still needs team_id in defaults
    # explicitly — queryset filters don't propagate into row creation.
    pr_obj, _ = PullRequest.objects.for_team(team_id).update_or_create(
        repo_config=repo_config,
        pr_number=pr_payload["number"],
        defaults={
            "team_id": team_id,
            "title": (pr_payload.get("title") or "")[:512],
            "author_login": ((pr_payload.get("user") or {}).get("login") or "")[:255],
            "pr_url": pr_payload.get("html_url", ""),
            "head_branch": head.get("ref", ""),
            "body_excerpt": (pr_payload.get("body") or "")[:PR_BODY_EXCERPT_MAX_CHARS],
        },
    )
    return pr_obj


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
    if not repo_config.enabled:
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
    approved = ReviewRun.objects.for_team(team_id).filter(pull_request=pr_obj, verdict=ReviewVerdict.APPROVED).exists()
    if repo_config.digest_enabled and approved:
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
            _record_merged_pull_request(payload, delivery_id)
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

    # Creation is guarded against cross-team duplicates (see StamphogRepoConfigViewSet).
    repo_config = _resolve_repo_config(installation_id, repo)
    if not repo_config:
        logger.info("stamphog_pr_event_repo_not_configured", repo=repo, installation_id=installation_id)
        return
    if not repo_config.enabled:
        logger.info("stamphog_pr_event_repo_disabled", repo=repo)
        return

    team_id = repo_config.team_id
    try:
        with transaction.atomic():
            pr_obj = _upsert_pull_request(repo_config, pr)
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
            transaction.on_commit(
                lambda: execute_stamphog_review_workflow(review_run_id=review_run_id, team_id=team_id)
            )
    except IntegrityError:
        # The unique delivery_id already has a run — a redelivery that slipped past the
        # cache dedup (miss/expiry). Nothing lost, nothing to retry.
        logger.info("stamphog_pr_event_delivery_already_processed", delivery_id=delivery_id, repo=repo)
        return
    except Exception as e:
        logger.exception("stamphog_pr_event_create_run_failed", repo=repo, pr_number=pr_number, error=str(e))
        raise cast(Any, process_pull_request_event).retry(exc=e)

    logger.info(
        "stamphog_pr_event_queued",
        repo=repo,
        pr_number=pr_number,
        action=action,
        review_run_id=review_run_id,
    )

    if delivery_id:
        _mark_pr_event_processed(delivery_id)
