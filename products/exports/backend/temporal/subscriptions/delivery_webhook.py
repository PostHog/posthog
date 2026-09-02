import os
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore
from typing import Any, NoReturn

import requests
from structlog import get_logger
from temporalio.exceptions import ApplicationError

from posthog.security.pinned_requests import SSRFBlockedError, pinned_session
from posthog.security.url_validation import is_microsoft_teams_webhook_url
from posthog.settings.utils import get_from_env

from products.exports.backend.models.subscription import Subscription
from products.exports.backend.temporal.subscriptions.delivery_common import (
    auto_disable_and_return,
    error_detail_results,
)
from products.exports.backend.temporal.subscriptions.retry_policy import SUBSCRIPTION_DELIVER_ATTEMPT_TIMEOUT
from products.exports.backend.temporal.subscriptions.types import DeliverSubscriptionResult, RecipientResult

from ee.tasks.subscriptions import _capture_delivery_failed_event
from ee.tasks.subscriptions.auto_disable import WEBHOOK_REJECTED_DISABLE_REASON

LOGGER = get_logger(__name__)

WEBHOOK_CONNECT_TIMEOUT_SECONDS = 5.0
# A webhook accepts no idempotency key, so a send still in flight when Temporal gives up on the
# activity and retries it posts the card to the channel a second time. Taking a tenth of the
# attempt budget keeps a stuck send failing inside the activity whichever way that budget moves.
WEBHOOK_READ_TIMEOUT_SECONDS = SUBSCRIPTION_DELIVER_ATTEMPT_TIMEOUT.total_seconds() / 10

# What a deleted or revoked Power Automate flow answers with. Retrying cannot recover any of them.
_PERMANENT_WEBHOOK_STATUSES = frozenset({403, 404, 410})
_WEBHOOK_UNREACHABLE_MESSAGE = "We couldn't reach your Teams channel. PostHog will try again on the next scheduled run."

_WEBHOOK_SEND_MAX_WORKERS: int = get_from_env(
    "SUBSCRIPTION_WEBHOOK_SEND_MAX_WORKERS", min(32, 4 * (os.cpu_count() or 1)), type_cast=int
)
_WEBHOOK_SEND_EXECUTOR = ThreadPoolExecutor(
    max_workers=_WEBHOOK_SEND_MAX_WORKERS, thread_name_prefix="subscription-webhook"
)
_WEBHOOK_SEND_CAPACITY = BoundedSemaphore(2 * _WEBHOOK_SEND_MAX_WORKERS)


class WebhookSendCapacityExhaustedError(Exception):
    """Raised when all webhook send slots on this worker are busy."""


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
        message, {"recipient_results": error_detail_results(recipient_results)}, non_retryable=non_retryable
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
            "POST",
            url,
            json=body,
            timeout=(WEBHOOK_CONNECT_TIMEOUT_SECONDS, WEBHOOK_READ_TIMEOUT_SECONDS),
            allow_redirects=False,
            stream=True,
        )
        try:
            return response.status_code
        finally:
            response.close()


async def _send_webhook(url: str, body: dict[str, Any]) -> int:
    if not _WEBHOOK_SEND_CAPACITY.acquire(blocking=False):
        raise WebhookSendCapacityExhaustedError

    try:
        send = _WEBHOOK_SEND_EXECUTOR.submit(_post_webhook, url, body)
    except Exception:
        _WEBHOOK_SEND_CAPACITY.release()
        raise

    send.add_done_callback(lambda _send: _WEBHOOK_SEND_CAPACITY.release())
    return await asyncio.wrap_future(send)


async def deliver_teams_webhook(
    subscription: Subscription,
    recipient_results: list[RecipientResult],
    *,
    body: dict[str, Any],
) -> DeliverSubscriptionResult:
    """Deliver a Teams card to the subscription's configured webhook."""
    url = subscription.target_value
    recipient = subscription.recipient_label
    LOGGER.info("deliver_subscription.sending_webhook", subscription_id=subscription.id, recipient=recipient)

    # The serializer runs the same check on save. Re-running it here means a stored value that never
    # went through that path, or went through an older version of it, still cannot make this worker
    # POST to a host outside the Microsoft set.
    if not is_microsoft_teams_webhook_url(url):
        LOGGER.error("deliver_subscription.webhook_url_blocked", subscription_id=subscription.id, recipient=recipient)
        _fail_webhook_delivery(
            subscription,
            recipient_results,
            recipient=recipient,
            message="Webhook URL failed validation: not a Microsoft Teams webhook URL",
            error_type="webhook_url_blocked",
            human_readable_error=_WEBHOOK_UNREACHABLE_MESSAGE,
            non_retryable=False,
        )

    try:
        status = await _send_webhook(url, body)
    except WebhookSendCapacityExhaustedError:
        LOGGER.warning(
            "deliver_subscription.webhook_send_capacity_exhausted",
            subscription_id=subscription.id,
            recipient=recipient,
        )
        _fail_webhook_delivery(
            subscription,
            recipient_results,
            recipient=recipient,
            message="No webhook send capacity on this worker",
            error_type="webhook_send_capacity_exhausted",
            human_readable_error=_WEBHOOK_UNREACHABLE_MESSAGE,
            non_retryable=False,
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
        human_readable_error=f"Microsoft Teams returned an error (HTTP {status}).",
        non_retryable=not (status == 429 or status >= 500),
    )
