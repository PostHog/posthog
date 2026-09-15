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
)
def handle_vapi_webhook(payload: dict[str, Any], event_type: str) -> None:
    from products.user_interviews.backend import (  # noqa: PLC0415 - keeps posthog.schema and the embedding worker off the task module's import path
        vapi_events,
    )

    vapi_events.handle_vapi_webhook_delivery(payload, event_type)
