"""Celery tasks for user_interviews.

``handle_vapi_webhook`` is the durable side of the inbound Vapi webhook. Ingress answers the
request with a transport receipt that never reflects consumer work, so Vapi does not resend
when persistence fails. The retry therefore has to live in something that outlives the request.
"""

from typing import Any

from django.db import InterfaceError, OperationalError

import structlog
from celery import Task, shared_task

logger = structlog.get_logger(__name__)


def _call_id(payload: dict[str, Any]) -> str | None:
    call: dict[str, Any] = (payload.get("message") or {}).get("call") or {}
    return call.get("id")


@shared_task(
    bind=True,
    name="products.user_interviews.backend.tasks.handle_vapi_webhook",
    ignore_result=True,
    # autoretry_for is load-bearing: bare max_retries without it is silently inert.
    autoretry_for=(OperationalError, InterfaceError),
    # Sized for a database outage, which lasts minutes to hours, while the default backoff is
    # spent in a few seconds. Vapi holds its receipt by the time the task runs and nothing else
    # replays an interview, so every attempt this policy does not make is a report lost. Each
    # attempt waits twice as long as the one before it, capped at ten minutes, which spans about
    # two and a half hours over all the attempts. Jitter spreads the workers that failed at the
    # same moment, and halves that span on average.
    retry_backoff=10,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=20,
    # The report is the only copy of the interview, and by the time the task runs Vapi already
    # holds its receipt. A worker that dies after reserving the message would drop the report with
    # the default early acknowledgement, so the message is acknowledged after the run instead and
    # given back to the broker when the worker is lost. The handler is idempotent on the call id,
    # so the redelivered message creates nothing a second time.
    acks_late=True,
    reject_on_worker_lost=True,
)
def handle_vapi_webhook(
    self: Task,
    payload: dict[str, Any],
    event_type: str,
    team_id: int,
    topic_id: str,
    interviewee_context_id: str,
    interviewee_identifier: str,
    received_at: str | None = None,
) -> None:
    """Store one verified Vapi delivery, outside the request that accepted it.

    ``received_at`` is the ISO time the endpoint received the delivery, and it timestamps the
    lifecycle analytics events. It has a default so that a message queued without it still runs;
    those events then carry the worker's clock instead.
    """
    from products.user_interviews.backend import (  # noqa: PLC0415 - keeps posthog.schema and the embedding worker off the task module's import path
        vapi_events,
    )

    try:
        vapi_events.handle_vapi_webhook_delivery(
            payload,
            event_type,
            team_id=team_id,
            topic_id=topic_id,
            interviewee_context_id=interviewee_context_id,
            interviewee_identifier=interviewee_identifier,
            received_at=received_at,
        )
    except (OperationalError, InterfaceError):
        # autoretry_for re-raises the original error once the retries run out, which reads like any
        # other failed attempt. The last attempt says that the report is now lost, and names the
        # call so the interview can be traced in Vapi.
        if self.request.retries >= self.max_retries:
            logger.exception(
                "user_interviews_vapi_webhook_retries_exhausted",
                event_type=event_type,
                call_id=_call_id(payload),
                team_id=team_id,
                topic_id=topic_id,
            )
        raise
