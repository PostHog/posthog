from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

import structlog
from celery import shared_task
from slack_sdk.errors import SlackApiError

from posthog.cloud_utils import get_cached_instance_license
from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.models.scoping import with_team_scope
from posthog.ph_client import ph_scoped_capture
from posthog.scoping_audit import skip_team_scope_audit

from products.signals.backend.billing import current_billing_period_bounds
from products.signals.backend.implementation_pr import PrCloseReason, close_implementation_pr_for_report
from products.signals.backend.models import SignalReportRefund, SignalScoutEmission
from products.signals.backend.scout_harness.slack_delivery import (
    ScoutSlackPermanentDeliveryError,
    post_scout_emission_to_slack,
    slack_api_error_code,
)

logger = structlog.get_logger(__name__)

# Bounded exponential backoff: 2m, 4m, 8m, ... capped at 1h, 8 retries ≈ 5h total. Deliberately
# NOT unbounded — a hard failure should land with the sweeper (and its 7-day horizon) rather
# than retry forever. Rollover itself is survivable: the payload reports the period bounds
# frozen on the refund row, and billing credits against that period as long as it is still the
# customer's immediately-previous one.
_REFUND_SYNC_MAX_RETRIES = 8
_REFUND_SYNC_RETRY_BASE_SECONDS = 120
_REFUND_SYNC_RETRY_MAX_SECONDS = 3600

# Sweeper horizon: stop re-enqueueing unsynced credited refunds after 7 days. Anything older is
# an operational problem surfaced by the failure analytics event, handled manually (a billing
# admin creates the credit with idempotency key `signals_pr_dispute:{billing_customer_id}:{refund_id}`;
# the row then syncs as already_processed on any later attempt).
_REFUND_SYNC_SWEEP_MAX_AGE = timedelta(days=7)

# Billing answered a handled $0 because it could no longer credit the period the refund was
# accepted in — the sync outran billing's late-credit horizon (the frozen period is no longer
# the customer's current or immediately-previous one), or the row predates the frozen period
# bounds. Terminal for automation: retrying recomputes the same $0 (the frozen period only gets
# older), so the sweeper skips these rows and recovery is the documented manual credit path.
_OUT_OF_PERIOD_SYNC_ERROR = "billing: refund period no longer creditable at sync time; credit needs manual recovery"

_SCOUT_SLACK_MAX_RETRIES = 5
_SCOUT_SLACK_RETRY_BASE_SECONDS = 60
_SCOUT_SLACK_RETRY_MAX_SECONDS = 3600


@shared_task(
    name="products.signals.backend.tasks.close_dismissed_report_pr",
    ignore_result=True,
    max_retries=0,
)
@with_team_scope()
def close_dismissed_report_pr(report_id: str, team_id: int, reason: PrCloseReason = "suppressed") -> None:
    close_implementation_pr_for_report(team_id, report_id, reason=reason)


def _slack_retry_after_seconds(exc: Exception) -> int | None:
    if not isinstance(exc, SlackApiError) or not exc.response:
        return None
    headers = exc.response.headers or {}
    raw_value = headers.get("Retry-After") or headers.get("retry-after")
    try:
        retry_after = int(raw_value) if raw_value is not None else None
    except (TypeError, ValueError):
        return None
    return retry_after if retry_after is not None and retry_after > 0 else None


def _scout_slack_retry_countdown(exc: Exception, retries: int) -> int:
    backoff = min(_SCOUT_SLACK_RETRY_BASE_SECONDS * (2**retries), _SCOUT_SLACK_RETRY_MAX_SECONDS)
    retry_after = _slack_retry_after_seconds(exc)
    return min(max(backoff, retry_after or 0), _SCOUT_SLACK_RETRY_MAX_SECONDS)


@shared_task(
    name="products.signals.backend.tasks.deliver_scout_slack_output",
    ignore_result=True,
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=_SCOUT_SLACK_MAX_RETRIES,
)
@with_team_scope(canonical=True)
def deliver_scout_slack_output(
    self,
    team_id: int,
    emission_id: str,
    integration_id: int,
    channel: str,
) -> None:
    emission = SignalScoutEmission.objects.select_related("scout_run").filter(id=emission_id).first()
    if emission is None:
        logger.warning(
            "signals_scout.slack_delivery_emission_missing",
            team_id=team_id,
            emission_id=emission_id,
        )
        return

    context = {
        "team_id": team_id,
        "emission_id": emission_id,
        "integration_id": integration_id,
    }
    try:
        post_scout_emission_to_slack(emission, integration_id=integration_id, channel=channel)
    except ScoutSlackPermanentDeliveryError as exc:
        capture_exception(exc, {**context, "error_code": exc.error_code})
        logger.warning(
            "signals_scout.slack_delivery_permanent_failure",
            **context,
            error_code=exc.error_code,
        )
        return
    except Exception as exc:
        if self.request.retries < _SCOUT_SLACK_MAX_RETRIES:
            countdown = _scout_slack_retry_countdown(exc, self.request.retries)
            logger.warning(
                "signals_scout.slack_delivery_retrying",
                **context,
                error_code=slack_api_error_code(exc) if isinstance(exc, SlackApiError) else None,
                attempt=self.request.retries + 1,
                countdown=countdown,
            )
            raise self.retry(exc=exc, countdown=countdown)

        capture_exception(
            exc,
            {
                **context,
                "error_code": slack_api_error_code(exc) if isinstance(exc, SlackApiError) else None,
                "attempts": self.request.retries + 1,
            },
        )
        logger.exception(
            "signals_scout.slack_delivery_exhausted",
            **context,
            attempts=self.request.retries + 1,
        )
        return

    logger.info("signals_scout.slack_delivery_sent", **context)


