from celery import shared_task


@shared_task(ignore_result=True)
def expire_mcp_event_subscriptions() -> None:
    from products.mcp_events.backend.logic.subscriptions import (  # noqa: PLC0415 — keeps HogQL off Celery startup
        EXPIRY_BATCH_SIZE,
        MCPEventSubscriptions,
    )

    if MCPEventSubscriptions.expire() >= EXPIRY_BATCH_SIZE:
        expire_mcp_event_subscriptions.delay()


@shared_task(ignore_result=True)
def revalidate_mcp_event_subscriptions(team_id: int) -> None:
    from products.mcp_events.backend.logic.revocation import (  # noqa: PLC0415 — keeps HogQL off Celery startup
        revalidate_team_subscriptions,
    )

    revalidate_team_subscriptions(team_id)
