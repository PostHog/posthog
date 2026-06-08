import uuid

import temporalio.activity
from structlog import get_logger
from temporalio.exceptions import ApplicationError

from posthog.sync import database_sync_to_async

from products.exports.backend.models.subscription import Subscription, SubscriptionDelivery
from products.exports.backend.temporal.subscriptions.ai_subscription.delivery import (
    generate_ai_subscription_markdown,
    send_email_ai_subscription_report,
    send_slack_ai_subscription_report,
)
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

from ee.tasks.subscriptions import _capture_delivery_failed_event
from ee.tasks.subscriptions.auto_disable import AI_CONSENT_REVOKED_DISABLE_REASON, AI_PROMPT_INVALID_DISABLE_REASON

LOGGER = get_logger(__name__)

# `SubscriptionDelivery.content_snapshot` key the AI report markdown is written under by
# `generate_ai_subscription_report` and read back by `_deliver_ai_subscription`. The markdown
# can exceed Temporal's ~2 MiB payload cap, so it travels through Postgres by reference rather
# than on the wire — the same pattern insight snapshots use.
AI_REPORT_SNAPSHOT_KEY = "ai_report"


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


async def _persist_ai_report(delivery_id: uuid.UUID, markdown: str) -> None:
    @database_sync_to_async(thread_sensitive=False)
    def _write() -> None:
        # No DoesNotExist guard: create_delivery_record always writes this row before
        # generation runs, so a missing row is a wiring bug — let it raise loudly.
        delivery = SubscriptionDelivery.objects.get(pk=delivery_id)
        delivery.content_snapshot = {**(delivery.content_snapshot or {}), AI_REPORT_SNAPSHOT_KEY: markdown}
        delivery.save(update_fields=["content_snapshot", "last_updated_at"])

    await _write()


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

    try:
        markdown = await generate_ai_subscription_markdown(subscription)
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

    await _persist_ai_report(inputs.delivery_id, markdown)
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

    markdown = await _load_ai_report(inputs.delivery_id)
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
            )

        return await deliver_email(subscription, inputs, recipient_results, _send_email)
    if subscription.target_type == Subscription.SubscriptionTarget.SLACK:
        return await deliver_slack(
            subscription,
            recipient_results,
            lambda integration: send_slack_ai_subscription_report(
                subscription=subscription, markdown=markdown, integration=integration
            ),
        )
    # `validate_subscription_for_delivery` auto-disables unsupported targets up front,
    # so reaching here means an invariant was violated.
    raise ApplicationError(
        f"AI delivery reached an unsupported target {subscription.target_type!r}", non_retryable=True
    )
