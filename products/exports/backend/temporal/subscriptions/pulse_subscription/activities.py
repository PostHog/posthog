import uuid

import temporalio.activity
from structlog import get_logger
from temporalio.exceptions import ApplicationError

from posthog.sync import database_sync_to_async

from products.exports.backend.models.subscription import Subscription, SubscriptionDelivery
from products.exports.backend.temporal.subscriptions.delivery_common import (
    auto_disable_and_return,
    deliver_email,
    deliver_slack,
)
from products.exports.backend.temporal.subscriptions.pulse_subscription.delivery import (
    QUIET_BRIEF_NOTE,
    render_brief_markdown,
    send_email_pulse_brief,
    send_slack_pulse_brief,
)
from products.exports.backend.temporal.subscriptions.types import (
    DeliverSubscriptionInputs,
    DeliverSubscriptionResult,
    MarkPulseBriefSkippedInputs,
    PreparePulseBriefInputs,
    PreparePulseBriefResult,
    RecipientResult,
    RenderPulseBriefInputs,
    RenderPulseBriefResult,
)
from products.pulse.backend.models import BriefConfig, ProductBrief

from ee.tasks.subscriptions.auto_disable import AI_CONSENT_REVOKED_DISABLE_REASON, PULSE_BRIEF_INVALID_DISABLE_REASON

LOGGER = get_logger(__name__)

# `SubscriptionDelivery.content_snapshot` keys. The brief id makes prepare idempotent across
# activity retries (no duplicate ProductBrief rows); the rendered markdown travels through
# Postgres by reference rather than on the Temporal wire (~2 MiB cap) — the same pattern the
# AI report uses.
PULSE_BRIEF_ID_SNAPSHOT_KEY = "pulse_brief_id"
PULSE_BRIEF_REPORT_SNAPSHOT_KEY = "pulse_brief_report"

# Error recorded on a brief whose generation was skipped because another run (e.g. an
# on-demand generation) already held the per-team+config single-flight lock.
GENERATION_ALREADY_RUNNING_ERROR = "Skipped: a brief generation for this config was already running"


async def _read_snapshot_value(delivery_id: uuid.UUID, key: str) -> str | None:
    @database_sync_to_async(thread_sensitive=False)
    def _read() -> str | None:
        try:
            snapshot = SubscriptionDelivery.objects.values_list("content_snapshot", flat=True).get(pk=delivery_id)
        except SubscriptionDelivery.DoesNotExist:
            return None
        if not isinstance(snapshot, dict):
            return None
        value = snapshot.get(key)
        return value if isinstance(value, str) and value else None

    return await _read()


async def _write_snapshot_value(delivery_id: uuid.UUID, key: str, value: str) -> None:
    @database_sync_to_async(thread_sensitive=False)
    def _write() -> None:
        # No DoesNotExist guard: create_delivery_record always writes this row first,
        # so a missing row is a wiring bug — let it raise loudly.
        delivery = SubscriptionDelivery.objects.get(pk=delivery_id)
        delivery.content_snapshot = {**(delivery.content_snapshot or {}), key: value}
        delivery.save(update_fields=["content_snapshot", "last_updated_at"])

    await _write()


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

    period_days = subscription.ai_report_window_days
    result = PreparePulseBriefResult(config_id=str(config.id), team_id=team_id, period_days=period_days)

    # Idempotency on Temporal redispatch: a prior attempt already created the brief row.
    existing_brief_id = await _read_snapshot_value(inputs.delivery_id, PULSE_BRIEF_ID_SNAPSHOT_KEY)
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
    await _write_snapshot_value(inputs.delivery_id, PULSE_BRIEF_ID_SNAPSHOT_KEY, str(brief.id))
    result.brief_id = str(brief.id)
    await LOGGER.ainfo("prepare_pulse_brief.brief_created", subscription_id=subscription.id, brief_id=result.brief_id)
    return result


