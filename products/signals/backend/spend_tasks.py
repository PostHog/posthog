import time

from django.db import transaction
from django.utils import timezone

import structlog
from celery import shared_task

from posthog.redis import get_client

from products.signals.backend.models import SignalSpend, SignalSpendMetadata
from products.signals.backend.spend import mark_spend_metadata_dirty, refresh_task_spend
from products.signals.backend.spend_metadata import refresh_signal_spend_metadata

logger = structlog.get_logger(__name__)


def reconcile_spend_metadata(*, deadline: float) -> None:
    pending = SignalSpendMetadata.objects.unscoped().filter(needs_refresh=True).order_by("updated_at")[:1000]
    for entry in pending:
        if time.monotonic() >= deadline:
            break
        lock = get_client().lock(f"signals:spend_metadata:{entry.team_id}:{entry.signal_id}", timeout=60)
        if not lock.acquire(blocking=False):
            continue
        confirmed = False
        try:
            confirmed = refresh_signal_spend_metadata(team_id=entry.team_id, signal_id=str(entry.signal_id))
        except Exception:
            logger.exception(
                "signals.spend.accounting_failed",
                stage="persist_metadata",
                team_id=entry.team_id,
                signal_id=str(entry.signal_id),
            )
        finally:
            try:
                SignalSpendMetadata.objects.for_team(entry.team_id).filter(
                    id=entry.id, updated_at=entry.updated_at
                ).update(needs_refresh=not confirmed, updated_at=timezone.now())
            finally:
                lock.release()


@shared_task(ignore_result=True)
def reconcile_signal_spend() -> None:
    deadline = time.monotonic() + 45
    pending = list(
        SignalSpend.objects.unscoped().filter(needs_refresh=True, is_task=True).order_by("updated_at")[:1000]
    )
    for spend in pending:
        if time.monotonic() >= deadline:
            break
        try:
            refresh_task_spend(spend_id=spend.id, team_id=spend.team_id)
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
                    if spend.signal_id:
                        mark_spend_metadata_dirty(team_id=spend.team_id, signal_id=str(spend.signal_id))
            except Exception:
                logger.exception("signals.spend.failure_recording_failed", stage=spend.stage, spend_id=str(spend.id))
    reconcile_spend_metadata(deadline=time.monotonic() + 15)
