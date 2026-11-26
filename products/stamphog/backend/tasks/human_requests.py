"""Celery tasks that keep a human request and its Slack card in step with the pull request."""

from __future__ import annotations

from django.db import router

import structlog
from celery import Task, shared_task

from posthog.egress.github.transport import GitHubRateLimitError

from products.stamphog.backend.facade.enums import ACTIVE_HUMAN_REQUEST_STATUSES, ReviewRunStatus
from products.stamphog.backend.logic import human_requests
from products.stamphog.backend.models import HumanRequest, ReviewRun

logger = structlog.get_logger(__name__)

_MAX_RETRIES = 5
_RETRY_BASE_SECONDS = 30


@shared_task(bind=True, ignore_result=True, max_retries=_MAX_RETRIES)
def refresh_human_request(self: Task, team_id: int, human_request_id: str) -> None:
    """Recompute one human request from the database and GitHub, then post or edit its Slack card.

    Every change to a request goes through this task, so it must be idempotent: a retry or a second
    queue for the same state posts nothing new. GitHub and Slack errors retry with backoff.
    """
    try:
        human_requests.refresh(team_id, human_request_id)
    except GitHubRateLimitError as e:
        raise self.retry(exc=e, countdown=max(e.retry_after or 0, 60))
    except Exception as e:
        logger.exception("stamphog_human_request_refresh_failed", human_request_id=human_request_id)
        raise self.retry(exc=e, countdown=_RETRY_BASE_SECONDS * 2**self.request.retries)


def queue_human_request_refresh(team_id: int, human_request_id: str) -> None:
    """Queue ``refresh_human_request``. Never raises, because the caller's own write already committed."""
    try:
        refresh_human_request.delay(team_id=team_id, human_request_id=human_request_id)
    except Exception:
        logger.exception("stamphog_human_request_refresh_queue_failed", human_request_id=human_request_id)


def queue_human_request_refresh_after_verdict(run: ReviewRun, status: ReviewRunStatus) -> None:
    """Refresh the pull request's active human request once a run's outcome reached GitHub. Never raises.

    A verdict that a silent run withheld queues nothing, so the card never shows an outcome that
    GitHub does not have.
    """
    try:
        published = run.may_publish() if status == ReviewRunStatus.FAILED else run.verdict_posted_at is not None
        if not published:
            return
        request_ids = (
            HumanRequest.objects.for_team(run.team_id)
            .using(router.db_for_write(HumanRequest))
            .filter(pull_request_id=run.pull_request_id, status__in=ACTIVE_HUMAN_REQUEST_STATUSES)
            .values_list("id", flat=True)
        )
        for request_id in request_ids:
            queue_human_request_refresh(run.team_id, str(request_id))
    except Exception:
        logger.exception("stamphog_human_request_queue_after_verdict_failed", review_run_id=str(run.id))
