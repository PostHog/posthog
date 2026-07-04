import uuid

import temporalio.activity
from structlog import get_logger
from temporalio.exceptions import ApplicationError

from posthog.models.integration import Integration
from posthog.sync import database_sync_to_async

from products.exports.backend.models.subscription import Subscription
from products.exports.backend.temporal.subscriptions.delivery_common import (
    auto_disable_and_return,
    deliver_markdown_subscription,
    read_delivery_snapshot_value,
    write_delivery_snapshot_values,
)
from products.exports.backend.temporal.subscriptions.pulse_subscription.delivery import (
    QUIET_BRIEF_NOTE,
    render_brief_markdown,
    send_email_pulse_brief,
    send_slack_pulse_brief,
)
from products.exports.backend.temporal.subscriptions.types import (
    CleanupSkippedPulseBriefInputs,
    DeliverSubscriptionInputs,
    DeliverSubscriptionResult,
    PreparePulseBriefInputs,
    PreparePulseBriefResult,
    RecipientResult,
    RenderPulseBriefInputs,
)
from products.pulse.backend.models import BriefConfig, ProductBrief

from ee.tasks.subscriptions.auto_disable import AI_CONSENT_REVOKED_DISABLE_REASON, PULSE_BRIEF_INVALID_DISABLE_REASON
from ee.tasks.subscriptions.slack_subscriptions import SlackDeliveryResult

LOGGER = get_logger(__name__)

# `SubscriptionDelivery.content_snapshot` keys. The brief id makes prepare idempotent across
# activity retries (no duplicate ProductBrief rows); the rendered markdown travels through
# Postgres by reference rather than on the Temporal wire (~2 MiB cap) — the same pattern the
# AI report uses.
PULSE_BRIEF_ID_SNAPSHOT_KEY = "pulse_brief_id"
PULSE_BRIEF_REPORT_SNAPSHOT_KEY = "pulse_brief_report"


@temporalio.activity.defn
async def prepare_pulse_brief_subscription(inputs: PreparePulseBriefInputs) -> PreparePulseBriefResult:
    """Pre-generation phase: re-check the terminal gates (consent, config, creator) and create
    the ProductBrief row the generate workflow will fill. Terminal failures auto-disable the
    subscription and return aborted=True; transient errors bubble up for the Temporal retry."""
    subscription = await database_sync_to_async(
        Subscription.objects.select_related("created_by", "team", "team__organization").get,
        thread_sensitive=False,
    )(pk=inputs.subscription_id)
    team_id = subscription.team_id

    # Consent is gated here before any generation cost, mirroring the AI-prompt path —
    # creation-time gates don't catch an org that revokes AI-data-processing approval later.
    # The generate workflow re-checks too; checking here auto-disables so it stops re-firing.
    if not subscription.team.organization.is_ai_data_processing_approved:
        LOGGER.warning("prepare_pulse_brief.consent_revoked", subscription_id=subscription.id)
        aborted = await auto_disable_and_return(subscription, AI_CONSENT_REVOKED_DISABLE_REASON, [])
        return PreparePulseBriefResult(aborted=True, recipient_results=aborted.recipient_results)

    config = await database_sync_to_async(
        lambda: BriefConfig.objects.for_team(team_id).filter(id=subscription.pulse_brief_config_id).first(),
        thread_sensitive=False,
    )()
    if config is None or not config.enabled or subscription.created_by is None:
        # Structurally permanent: the config was deleted/disabled after subscribing, or the
        # creator (needed for LLM attribution in generation) is gone. Re-firing can't succeed.
        LOGGER.warning(
            "prepare_pulse_brief.invalid_config_or_creator",
            subscription_id=subscription.id,
            config_id=str(subscription.pulse_brief_config_id),
            config_found=config is not None,
            has_creator=subscription.created_by is not None,
        )
        aborted = await auto_disable_and_return(subscription, PULSE_BRIEF_INVALID_DISABLE_REASON, [])
        return PreparePulseBriefResult(aborted=True, recipient_results=aborted.recipient_results)

    period_days = subscription.report_window_days
    result = PreparePulseBriefResult(config_id=str(config.id), period_days=period_days)

    # Idempotency on Temporal redispatch: a prior attempt already created the brief row.
    existing_brief_id = await read_delivery_snapshot_value(inputs.delivery_id, PULSE_BRIEF_ID_SNAPSHOT_KEY)
    if existing_brief_id is not None:
        await LOGGER.ainfo("prepare_pulse_brief.already_prepared", subscription_id=subscription.id)
        result.brief_id = existing_brief_id
        return result

    brief = await database_sync_to_async(
        lambda: ProductBrief.objects.for_team(team_id).create(
            team_id=team_id,
            config=config,
            created_by=subscription.created_by,
            status=ProductBrief.Status.GENERATING,
            trigger=ProductBrief.Trigger.SCHEDULED,
            period_days=period_days,
        ),
        thread_sensitive=False,
    )()
    await write_delivery_snapshot_values(inputs.delivery_id, {PULSE_BRIEF_ID_SNAPSHOT_KEY: str(brief.id)})
    result.brief_id = str(brief.id)
    await LOGGER.ainfo("prepare_pulse_brief.brief_created", subscription_id=subscription.id, brief_id=result.brief_id)
    return result


