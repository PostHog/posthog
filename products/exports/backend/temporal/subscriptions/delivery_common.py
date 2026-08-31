import uuid
import dataclasses
from collections.abc import Awaitable, Callable
from typing import Any, cast

from django.db import transaction

from slack_sdk.errors import SlackApiError
from structlog import get_logger
from temporalio.exceptions import ApplicationError

from posthog.email import EmailDeliveryError
from posthog.exceptions_capture import capture_exception
from posthog.models.integration import Integration
from posthog.sync import database_sync_to_async

from products.exports.backend.models.subscription import Subscription, SubscriptionDelivery
from products.exports.backend.temporal.subscriptions.types import (
    DeliverSubscriptionInputs,
    DeliverSubscriptionResult,
    RecipientResult,
    RecipientResultStatus,
)

from ee.tasks.subscriptions import SLACK_GALLERY_CONFIG_ERRORS, SLACK_USER_CONFIG_ERRORS, _capture_delivery_failed_event
from ee.tasks.subscriptions.auto_disable import (
    SLACK_DISCONNECTED_DISABLE_REASON,
    SLACK_FILE_UPLOAD_PERMISSION_REVOKED_DISABLE_REASON,
    SLACK_FILE_UPLOAD_UNAVAILABLE_DISABLE_REASON,
    SLACK_PERMISSION_REVOKED_DISABLE_REASON,
    DisableReason,
    disable_invalid_subscription,
    mark_subscription_disabled,
    notify_subscription_disabled,
)
from ee.tasks.subscriptions.slack_subscriptions import SlackDeliveryResult, get_slack_integration_for_team

LOGGER = get_logger(__name__)

# Cap recipient_results echoed into an ApplicationError's details — Temporal serializes error
# details into history events capped at the gRPC payload limit, and an oversized non-retryable
# error can't be recorded, leaving the workflow unable to complete its failing task.
_MAX_ERROR_DETAIL_RESULTS = 50


def persist_auto_disable_result_and_disable(
    delivery_id: uuid.UUID,
    subscription: Subscription,
    reason: DisableReason,
    recipient_results: list[RecipientResult],
) -> bool:
    with transaction.atomic():
        updated = SubscriptionDelivery.objects.filter(id=delivery_id, subscription_id=subscription.id).update(
            recipient_results=[dataclasses.asdict(result) for result in recipient_results]
        )
        if updated != 1:
            raise RuntimeError(f"Subscription delivery {delivery_id} was not found")
        return mark_subscription_disabled(subscription, reason)


def load_persisted_recipient_results(delivery_id: uuid.UUID, subscription_id: int) -> list[RecipientResult]:
    raw_results = (
        SubscriptionDelivery.objects.filter(
            id=delivery_id,
            subscription_id=subscription_id,
        )
        .values_list("recipient_results", flat=True)
        .get()
    )
    results: list[RecipientResult] = []
    if not isinstance(raw_results, list):
        return results
    for raw_result in raw_results:
        if not isinstance(raw_result, dict):
            continue
        recipient = raw_result.get("recipient")
        status = raw_result.get("status")
        if not isinstance(recipient, str) or status not in {"success", "failed", "partial"}:
            continue
        error = raw_result.get("error")
        human_readable_error = raw_result.get("human_readable_error")
        results.append(
            RecipientResult(
                recipient=recipient,
                status=cast(RecipientResultStatus, status),
                error=error if isinstance(error, dict) else None,
                human_readable_error=human_readable_error if isinstance(human_readable_error, str) else None,
            )
        )
    return results


def _is_gallery_delivery(delivery_id: uuid.UUID, subscription_id: int) -> bool:
    return SubscriptionDelivery.objects.filter(
        id=delivery_id,
        subscription_id=subscription_id,
        slack_delivery_mode=SubscriptionDelivery.SlackDeliveryMode.GALLERY,
    ).exists()


def strip_null_bytes(value: Any) -> Any:
    """Recursively remove NUL (\\x00) from strings — Postgres text/jsonb columns cannot store it.

    Anything written to ``SubscriptionDelivery.content_snapshot`` that originates outside a Postgres
    text column (ClickHouse query results, LLM output, user-supplied prompts) must pass through this
    first, or the NUL surfaces as a unicode escape that fails the whole delivery write with a DataError.
    """
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [strip_null_bytes(v) for v in value]
    if isinstance(value, tuple):
        return tuple(strip_null_bytes(v) for v in value)
    if isinstance(value, dict):
        # Strip keys too: a Map(String, …) column can produce data-derived keys carrying NUL,
        # and Postgres rejects it in a jsonb key just as it does in a value.
        return {strip_null_bytes(k): strip_null_bytes(v) for k, v in value.items()}
    return value


