from collections.abc import Awaitable, Callable

from slack_sdk.errors import SlackApiError
from structlog import get_logger
from temporalio.exceptions import ApplicationError

from posthog.exceptions_capture import capture_exception
from posthog.models.integration import Integration
from posthog.sync import database_sync_to_async

from products.exports.backend.models.subscription import Subscription
from products.exports.backend.temporal.subscriptions.types import (
    DeliverSubscriptionInputs,
    DeliverSubscriptionResult,
    RecipientResult,
)

from ee.tasks.subscriptions import SLACK_USER_CONFIG_ERRORS, _capture_delivery_failed_event
from ee.tasks.subscriptions.auto_disable import (
    SLACK_DISCONNECTED_DISABLE_REASON,
    SLACK_PERMISSION_REVOKED_DISABLE_REASON,
    DisableReason,
    disable_invalid_subscription,
)
from ee.tasks.subscriptions.slack_subscriptions import SlackDeliveryResult, get_slack_integration_for_team

LOGGER = get_logger(__name__)


async def auto_disable_and_return(
    subscription: Subscription,
    reason: DisableReason,
    recipient_results: list[RecipientResult],
) -> DeliverSubscriptionResult:
    """Permanent-failure exit path: record per-recipient failure, capture analytics,
    and auto-disable the subscription. Shared by the insight/dashboard and AI delivery paths."""
    recipient_results.append(
        RecipientResult(
            recipient=subscription.target_value,
            status="failed",
            error={"message": reason.description, "type": reason.key},
        )
    )
    # `_capture_delivery_failed_event` only reads `str(e)` and `type(e).__name__`,
    # so a plain Exception conveys the same info without implying retry semantics.
    _capture_delivery_failed_event(subscription, Exception(reason.description))
    await database_sync_to_async(disable_invalid_subscription, thread_sensitive=False)(subscription, reason)
    return DeliverSubscriptionResult(recipient_results=recipient_results)


async def deliver_email(
    subscription: Subscription,
    inputs: DeliverSubscriptionInputs,
    recipient_results: list[RecipientResult],
    send_one: Callable[[str], Awaitable[None]],
) -> DeliverSubscriptionResult:
    """Send to each recipient via `send_one`. Partial success is kept; only an all-failed run
    raises, so a Temporal retry won't re-send to recipients who already succeeded."""
    emails = list(dict.fromkeys(e.strip() for e in subscription.target_value.split(",") if e.strip()))
    if inputs.is_new_subscription_target and inputs.previous_value is not None:
        previous = {e.strip() for e in inputs.previous_value.split(",") if e.strip()}
        emails = [e for e in emails if e not in previous]

    await LOGGER.ainfo(
        "deliver_subscription.sending_email", subscription_id=subscription.id, recipient_count=len(emails)
    )

    success_count = 0
    last_error: Exception | None = None
    for email in emails:
        try:
            await send_one(email)
            recipient_results.append(RecipientResult(recipient=email, status="success", error=None))
            success_count += 1
        except Exception as exc:
            LOGGER.error(
                "deliver_subscription.email_failed",
                subscription_id=subscription.id,
                email=email,
                next_delivery_date=subscription.next_delivery_date,
                destination=subscription.target_type,
                exc_info=True,
            )
            capture_exception(exc)
            _capture_delivery_failed_event(subscription, exc)
            recipient_results.append(
                RecipientResult(
                    recipient=email, status="failed", error={"message": str(exc), "type": type(exc).__name__}
                )
            )
            last_error = exc

    await LOGGER.ainfo(
        "deliver_subscription.email_complete",
        subscription_id=subscription.id,
        success_count=success_count,
        total_count=len(emails),
    )

    if last_error is not None and success_count == 0:
        raise last_error
    return DeliverSubscriptionResult(recipient_results=recipient_results)


def _resolve_slack_integration(subscription: Subscription) -> Integration | None:
    integration = subscription.integration
    if integration is not None and integration.kind != "slack":
        LOGGER.warning(
            "deliver_subscription.invalid_integration_kind",
            subscription_id=subscription.id,
            integration_id=integration.id,
            kind=integration.kind,
        )
        integration = None
    if integration is None:
        integration = get_slack_integration_for_team(subscription.team_id)
    return integration


async def deliver_slack(
    subscription: Subscription,
    recipient_results: list[RecipientResult],
    send: Callable[[Integration], Awaitable[SlackDeliveryResult]],
) -> DeliverSubscriptionResult:
    """A missing integration or a permanent Slack config error auto-disables the subscription;
    transient Slack errors raise so Temporal retries."""
    integration = await database_sync_to_async(_resolve_slack_integration, thread_sensitive=False)(subscription)
    if integration is None:
        LOGGER.warning("deliver_subscription.no_slack_integration", subscription_id=subscription.id)
        return await auto_disable_and_return(subscription, SLACK_DISCONNECTED_DISABLE_REASON, recipient_results)

    LOGGER.info("deliver_subscription.sending_slack_message", subscription_id=subscription.id)
    try:
        result = await send(integration)
    except ApplicationError:
        raise
    except Exception as exc:
        slack_error_code = exc.response.get("error") if isinstance(exc, SlackApiError) else None
        _capture_delivery_failed_event(subscription, exc)
        LOGGER.error(
            "deliver_subscription.slack_failed",
            subscription_id=subscription.id,
            slack_error=slack_error_code,
            next_delivery_date=subscription.next_delivery_date,
            destination=subscription.target_type,
            exc_info=True,
        )
        capture_exception(exc)
        if slack_error_code in SLACK_USER_CONFIG_ERRORS:
            # Won't self-heal without user action — auto-disable so it stops re-firing.
            return await auto_disable_and_return(
                subscription, SLACK_PERMISSION_REVOKED_DISABLE_REASON, recipient_results
            )
        raise  # Transient Slack errors — let Temporal retry

    if result.is_complete_success:
        await LOGGER.ainfo("deliver_subscription.slack_sent", subscription_id=subscription.id)
        recipient_results.append(RecipientResult(recipient=subscription.target_value, status="success", error=None))
    elif result.is_partial_failure:
        await LOGGER.awarning(
            "deliver_subscription.slack_partial_failure",
            subscription_id=subscription.id,
            failed_thread_count=len(result.failed_thread_message_indices),
            total_thread_count=result.total_thread_messages,
        )
        recipient_results.append(
            RecipientResult(
                recipient=subscription.target_value,
                status="partial",
                error={
                    "message": f"{len(result.failed_thread_message_indices)} thread message(s) failed",
                    "type": "partial_thread_failure",
                },
            )
        )
    return DeliverSubscriptionResult(recipient_results=recipient_results)
