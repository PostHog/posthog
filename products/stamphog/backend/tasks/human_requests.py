"""Celery tasks that keep a human request and its Slack card in step with the pull request."""

from __future__ import annotations

import structlog
from celery import shared_task

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
def refresh_human_request(team_id: int, human_request_id: str) -> None:
    """Recompute one human request from the database and GitHub, then post or edit its Slack card.

    Every change to a request goes through this task, so it must be idempotent: a retry or a second
    queue for the same state posts nothing new.
    """
    # The card and the state machine land separately, so this only records that a refresh was asked.
    logger.info("stamphog_human_request_refresh_queued", team_id=team_id, human_request_id=human_request_id)


def queue_human_request_refresh(team_id: int, human_request_id: str) -> None:
    """Queue ``refresh_human_request``. Never raises, because the caller's own write already committed."""
    try:
        refresh_human_request.delay(team_id=team_id, human_request_id=human_request_id)
    except Exception:
        logger.exception("stamphog_human_request_refresh_queue_failed", human_request_id=human_request_id)