def enqueue_scout_slack_delivery(
    *,
    team_id: int,
    emission_id: str,
    integration_id: int,
    channel: str,
) -> None:
    """Publish after commit, capturing broker failures without affecting the completed emit."""
    try:
        deliver_scout_slack_output.delay(team_id, emission_id, integration_id, channel)
    except Exception as exc:
        capture_exception(
            exc,
            {
                "team_id": team_id,
                "emission_id": emission_id,
                "integration_id": integration_id,
            },
        )
        logger.exception(
            "signals_scout.slack_delivery_enqueue_failed",
            team_id=team_id,
            emission_id=emission_id,
            integration_id=integration_id,
        )


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
    # Report the period bounds frozen at refund acceptance, so billing credits against the
    # period the refund was accepted in even when this sync lands after rollover — recomputing
    # bounds here is exactly the drift that loses the credit. The fallback covers rows created
    # before the bounds were snapshotted.
    if refund.period_start is not None and refund.period_end is not None:
        period_start, period_end = refund.period_start, refund.period_end
    else:
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
        credit_amount_usd = Decimal(str(response["credit_amount_usd"]))
    except Exception as exc:
        if self.request.retries < _REFUND_SYNC_MAX_RETRIES:
            countdown = min(_REFUND_SYNC_RETRY_BASE_SECONDS * (2**self.request.retries), _REFUND_SYNC_RETRY_MAX_SECONDS)
            raise self.retry(exc=exc, countdown=countdown)
        # Terminal for this delivery — record the error for the weekly review; the hourly sweeper
        # keeps re-enqueueing the row for up to 7 days, after which recovery is operational. The
        # conditional update mirrors the success-path claim below: never stamp an error (or emit
        # the failed event) onto a row a concurrent delivery already synced.
        recorded = (
            # nosemgrep: idor-lookup-without-team (id comes from the sanctioned unscoped lookup above; system task, no user input)
            SignalReportRefund.objects.unscoped()
            .filter(id=refund.id, billing_synced_at__isnull=True)
            .update(billing_sync_error=str(exc)[:4000])
        )
        if recorded:
            capture_exception(exc, {"refund_id": str(refund.id), "team_id": refund.team_id})
            _capture_refund_sync_event(refund, "signals_pr_refund_credit_failed", {"error": str(exc)[:1000]})
        return

    if response.get("zero_reason") == "out_of_period":
        # The $0 means billing could no longer credit the frozen refund period (see
        # _OUT_OF_PERIOD_SYNC_ERROR), not that the refund was legitimately free. Record a sync
        # error instead of a synced $0 so the row surfaces for manual recovery.
        recorded = (
            # nosemgrep: idor-lookup-without-team (id comes from the sanctioned unscoped lookup above; system task, no user input)
            SignalReportRefund.objects.unscoped()
            .filter(id=refund.id, billing_synced_at__isnull=True)
            .update(billing_sync_error=_OUT_OF_PERIOD_SYNC_ERROR)
        )
        if recorded:
            capture_exception(
                Exception("signals refund credit lost to billing period rollover"),
                {"refund_id": str(refund.id), "team_id": refund.team_id},
            )
            _capture_refund_sync_event(refund, "signals_pr_refund_credit_failed", {"error": _OUT_OF_PERIOD_SYNC_ERROR})
        return

    # Atomic claim: the on-commit enqueue and the hourly sweeper can race two deliveries for the
    # same refund past the billing_synced_at gate above while the billing call is in flight
    # (billing stays idempotent, so the credit itself is issued once). Only the delivery that
    # flips the row records the sync and emits the issued event, keeping the weekly-review
    # analytics single-counted.
    claimed = (
        # nosemgrep: idor-lookup-without-team (id comes from the sanctioned unscoped lookup above; system task, no user input)
        SignalReportRefund.objects.unscoped()
        .filter(id=refund.id, billing_synced_at__isnull=True)
        .update(credit_amount_usd=credit_amount_usd, billing_synced_at=timezone.now(), billing_sync_error=None)
    )
    if not claimed:
        return
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
        # Horizon-lost credits are terminal for automation — replaying returns the same $0.
        .exclude(billing_sync_error=_OUT_OF_PERIOD_SYNC_ERROR)
        .values_list("id", flat=True)
    )
    for refund_id in pending_ids:
        sync_signals_refund_credit.delay(str(refund_id))
    if pending_ids:
        logger.info("signals refund credit sweeper re-enqueued pending refunds", count=len(pending_ids))
