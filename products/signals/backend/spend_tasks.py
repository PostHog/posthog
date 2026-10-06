import time

from django.conf import settings
from django.db import transaction
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
                with transaction.atomic():
                    pending_spend = SignalSpend.objects.for_team(spend.team_id).filter(id=spend.id, needs_refresh=True)
                    if cost is not None:
                        pending_spend.update(
                            token_cost_microusd=cost.cost_microusd,
                            accounting_failed=False,
                            needs_refresh=False,
                            updated_at=timezone.now(),
                        )
                    else:
                        pending_spend.update(accounting_failed=True, updated_at=timezone.now())
                if cost is None:
                    logger.warning(
                        "signals.spend.generation_unaccounted",
                        stage=spend.stage,
                        team_id=spend.team_id,
                        signal_id=str(spend.signal_id),
                        request_id=spend.source_id,
                    )
        except Exception:
            logger.exception(
                "signals.spend.reconciliation_failed",
                stage=spend.stage,
                team_id=spend.team_id,
                signal_id=str(spend.signal_id) if spend.signal_id else None,
                scout_run_id=str(spend.scout_run_id) if spend.scout_run_id else None,
                request_id=spend.source_id,
            )
            try:
                with transaction.atomic():
                    SignalSpend.objects.for_team(spend.team_id).filter(id=spend.id, needs_refresh=True).update(
                        accounting_failed=True, updated_at=timezone.now()
                    )
            except Exception:
                logger.exception("signals.spend.failure_recording_failed", stage=spend.stage, spend_id=str(spend.id))
