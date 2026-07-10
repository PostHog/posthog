"""Celery tasks for stamphog — the inbound PR review path.

``process_pull_request_event`` is the durable hand-off from the GitHub webhook:
it dedupes redeliveries, resolves the repo config, supersedes any stale in-flight
run for the same PR, creates a fresh ReviewRun, and kicks off the Temporal review
workflow once the row commits.
"""

from typing import Any, cast

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

import structlog
from celery import shared_task

from products.stamphog.backend.facade.enums import ReviewRunStatus
from products.stamphog.backend.models import ReviewRun, StamphogRepoConfig
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


def _is_duplicate_pr_event(delivery_id: str) -> bool:
    return cache.get(f"{STAMPHOG_PR_EVENT_IDEMPOTENCY_KEY_PREFIX}{delivery_id}") is not None


def _mark_pr_event_processed(delivery_id: str) -> None:
    cache.set(
        f"{STAMPHOG_PR_EVENT_IDEMPOTENCY_KEY_PREFIX}{delivery_id}",
        True,
        timeout=STAMPHOG_PR_EVENT_IDEMPOTENCY_TTL_SECONDS,
    )


def _supersede_prior_runs(repo_config: StamphogRepoConfig, pr_number: int) -> None:
    """Mark every non-terminal run for this PR as superseded, under a row lock.

    A new push (synchronize) or reopen makes any queued/in-flight run stale — its
    head SHA no longer matches. Locking the rows first keeps two concurrent
    deliveries for the same PR from both leaving a live run behind.
    """
    stale_ids = list(
        ReviewRun.objects.for_team(repo_config.team_id)
        .select_for_update()
        .filter(repo_config=repo_config, pr_number=pr_number)
        .exclude(status__in=TERMINAL_STATUSES)
        .values_list("id", flat=True)
    )
    if stale_ids:
        ReviewRun.objects.for_team(repo_config.team_id).filter(id__in=stale_ids).update(
            status=ReviewRunStatus.SUPERSEDED, updated_at=timezone.now()
        )


@shared_task(ignore_result=True, max_retries=3, default_retry_delay=5)
def process_pull_request_event(payload: dict[str, Any], delivery_id: str) -> None:
    """Turn one verified pull_request webhook delivery into a queued ReviewRun."""
    if delivery_id and _is_duplicate_pr_event(delivery_id):
        logger.info("stamphog_pr_event_duplicate_skipped", delivery_id=delivery_id)
        return

    action = payload.get("action", "")
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

    # Resolve deterministically (oldest config wins) so a later duplicate registration for the
    # same (installation, repo) can't non-deterministically hijack whose team/policy runs the
    # review. Creation is guarded against cross-team duplicates (see StamphogRepoConfigViewSet).
    # unscoped(): the team is unknown until this installation->config resolution completes,
    # the one genuinely cross-team read on this path; everything after it is for_team-scoped.
    repo_config = (
        StamphogRepoConfig.objects.unscoped()
        .filter(provider="github", installation_id=installation_id, repository=repo)
        .order_by("created_at", "id")
        .first()
    )
    if not repo_config:
        logger.info("stamphog_pr_event_repo_not_configured", repo=repo, installation_id=installation_id)
        return
    if not repo_config.enabled:
        logger.info("stamphog_pr_event_repo_disabled", repo=repo)
        return

    team_id = repo_config.team_id
    try:
        with transaction.atomic():
            _supersede_prior_runs(repo_config, pr_number)
            head = pr.get("head") or {}
            review_run = ReviewRun.objects.for_team(team_id).create(
                team_id=team_id,
                repo_config=repo_config,
                pr_number=pr_number,
                pr_url=pr.get("html_url", ""),
                head_sha=head.get("sha", ""),
                head_branch=head.get("ref", ""),
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
