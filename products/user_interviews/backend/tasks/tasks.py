"""Celery tasks for user_interviews.

``handle_vapi_webhook`` is the durable side of the inbound Vapi webhook. Ingress answers the
request with a transport receipt that never reflects consumer work, so Vapi does not resend
when persistence fails. The retry therefore has to live in something that outlives the request.
"""

from typing import Any

from django.db import InterfaceError, OperationalError

from celery import shared_task


@shared_task(
    name="products.user_interviews.backend.tasks.handle_vapi_webhook",
    ignore_result=True,
    # autoretry_for is load-bearing: bare max_retries without it is silently inert.
    autoretry_for=(OperationalError, InterfaceError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    # The report is the only copy of the interview, and by the time the task runs Vapi already
    # holds its receipt. A worker that dies after reserving the message would drop the report with
    # the default early acknowledgement, so the message is acknowledged after the run instead and
    # given back to the broker when the worker is lost. The handler is idempotent on the call id,
    # so the redelivered message creates nothing a second time.
    acks_late=True,
    reject_on_worker_lost=True,
)
def handle_vapi_webhook(payload: dict[str, Any], event_type: str, sharing_configuration_id: int) -> None:
    from products.user_interviews.backend import (  # noqa: PLC0415 - keeps posthog.schema and the embedding worker off the task module's import path
        vapi_events,
    )

    vapi_events.handle_vapi_webhook_delivery(payload, event_type, sharing_configuration_id=sharing_configuration_id)
