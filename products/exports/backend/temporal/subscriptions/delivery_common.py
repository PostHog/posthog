import asyncio
import functools
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, NoReturn
from urllib.parse import urlparse

import requests
from slack_sdk.errors import SlackApiError
from structlog import get_logger
from temporalio.exceptions import ApplicationError

from posthog.email import EmailDeliveryError
from posthog.exceptions_capture import capture_exception
from posthog.models.integration import Integration
from posthog.security.pinned_requests import SSRFBlockedError, pinned_session
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
    WEBHOOK_REJECTED_DISABLE_REASON,
    DisableReason,
    disable_invalid_subscription,
)
from ee.tasks.subscriptions.slack_subscriptions import SlackDeliveryResult, get_slack_integration_for_team

LOGGER = get_logger(__name__)

# Cap recipient_results echoed into an ApplicationError's details — Temporal serializes error
# details into history events capped at the gRPC payload limit, and an oversized non-retryable
# error can't be recorded, leaving the workflow unable to complete its failing task.
_MAX_ERROR_DETAIL_RESULTS = 50

# Connect and read timeouts for a webhook POST. Power Automate acknowledges quickly, so a read
# that runs long means the flow is stuck rather than slow.
_WEBHOOK_TIMEOUT_SECONDS = (5.0, 30.0)
# What a deleted or revoked Power Automate flow answers with. Retrying cannot recover any of them.
_PERMANENT_WEBHOOK_STATUSES = frozenset({403, 404, 410})
_WEBHOOK_UNREACHABLE_MESSAGE = (
    "We couldn't reach the destination URL. PostHog will try again on the next scheduled run."
)
# Webhook sends get their own small pool rather than the event loop's default executor, which also
# serves every database_sync_to_async call and every async log line in this worker. `requests`
# applies its read timeout per socket read, so a destination that trickles bytes holds its thread
# for as long as it likes, and Temporal's start_to_close_timeout cancels the await rather than the
# thread. Confining that to a few threads keeps one stuck destination away from the deliveries
# running beside it.
_WEBHOOK_SEND_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="subscription-webhook")


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


def _error_detail_results(recipient_results: list[RecipientResult]) -> list[dict[str, Any]]:
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
    return details


def recipient_label(subscription: Subscription) -> str:
    """How this subscription's destination is named everywhere outside its own ``target_value``:
    ``RecipientResult.recipient`` and the ``SubscriptionDelivery.target_value`` snapshot, both of
    which the API returns. A webhook URL is a bearer credential for the destination channel, so
    only its host is recorded."""
    if subscription.target_type not in Subscription.SubscriptionTarget.webhook_targets():
        return subscription.target_value
    try:
        host = (urlparse(subscription.target_value).hostname or "").lower()
    except ValueError:
        host = ""
    return host or "webhook"


def _fail_webhook_delivery(
    subscription: Subscription,
    recipient_results: list[RecipientResult],
    *,
    recipient: str,
    message: str,
    error_type: str,
    human_readable_error: str,
    non_retryable: bool,
) -> NoReturn:
    recipient_results.append(
        RecipientResult(
            recipient=recipient,
            status="failed",
            error={"message": message, "type": error_type},
            human_readable_error=human_readable_error,
        )
    )
    _capture_delivery_failed_event(subscription, Exception(message))
    # `from None` keeps the originating exception out of the Temporal failure chain: a `requests`
    # error carries the full webhook URL in its text, and that URL is a credential.
    raise ApplicationError(
        message, {"recipient_results": _error_detail_results(recipient_results)}, non_retryable=non_retryable
    ) from None


def _post_webhook(url: str, body: dict[str, Any]) -> int:
    """POST the payload and return the status code, without reading the response body.

    `pinned_session` re-validates the URL and pins the connection to the IPs it resolved, which is
    what closes the DNS-rebinding window, so this path must never fall back to plain `requests`.
    `stream=True` keeps an untrusted destination from making us download a response of any size we
    would only throw away.
    """
    with pinned_session(url) as session:
        response = session.request(
            "POST", url, json=body, timeout=_WEBHOOK_TIMEOUT_SECONDS, allow_redirects=False, stream=True
        )
        try:
            return response.status_code
        finally:
            response.close()