@temporalio.activity.defn
async def cleanup_skipped_pulse_brief(inputs: CleanupSkippedPulseBriefInputs) -> None:
    """A concurrent generation held the single-flight lock, so this run's brief row will never
    be filled — delete it, the same collision policy as the on-demand API path
    (products/pulse/backend/api/brief.py). The delivery row records SKIPPED for the audit
    trail. The status filter keeps this from deleting a brief the concurrent run completed."""

    @database_sync_to_async(thread_sensitive=False)
    def _delete() -> None:
        ProductBrief.objects.for_team(inputs.team_id).filter(
            id=inputs.brief_id, status=ProductBrief.Status.GENERATING
        ).delete()

    await _delete()


@temporalio.activity.defn
async def render_pulse_brief_for_delivery(inputs: RenderPulseBriefInputs) -> None:
    """Post-generation phase: turn the brief into deliverable markdown. READY → full sections;
    QUIET → the one-line quiet note (spec §7). Anything else is an invariant break — the
    generate child workflow either completes the brief or fails the run."""
    brief = await database_sync_to_async(
        lambda: ProductBrief.objects.for_team(inputs.team_id).get(id=inputs.brief_id),
        thread_sensitive=False,
    )()

    if brief.status == ProductBrief.Status.READY:
        markdown = render_brief_markdown(brief)
    elif brief.status == ProductBrief.Status.QUIET:
        markdown = QUIET_BRIEF_NOTE
    else:
        raise ApplicationError(
            f"Brief {inputs.brief_id} is not deliverable (status: {brief.status})", non_retryable=True
        )

    await write_delivery_snapshot_values(inputs.delivery_id, {PULSE_BRIEF_REPORT_SNAPSHOT_KEY: markdown})


async def deliver_pulse_subscription(
    subscription: Subscription,
    inputs: DeliverSubscriptionInputs,
    recipient_results: list[RecipientResult],
) -> DeliverSubscriptionResult:
    # Ships the markdown render_pulse_brief_for_delivery already persisted.

    async def _send_email(email: str, markdown: str, delivery_run_id: str, _delivery_id: uuid.UUID) -> None:
        await database_sync_to_async(send_email_pulse_brief, thread_sensitive=False)(
            email=email,
            subscription=subscription,
            markdown=markdown,
            delivery_run_id=delivery_run_id,
        )

    async def _send_slack(integration: Integration, markdown: str, _delivery_id: uuid.UUID) -> SlackDeliveryResult:
        return await send_slack_pulse_brief(subscription=subscription, markdown=markdown, integration=integration)

    return await deliver_markdown_subscription(
        subscription,
        inputs,
        recipient_results,
        snapshot_key=PULSE_BRIEF_REPORT_SNAPSHOT_KEY,
        kind_label="Pulse brief",
        send_email=_send_email,
        send_slack=_send_slack,
    )
