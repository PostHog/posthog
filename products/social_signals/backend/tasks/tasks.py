"""Celery tasks for social_signals.

Tasks are kept thin — heavy lifting lives in ``logic.analysis``. The Celery
boundary is here so workers can be scaled independently and retries are
managed by Celery rather than reinvented in our code.
"""

from __future__ import annotations

import structlog
from celery import shared_task

from ..logic.analysis import run_analyzers_for_mention

logger = structlog.get_logger(__name__)


@shared_task(
    name="social_signals.analyze_mention",
    queue="social_signals",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=3,
    acks_late=True,
)
def analyze_mention_task(mention_id: str) -> None:
    """Run every default analyzer against a freshly ingested mention.

    Idempotent: re-running overwrites per-analyzer result rows keyed on
    ``(mention, kind)``.
    """
    logger.info("social_signals.analyze.start", mention_id=mention_id)
    run_analyzers_for_mention(mention_id)
    logger.info("social_signals.analyze.done", mention_id=mention_id)
