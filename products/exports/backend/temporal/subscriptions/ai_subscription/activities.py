import uuid
import datetime as dt
from datetime import datetime

from django.utils import timezone as tz

import dateutil.parser
import temporalio.activity
from asgiref.sync import sync_to_async
from structlog import get_logger
from temporalio.exceptions import ApplicationError

from posthog.models import OrganizationMembership
from posthog.ph_client import ph_scoped_capture
from posthog.sync import database_sync_to_async

from products.exports.backend.models.subscription import Subscription, SubscriptionDelivery
from products.exports.backend.temporal.subscriptions.ai_subscription.delivery import (
    build_ai_subscription_report,
    send_email_ai_subscription_credit_limited,
    send_email_ai_subscription_report,
    send_slack_ai_subscription_report,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.report_pipeline import AiReportResult
from products.exports.backend.temporal.subscriptions.ai_subscription.spec_generator import PromptRejectedError
from products.exports.backend.temporal.subscriptions.delivery_common import (
    auto_disable_and_return,
    deliver_email,
    deliver_slack,
)
from products.exports.backend.temporal.subscriptions.types import (
    DeliverSubscriptionInputs,
    DeliverSubscriptionResult,
    GenerateAIReportInputs,
    GenerateAIReportResult,
    RecipientResult,
)

from ee.billing.quota_limiting import is_team_over_ai_credit_budget
from ee.tasks.subscriptions import _capture_delivery_failed_event
from ee.tasks.subscriptions.auto_disable import AI_CONSENT_REVOKED_DISABLE_REASON, AI_PROMPT_INVALID_DISABLE_REASON

LOGGER = get_logger(__name__)

# `SubscriptionDelivery.content_snapshot` key the AI report markdown is written under by
# `generate_ai_subscription_report` and read back by `_deliver_ai_subscription`. The markdown
# can exceed Temporal's ~2 MiB payload cap, so it travels through Postgres by reference rather
# than on the wire — the same pattern insight snapshots use.
AI_REPORT_SNAPSHOT_KEY = "ai_report"
# Companion key holding per-step query diagnostics (the generated HogQL + failure type) so a degraded
# report is debuggable after the fact. Written alongside the markdown; never shipped to recipients.
AI_REPORT_DIAGNOSTICS_KEY = "ai_report_diagnostics"

# If the org's AI-credit balance isn't synced yet, reschedule roughly a billing cycle out so a
# skipped sub still moves forward instead of re-firing every tick.
_CREDIT_RESET_FALLBACK_DAYS = 31


async def _load_ai_report(delivery_id: uuid.UUID) -> str | None:
    @database_sync_to_async(thread_sensitive=False)
    def _read() -> str | None:
        # DoesNotExist is tolerated here (read side): a missing row just means "no report yet".
        try:
            snapshot = SubscriptionDelivery.objects.values_list("content_snapshot", flat=True).get(pk=delivery_id)
        except SubscriptionDelivery.DoesNotExist:
            return None
        if not isinstance(snapshot, dict):
            return None
        report = snapshot.get(AI_REPORT_SNAPSHOT_KEY)
        return report if isinstance(report, str) and report else None

    return await _read()


async def _persist_ai_report(delivery_id: uuid.UUID, result: AiReportResult) -> None:
    @database_sync_to_async(thread_sensitive=False)
    def _write() -> None:
        # No DoesNotExist guard: create_delivery_record always writes this row before
        # generation runs, so a missing row is a wiring bug — let it raise loudly.
        delivery = SubscriptionDelivery.objects.get(pk=delivery_id)
        delivery.content_snapshot = {
            **(delivery.content_snapshot or {}),
            AI_REPORT_SNAPSHOT_KEY: result.markdown,
            AI_REPORT_DIAGNOSTICS_KEY: [
                {"description": d.description, "hogql": d.hogql, "ok": d.ok, "error_type": d.error_type}
                for d in result.diagnostics
            ],
        }
        delivery.save(update_fields=["content_snapshot", "last_updated_at"])

    await _write()


def _capture_ai_credit_event(
    subscription: Subscription, event: str, properties: dict[str, object] | None = None
) -> None:
    try:
        distinct_id = (
            subscription.created_by.distinct_id
            if subscription.created_by and subscription.created_by.distinct_id
            else f"team_{subscription.team_id}"
        )
        with ph_scoped_capture() as capture:
            capture(
                distinct_id=distinct_id,
                event=event,
                properties={
                    "subscription_id": subscription.id,
                    "team_id": subscription.team_id,
                    "$process_person_profile": False,
                    **(properties or {}),
                },
                groups={"organization": str(subscription.team.organization_id)},
            )
    except Exception:
        LOGGER.warning(f"{event}.capture_failed", subscription_id=subscription.id, exc_info=True)


def _ai_credit_reset_date(subscription: Subscription) -> datetime:
    usage = subscription.team.organization.usage
    # usage["period"] is [current_period_start, current_period_end] as ISO strings (set in
    # billing_manager.py); index 1 — the period end — is when AI credits reset. isinstance guard:
    # a non-dict `usage` would raise AttributeError on .get, which the parse except below misses.
    period = usage.get("period") if isinstance(usage, dict) else None
    if period and len(period) == 2 and period[1]:
        try:
            reset_date = dateutil.parser.isoparse(period[1])
            # A rolled-over-but-not-yet-synced period leaves period[1] in the past, which would
            # resume "on a past date" and re-fire every tick — fall through to the fallback instead.
            if reset_date > tz.now():
                return reset_date
        except (ValueError, TypeError):
            pass
    return tz.now() + dt.timedelta(days=_CREDIT_RESET_FALLBACK_DAYS)


def _skip_ai_delivery_over_credit_limit_sync(subscription: Subscription) -> datetime:
    """Reschedule the over-limit subscription past the credit reset and notify the owner once.
    Runs entirely sync (DB + email) — call via `database_sync_to_async`.

    Persists `next_delivery_date = reset_date` so the always-runs `advance_next_delivery_date`
    activity recomputes from it (`rrule.after(reset_date)`) — otherwise the next slot could fall
    before the reset and re-fire while still over-limit.
    """
    reset_date = _ai_credit_reset_date(subscription)
    subscription.next_delivery_date = reset_date
    subscription.save(update_fields=["next_delivery_date"])

    creator = subscription.created_by
    # Skip the notice if the creator has left the org: they can no longer act on the credit limit,
    # and emailing them their former org's billing status leaks it outside the org. The org still
    # learns it's over budget through the normal billing/quota path.
    creator_is_org_member = (
        creator is not None
        and OrganizationMembership.objects.filter(
            organization_id=subscription.team.organization_id, user=creator
        ).exists()
    )
    if creator and creator.email and creator_is_org_member:
        send_email_ai_subscription_credit_limited(
            email=creator.email,
            subscription=subscription,
            resume_date=reset_date,
            # Stable within a billing period (reset_date is the period end), so MessagingRecord
            # dedups to one notice per credit-reset cycle.
            billing_period_key=reset_date.date().isoformat(),
        )
    _capture_ai_credit_event(
        subscription, "ai_subscription_skipped_over_credit_budget", {"resumes_at": reset_date.isoformat()}
    )
    return reset_date


@temporalio.activity.defn
async def generate_ai_subscription_report(inputs: GenerateAIReportInputs) -> GenerateAIReportResult:
    # The "decide what to send" phase, split from delivery so the LLM runs once up front with
    # its own retry policy. Terminal failures (consent revoked, prompt invalid) auto-disable and
    # return aborted=True; transient errors bubble up for the activity's Temporal retry.
    subscription = await database_sync_to_async(
        Subscription.objects.select_related("created_by", "team", "team__organization").get,
        thread_sensitive=False,
    )(pk=inputs.subscription_id)

    # Idempotency on Temporal redispatch: if a prior attempt already produced the report,
    # don't re-bill the LLM — the point of the generate -> deliver split is one LLM run.
    if await _load_ai_report(inputs.delivery_id) is not None:
        await LOGGER.ainfo("generate_ai_subscription_report.already_generated", subscription_id=subscription.id)
        return GenerateAIReportResult(aborted=False)

    # Consent is gated once here, before any LLM cost — creation-time gates don't catch an
    # org that revokes AI-data-processing approval later. Auto-disable so it stops re-firing.
    if not subscription.team.organization.is_ai_data_processing_approved:
        LOGGER.warning("generate_ai_subscription_report.consent_revoked", subscription_id=subscription.id)
        aborted = await auto_disable_and_return(subscription, AI_CONSENT_REVOKED_DISABLE_REASON, [])
        return GenerateAIReportResult(aborted=True, recipient_results=aborted.recipient_results)

    # Gate on AI credits before any LLM cost — but only past the idempotency check above, so an
    # already-generated report (its tokens already spent) still ships. The interactive Max path
    # enforces this same limit in ee/api/conversation.py; scheduled reports need their own check
    # or they'd keep spending against an exhausted balance. Fail open: a transient quota-lookup
    # error shouldn't drop a deliverable report. The check reads Redis (not the DB), so
    # sync_to_async — but the reschedule below writes the row, so that stays database_sync_to_async.
    try:
        over_credit_budget = await sync_to_async(is_team_over_ai_credit_budget, thread_sensitive=False)(
            subscription.team.api_token
        )
    except Exception as exc:
        over_credit_budget = False
        LOGGER.warning(
            "generate_ai_subscription_report.ai_credit_budget_check_failed",
            subscription_id=subscription.id,
            error=str(exc),
            exc_info=True,
        )
        # Fail-open is invisible to alerting otherwise — the report ships while billing against a
        # possibly-exhausted balance, the exact failure mode this gate exists to prevent.
        await sync_to_async(_capture_ai_credit_event, thread_sensitive=False)(
            subscription, "ai_subscription_credit_check_failed", {"error": str(exc)}
        )
    if over_credit_budget:
        reset_date = await database_sync_to_async(_skip_ai_delivery_over_credit_limit_sync, thread_sensitive=False)(
            subscription
        )
        LOGGER.warning(
            "generate_ai_subscription_report.ai_skipped_over_credit_limit",
            subscription_id=subscription.id,
            team_id=subscription.team_id,
            resumes_at=reset_date.isoformat(),
        )
        # skipped=True → the workflow records SKIPPED (not FAILED — the sub isn't broken) and skips
        # delivery; the sub stays enabled and advance_next_delivery_date recomputes from the reset.
        return GenerateAIReportResult(skipped=True)

    try:
        report_result = await build_ai_subscription_report(subscription)
    except PromptRejectedError as exc:
        # Structurally permanent: no creator, prompt now fails sanitization, or the
        # planner returned a malformed plan. Re-firing wastes LLM tokens every cycle.
        LOGGER.warning(
            "generate_ai_subscription_report.prompt_rejected",
            subscription_id=subscription.id,
            reason=str(exc),
        )
        _capture_delivery_failed_event(subscription, exc)
        # Seed a recipient result with the exception detail first — it carries planner
        # context that the disable reason (appended next by `auto_disable_and_return`)
        # doesn't.
        recipient_results = [
            RecipientResult(
                recipient=subscription.target_value,
                status="failed",
                error={"message": str(exc), "type": "PromptRejectedError"},
            )
        ]
        aborted = await auto_disable_and_return(subscription, AI_PROMPT_INVALID_DISABLE_REASON, recipient_results)
        return GenerateAIReportResult(aborted=True, recipient_results=aborted.recipient_results)

    await _persist_ai_report(inputs.delivery_id, report_result)
    return GenerateAIReportResult(aborted=False)


async def _deliver_ai_subscription(
    subscription: Subscription,
    inputs: DeliverSubscriptionInputs,
    recipient_results: list[RecipientResult],
) -> DeliverSubscriptionResult:
    # Ships the report generate_ai_subscription_report already produced (read back from the
    # delivery row) — no LLM work here. Transient send errors retry; terminal Slack errors auto-disable.
    if inputs.delivery_id is None:
        # The AI workflow always creates the delivery row and runs generation before
        # delivery, so a missing reference is a wiring bug, not a runtime state.
        raise ApplicationError(f"AI delivery for subscription {subscription.id} has no delivery_id", non_retryable=True)

    delivery_id = inputs.delivery_id
    markdown = await _load_ai_report(delivery_id)
    if markdown is None:
        # Generation persists the report before delivery is scheduled, so a missing report
        # means the row was lost. Non-retryable: re-running *delivery* can't regenerate the
        # report, so retrying just burns attempts — fail loud rather than ship an empty report.
        raise ApplicationError(
            f"AI report missing for subscription {subscription.id} (delivery {inputs.delivery_id})",
            non_retryable=True,
        )

    if subscription.target_type == Subscription.SubscriptionTarget.EMAIL:
        # Dedup key for MessagingRecord: stable across this run's retries, unique per run so a re-test re-sends.
        workflow_run_id = temporalio.activity.info().workflow_run_id
        if workflow_run_id is None:
            raise ApplicationError("AI email delivery requires a workflow run id", non_retryable=True)

        async def _send_email(email: str) -> None:
            await database_sync_to_async(send_email_ai_subscription_report, thread_sensitive=False)(
                email=email,
                subscription=subscription,
                markdown=markdown,
                delivery_run_id=workflow_run_id,
                delivery_id=delivery_id,
            )

        return await deliver_email(subscription, inputs, recipient_results, _send_email)
    if subscription.target_type == Subscription.SubscriptionTarget.SLACK:
        return await deliver_slack(
            subscription,
            recipient_results,
            lambda integration: send_slack_ai_subscription_report(
                subscription=subscription, markdown=markdown, integration=integration, delivery_id=delivery_id
            ),
        )
    # `validate_subscription_for_delivery` auto-disables unsupported targets up front,
    # so reaching here means an invariant was violated.
    raise ApplicationError(
        f"AI delivery reached an unsupported target {subscription.target_type!r}", non_retryable=True
    )
