from django.db import InterfaceError, OperationalError
from django.utils import timezone

from celery import shared_task

from products.mcp_events.backend.models import MCPEventSubscription


@shared_task(ignore_result=True, autoretry_for=(OperationalError, InterfaceError), retry_backoff=True, max_retries=3)
def expire_mcp_event_subscriptions() -> None:
    from products.mcp_events.backend.logic.subscriptions import (  # noqa: PLC0415  # Keeps HogQL off Celery startup.
        EXPIRY_BATCH_SIZE,
        MCPEventSubscriptions,
    )

    if MCPEventSubscriptions.expire() >= EXPIRY_BATCH_SIZE:
        expire_mcp_event_subscriptions.delay()


@shared_task(ignore_result=True, autoretry_for=(OperationalError, InterfaceError), retry_backoff=True, max_retries=3)
def revalidate_mcp_event_subscriptions(team_id: int) -> None:
    from products.mcp_events.backend.logic.revocation import (  # noqa: PLC0415  # Keeps HogQL off Celery startup.
        revalidate_team_subscriptions,
    )

    revalidate_team_subscriptions(team_id)


@shared_task(ignore_result=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def reconcile_mcp_event_subscriptions() -> None:
    teams = (
        MCPEventSubscription.objects.unscoped()
        .filter(active=True, expires_at__gt=timezone.now())
        .values_list("team_id", flat=True)
        .distinct()
    )
    for team_id in teams.iterator():
        revalidate_mcp_event_subscriptions.delay(team_id)
