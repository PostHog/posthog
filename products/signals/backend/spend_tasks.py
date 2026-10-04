import time

from django.conf import settings
from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync
from celery import shared_task

from posthog.llm.gateway_usage import fetch_gateway_cost

from products.signals.backend.models import SignalSpend
from products.signals.backend.spend import refresh_task_spend

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
def reconcile_signal_spend() -> None:
    deadline = time.monotonic() + 45
    pending = list(SignalSpend.objects.unscoped().filter(needs_refresh=True).order_by("updated_at")[:1000])
    for spend in pending:
        if time.monotonic() >= deadline:
            break
        try:
            if spend.is_task:
                refresh_task_spend(spend_id=spend.id, team_id=spend.team_id)
            else:
                cost = async_to_sync(fetch_gateway_cost)(
                    spend.source_id, base_url=settings.AI_GATEWAY_URL or "", api_key=settings.AI_GATEWAY_API_KEY or ""
                )
                SignalSpend.objects.for_team(spend.team_id).filter(id=spend.id, needs_refresh=True).update(
                    token_cost_microusd=cost.cost_microusd if cost else None,
                    needs_refresh=cost is None,
                    updated_at=timezone.now(),
                )
        except Exception:
            logger.exception("signals.spend.reconciliation_failed", spend_id=str(spend.id))
            SignalSpend.objects.for_team(spend.team_id).filter(id=spend.id).update(updated_at=timezone.now())