async def auto_disable_and_return(
    subscription: Subscription,
    reason: DisableReason,
    recipient_results: list[RecipientResult],
    delivery_id: uuid.UUID | None = None,
) -> DeliverSubscriptionResult:
    """Permanent-failure exit path: record per-recipient failure, capture analytics,
    and auto-disable the subscription. Shared by the insight/dashboard and AI delivery paths."""
    recipient_results.append(
        RecipientResult(
            recipient=subscription.target_value,
            status="failed",
            error={"message": reason.description, "type": reason.key},
            human_readable_error=reason.description,
        )
    )
    if delivery_id is not None:
        just_disabled = await database_sync_to_async(persist_auto_disable_result_and_disable, thread_sensitive=False)(
            delivery_id,
            subscription,
            reason,
            recipient_results,
        )
        if just_disabled:
            await database_sync_to_async(notify_subscription_disabled, thread_sensitive=False)(subscription, reason)
    else:
        await database_sync_to_async(disable_invalid_subscription, thread_sensitive=False)(subscription, reason)
    # `_capture_delivery_failed_event` only reads `str(e)` and `type(e).__name__`,
    # so a plain Exception conveys the same info without implying retry semantics.
    _capture_delivery_failed_event(subscription, Exception(reason.description))
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
    previous_target_value = inputs.previous_target_value
    if previous_target_value is None:
        previous_target_value = inputs.previous_value
    send_only_to_new_recipients = (
        inputs.is_new_subscription_target
        if inputs.is_new_subscription_target is not None
        else previous_target_value is not None and previous_target_value != subscription.target_value
    )
    if send_only_to_new_recipients:
        previous = {e.strip() for e in (previous_target_value or "").split(",") if e.strip()}
        emails = [e for e in emails if e not in previous]

    await LOGGER.ainfo(
        "deliver_subscription.sending_email", subscription_id=subscription.id, recipient_count=len(emails)
    )

    success_count = 0
    failures: list[tuple[str, Exception]] = []
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
                    recipient=email,
                    status="failed",
                    error={"message": str(exc), "type": type(exc).__name__},
                    human_readable_error=None,
                )
            )
            failures.append((email, exc))

    await LOGGER.ainfo(
        "deliver_subscription.email_complete",
        subscription_id=subscription.id,
        success_count=success_count,
        total_count=len(emails),
    )

    if failures and success_count == 0:
        # Whole batch failed. Retryability is decided per recipient, not by which error
        # happened to be last: any transient failure means a retry must run so those
        # recipients get another attempt (dedupe skips the already-delivered ones). Only
        # when every recipient hit a permanent rejection (EmailDeliveryError) is the batch
        # non-retryable — retrying then could never succeed.
        # Bound the error details: a huge recipient list with a domain-wide bounce would
        # otherwise exceed Temporal's gRPC payload cap and wedge the workflow mid-failure.
        details: list[dict[str, Any]] = [
            {
                "recipient": result.recipient,
                "status": result.status,
                **({"error": result.error} if result.error else {}),
            }
            for result in recipient_results[:_MAX_ERROR_DETAIL_RESULTS]
        ]
        if len(recipient_results) > _MAX_ERROR_DETAIL_RESULTS:
            details.append({"truncated_count": len(recipient_results) - _MAX_ERROR_DETAIL_RESULTS})
        permanent = [err for _, err in failures if isinstance(err, EmailDeliveryError)]
        if permanent and len(permanent) == len(failures):
            raise ApplicationError(
                f"all {len(failures)} recipients permanently rejected delivery",
                {"recipient_results": details},
                non_retryable=True,
            ) from permanent[0]
        # Mixed or all-transient: re-raise a retryable error so Temporal retries the batch.
        raise next(err for _, err in failures if not isinstance(err, EmailDeliveryError))
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
    delivery_id: uuid.UUID | None = None,
) -> DeliverSubscriptionResult:
    """A missing integration or a permanent Slack config error auto-disables the subscription;
    transient Slack errors raise so Temporal retries."""
    integration = await database_sync_to_async(_resolve_slack_integration, thread_sensitive=False)(subscription)
    if integration is None:
        LOGGER.warning("deliver_subscription.no_slack_integration", subscription_id=subscription.id)
        return await auto_disable_and_return(
            subscription,
            SLACK_DISCONNECTED_DISABLE_REASON,
            recipient_results,
            delivery_id,
        )

    gallery_delivery = False
    if delivery_id is not None:
        # Resolve this before the first Slack side effect. If the database read fails,
        # Temporal can retry safely without crossing the gallery claim boundary.
        gallery_delivery = await database_sync_to_async(
            _is_gallery_delivery,
            thread_sensitive=False,
        )(delivery_id, subscription.id)

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
        needed_scopes = (
            {scope.strip() for scope in str(exc.response.get("needed") or "").split(",") if scope.strip()}
            if isinstance(exc, SlackApiError)
            else set()
        )
        file_upload_permission_missing = slack_error_code in {"missing_scope", "not_allowed_token_type"} and (
            "files:write" in needed_scopes if needed_scopes else gallery_delivery
        )
        if file_upload_permission_missing:
            return await auto_disable_and_return(
                subscription,
                SLACK_FILE_UPLOAD_PERMISSION_REVOKED_DISABLE_REASON,
                recipient_results,
                delivery_id,
            )
        if slack_error_code in SLACK_USER_CONFIG_ERRORS:
            # Won't self-heal without user action — auto-disable so it stops re-firing.
            return await auto_disable_and_return(
                subscription,
                SLACK_PERMISSION_REVOKED_DISABLE_REASON,
                recipient_results,
                delivery_id,
            )
        if slack_error_code in SLACK_GALLERY_CONFIG_ERRORS:
            return await auto_disable_and_return(
                subscription,
                SLACK_FILE_UPLOAD_UNAVAILABLE_DISABLE_REASON,
                recipient_results,
                delivery_id,
            )
        raise  # Transient Slack errors — let Temporal retry

    if result.is_complete_success:
        await LOGGER.ainfo("deliver_subscription.slack_sent", subscription_id=subscription.id)
        recipient_results.append(RecipientResult(recipient=subscription.target_value, status="success", error=None))
    elif result.is_partial_failure:
        failed_thread_count = len(result.failed_thread_message_indices)
        await LOGGER.awarning(
            "deliver_subscription.slack_partial_failure",
            subscription_id=subscription.id,
            failed_thread_count=failed_thread_count,
            total_thread_count=result.total_thread_messages,
            omitted_attachment_count=result.omitted_attachment_count,
        )
        partial_reasons = []
        if failed_thread_count:
            partial_reasons.append(
                f"{failed_thread_count} thread message{'s' if failed_thread_count != 1 else ''} failed"
            )
        if result.omitted_attachment_count:
            partial_reasons.append(
                f"{result.omitted_attachment_count} image{'s' if result.omitted_attachment_count != 1 else ''} could not be attached"
            )
        partial_message = "; ".join(partial_reasons)
        if failed_thread_count and result.omitted_attachment_count:
            partial_error_type = "partial_slack_failure"
        elif failed_thread_count:
            partial_error_type = "partial_thread_failure"
        else:
            partial_error_type = "partial_attachment_failure"
        recipient_results.append(
            RecipientResult(
                recipient=subscription.target_value,
                status="partial",
                error={"message": partial_message, "type": partial_error_type},
                human_readable_error=partial_message,
            )
        )
    elif result.is_complete_failure:
        failure_message = result.failure_message or "Slack could not confirm whether the gallery was delivered."
        failure_type = result.failure_type or "slack_delivery_unconfirmed"
        await LOGGER.aerror(
            "deliver_subscription.slack_delivery_failed",
            subscription_id=subscription.id,
            failure_type=failure_type,
        )
        _capture_delivery_failed_event(subscription, Exception(failure_message))
        recipient_results.append(
            RecipientResult(
                recipient=subscription.target_value,
                status="failed",
                error={"message": failure_message, "type": failure_type},
                human_readable_error=failure_message,
            )
        )
    return DeliverSubscriptionResult(recipient_results=recipient_results)