@temporalio.activity.defn
async def mark_pulse_brief_generation_skipped(inputs: MarkPulseBriefSkippedInputs) -> None:
    """A concurrent generation held the single-flight lock, so this run's brief row will never
    be filled — mark it FAILED (visible in-app) instead of stranding it in GENERATING. The
    status filter keeps this from clobbering a brief the concurrent run already completed."""

    @database_sync_to_async(thread_sensitive=False)
    def _mark() -> None:
        ProductBrief.objects.for_team(inputs.team_id).filter(
            id=inputs.brief_id, status=ProductBrief.Status.GENERATING
        ).update(status=ProductBrief.Status.FAILED, error=GENERATION_ALREADY_RUNNING_ERROR)

    await _mark()


@temporalio.activity.defn
async def render_pulse_brief_for_delivery(inputs: RenderPulseBriefInputs) -> RenderPulseBriefResult:
    """Post-generation phase: turn the brief into deliverable markdown. READY → full sections;
    QUIET → the one-line quiet note (spec §7); FAILED/GENERATING → not deliverable."""
    brief = await database_sync_to_async(
        lambda: ProductBrief.objects.for_team(inputs.team_id).get(id=inputs.brief_id),
        thread_sensitive=False,
    )()

    if brief.status == ProductBrief.Status.READY:
        markdown = render_brief_markdown(brief)
    elif brief.status == ProductBrief.Status.QUIET:
        markdown = QUIET_BRIEF_NOTE
    else:
        LOGGER.warning(
            "render_pulse_brief.not_deliverable",
            subscription_id=inputs.subscription_id,
            brief_id=inputs.brief_id,
            status=brief.status,
        )
        return RenderPulseBriefResult(deliverable=False, brief_status=brief.status)

    await _write_snapshot_value(inputs.delivery_id, PULSE_BRIEF_REPORT_SNAPSHOT_KEY, markdown)
    return RenderPulseBriefResult(deliverable=True, brief_status=brief.status)


async def _deliver_pulse_subscription(
    subscription: Subscription,
    inputs: DeliverSubscriptionInputs,
    recipient_results: list[RecipientResult],
) -> DeliverSubscriptionResult:
    # Ships the markdown render_pulse_brief_for_delivery already persisted (read back from the
    # delivery row). Transient send errors retry; terminal Slack errors auto-disable.
    if inputs.delivery_id is None:
        # The pulse workflow always creates the delivery row and renders before delivery,
        # so a missing reference is a wiring bug, not a runtime state.
        raise ApplicationError(
            f"Pulse delivery for subscription {subscription.id} has no delivery_id", non_retryable=True
        )

    markdown = await _read_snapshot_value(inputs.delivery_id, PULSE_BRIEF_REPORT_SNAPSHOT_KEY)
    if markdown is None:
        # Rendering persists the markdown before delivery is scheduled; re-running delivery
        # can't regenerate it, so retrying just burns attempts — fail loud.
        raise ApplicationError(
            f"Pulse brief report missing for subscription {subscription.id} (delivery {inputs.delivery_id})",
            non_retryable=True,
        )

    if subscription.target_type == Subscription.SubscriptionTarget.EMAIL:
        # Dedup key for MessagingRecord: stable across this run's retries, unique per run.
        workflow_run_id = temporalio.activity.info().workflow_run_id
        if workflow_run_id is None:
            raise ApplicationError("Pulse email delivery requires a workflow run id", non_retryable=True)

        async def _send_email(email: str) -> None:
            await database_sync_to_async(send_email_pulse_brief, thread_sensitive=False)(
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
            lambda integration: send_slack_pulse_brief(
                subscription=subscription, markdown=markdown, integration=integration
            ),
        )
    # `validate_subscription_for_delivery` auto-disables unsupported targets up front,
    # so reaching here means an invariant was violated.
    raise ApplicationError(
        f"Pulse delivery reached an unsupported target {subscription.target_type!r}", non_retryable=True
    )
