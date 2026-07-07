from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

import structlog
from celery import shared_task

from posthog.cloud_utils import get_cached_instance_license
from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.models.scoping import with_team_scope
from posthog.ph_client import ph_scoped_capture
from posthog.scoping_audit import skip_team_scope_audit

from products.signals.backend.billing import current_billing_period_bounds
from products.signals.backend.implementation_pr import PrCloseReason, close_implementation_pr_for_report
from products.signals.backend.models import SignalReportRefund

logger = structlog.get_logger(__name__)

# Bounded exponential backoff: 2m, 4m, 8m, ... capped at 1h, 8 retries ≈ 5h total. Deliberately
# NOT unbounded — a sync drifting past the org's billing-period rollover would compute against
# the wrong period (billing also guards this server-side, returning a $0 credit with a note).
_REFUND_SYNC_MAX_RETRIES = 8
_REFUND_SYNC_RETRY_BASE_SECONDS = 120
_REFUND_SYNC_RETRY_MAX_SECONDS = 3600

# Sweeper horizon: stop re-enqueueing unsynced credited refunds after 7 days. Anything older is
# an operational problem surfaced by the failure analytics event, handled manually (a billing
# admin creates the credit with idempotency key `signals_pr_dispute:{refund_id}`; the row then
# syncs as already_processed on any later attempt).
_REFUND_SYNC_SWEEP_MAX_AGE = timedelta(days=7)


@shared_task(
    name="products.signals.backend.tasks.close_dismissed_report_pr",
    ignore_result=True,
    max_retries=0,
)
@with_team_scope()
def close_dismissed_report_pr(report_id: str, team_id: int, reason: PrCloseReason = "suppressed") -> None:
    close_implementation_pr_for_report(team_id, report_id, reason=reason)


def _capture_refund_sync_event(refund: SignalReportRefund, event: str, extra: dict[str, object]) -> None:
    organization = refund.team.organization
    with ph_scoped_capture() as capture:
        capture(
            distinct_id=str(organization.id),
            event=event,
            properties={
                "team_id": refund.team_id,
                "organization_id": str(organization.id),
                "report_id": str(refund.report_id),
                "refund_id": str(refund.id),
                "credits": refund.credits,
                **extra,
            },
            groups=groups(organization=organization),
        )


@shared_task(
    name="products.signals.backend.tasks.sync_signals_refund_credit",
    ignore_result=True,
    bind=True,
    max_retries=_REFUND_SYNC_MAX_RETRIES,
)
@skip_team_scope_audit
def sync_signals_refund_credit(self, refund_id: str) -> None:
    """Report a credited-path refund to the billing dispute endpoint and record the outcome.

    Safe to re-deliver at any time (double-enqueue, sweeper overlap, manual re-run): billing is
    idempotent on `refund_id`, and an already-synced row returns immediately. User experience is
    unaffected while this lags — archive + badge + freed quota slot all happened at refund time;
    only the invoice credit waits.
    """
    from ee.billing.billing_manager import (
        BillingManager,  # noqa: PLC0415 — keeps the ee layer off the products import path (precedent: posthog/tasks/sync_billing.py)
    )

    refund = (
        # nosemgrep: idor-lookup-without-team (system Celery task keyed by refund id from our own enqueue/sweeper, no user input; unscoped is the sanctioned cross-team access)
        SignalReportRefund.objects.unscoped()
        .select_related("team__organization")
        .filter(id=refund_id, billing_path=SignalReportRefund.BillingPath.CREDITED)
        .first()
    )
    if refund is None:
        logger.warning("signals refund credit sync: no credited refund found", refund_id=refund_id)
        return
    if refund.billing_synced_at is not None:
        return

    organization = refund.team.organization
    period_start, period_end = current_billing_period_bounds(organization)
    payload = {
        "refund_id": str(refund.id),
        "credits": refund.credits,
        "metadata": {
            "team_id": refund.team_id,
            "report_id": str(refund.report_id),
            "pr_url": refund.pr_url,
            "pr_run_created_at": refund.pr_run_created_at.isoformat(),
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
        },
    }

    try:
        license = get_cached_instance_license()
        response = BillingManager(license, None).dispute_signals_pr(organization, payload)
        credit_amount_usd = Decimal(response["credit_amount_usd"])
    except Exception as exc:
        if self.request.retries < _REFUND_SYNC_MAX_RETRIES:
            countdown = min(_REFUND_SYNC_RETRY_BASE_SECONDS * (2**self.request.retries), _REFUND_SYNC_RETRY_MAX_SECONDS)
            raise self.retry(exc=exc, countdown=countdown)
        # Terminal for this delivery — record the error for the weekly review; the hourly sweeper
        # keeps re-enqueueing the row for up to 7 days, after which recovery is operational.
        refund.billing_sync_error = str(exc)[:4000]
        refund.save(update_fields=["billing_sync_error"])
        capture_exception(exc, {"refund_id": str(refund.id), "team_id": refund.team_id})
        _capture_refund_sync_event(refund, "signals_pr_refund_credit_failed", {"error": str(exc)[:1000]})
        return

    refund.credit_amount_usd = credit_amount_usd
    refund.billing_synced_at = timezone.now()
    refund.billing_sync_error = None
    refund.save(update_fields=["credit_amount_usd", "billing_synced_at", "billing_sync_error"])
    _capture_refund_sync_event(
        refund,
        "signals_pr_refund_credit_issued",
        {
            "credit_amount_usd": str(credit_amount_usd),
            "already_processed": bool(response.get("already_processed")),
        },
    )


@shared_task(
    name="products.signals.backend.tasks.sync_pending_signals_refund_credits",
    ignore_result=True,
    max_retries=0,
)
@skip_team_scope_audit
def sync_pending_signals_refund_credits() -> None:
    """Hourly sweeper: re-enqueue credited refunds whose billing sync hasn't landed yet.

    Catches deliveries lost to worker crashes / deploys and rows whose bounded retries were
    exhausted while billing was down. Only rows younger than the sweep horizon are retried;
    re-enqueueing an already-synced row is a no-op in the task itself.
    """
    cutoff = timezone.now() - _REFUND_SYNC_SWEEP_MAX_AGE
    pending_ids = list(
        SignalReportRefund.objects.unscoped()
        .filter(
            billing_path=SignalReportRefund.BillingPath.CREDITED,
            billing_synced_at__isnull=True,
            created_at__gte=cutoff,
        )
        .values_list("id", flat=True)
    )
    for refund_id in pending_ids:
        sync_signals_refund_credit.delay(str(refund_id))
    if pending_ids:
        logger.info("signals refund credit sweeper re-enqueued pending refunds", count=len(pending_ids))