async def deliver_webhook(
    subscription: Subscription,
    recipient_results: list[RecipientResult],
    *,
    body: dict[str, Any],
) -> DeliverSubscriptionResult:
    """POST an already-built payload to the subscription's user-supplied webhook URL.

    Knows nothing about what the payload means. Neither the URL nor an exception carrying it is
    logged, captured, or put in a delivery receipt.
    """
    url = subscription.target_value
    recipient = recipient_label(subscription)
    LOGGER.info("deliver_subscription.sending_webhook", subscription_id=subscription.id, recipient=recipient)

    try:
        # The send is synchronous and resolves DNS, so it cannot run on the event loop.
        status = await asyncio.get_running_loop().run_in_executor(
            _WEBHOOK_SEND_EXECUTOR, functools.partial(_post_webhook, url, body)
        )
    except (SSRFBlockedError, requests.RequestException) as exc:
        # Retryable rather than permanent even when the URL was blocked, because the likely cause is
        # a failed name resolution. Callers validate the host on save, so a URL that can never work
        # does not reach here.
        if isinstance(exc, SSRFBlockedError):
            event = "deliver_subscription.webhook_url_blocked"
            error_type = "webhook_url_blocked"
            message = f"Webhook URL failed validation: {exc}"
        else:
            event = "deliver_subscription.webhook_request_failed"
            error_type = "webhook_request_failed"
            message = f"Webhook request failed: {type(exc).__name__}"
        # No exc_info anywhere in this function: a traceback would render the exception text, and a
        # `requests` error carries the full webhook URL in it.
        LOGGER.error(  # noqa: TRY400
            event,
            subscription_id=subscription.id,
            recipient=recipient,
            reason=message,
        )
        _fail_webhook_delivery(
            subscription,
            recipient_results,
            recipient=recipient,
            message=message,
            error_type=error_type,
            human_readable_error=_WEBHOOK_UNREACHABLE_MESSAGE,
            non_retryable=False,
        )

    # Any 2xx counts: Power Automate answers 202 on a webhook it accepted for processing.
    if 200 <= status < 300:
        await LOGGER.ainfo(
            "deliver_subscription.webhook_sent",
            subscription_id=subscription.id,
            recipient=recipient,
            status=status,
        )
        recipient_results.append(RecipientResult(recipient=recipient, status="success", error=None))
        return DeliverSubscriptionResult(recipient_results=recipient_results)

    LOGGER.error(
        "deliver_subscription.webhook_rejected",
        subscription_id=subscription.id,
        recipient=recipient,
        status=status,
        next_delivery_date=subscription.next_delivery_date,
        destination=subscription.target_type,
    )
    if status in _PERMANENT_WEBHOOK_STATUSES:
        return await auto_disable_and_return(subscription, WEBHOOK_REJECTED_DISABLE_REASON, recipient_results)

    _fail_webhook_delivery(
        subscription,
        recipient_results,
        recipient=recipient,
        message=f"Webhook destination returned HTTP {status}",
        error_type="webhook_http_error",
        human_readable_error=f"The destination returned an error (HTTP {status}).",
        non_retryable=not (status == 429 or status >= 500),
    )


async def auto_disable_and_return(
    subscription: Subscription,
    reason: DisableReason,
    recipient_results: list[RecipientResult],
) -> DeliverSubscriptionResult:
    """Permanent-failure exit path: record per-recipient failure, capture analytics,
    and auto-disable the subscription. Shared by the insight/dashboard and AI delivery paths."""
    recipient_results.append(
        RecipientResult(
            recipient=recipient_label(subscription),
            status="failed",
            error={"message": reason.description, "type": reason.key},
            human_readable_error=reason.description,
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
        details = _error_detail_results(recipient_results)
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
        recipient_results.append(RecipientResult(recipient=recipient_label(subscription), status="success", error=None))
    elif result.is_partial_failure:
        await LOGGER.awarning(
            "deliver_subscription.slack_partial_failure",
            subscription_id=subscription.id,
            failed_thread_count=len(result.failed_thread_message_indices),
            total_thread_count=result.total_thread_messages,
        )
        failed_count = len(result.failed_thread_message_indices)
        partial_message = f"{failed_count} thread message{'s' if failed_count != 1 else ''} failed"
        recipient_results.append(
            RecipientResult(
                recipient=recipient_label(subscription),
                status="partial",
                error={"message": partial_message, "type": "partial_thread_failure"},
                human_readable_error=partial_message,
            )
        )
    return DeliverSubscriptionResult(recipient_results=recipient_results)
