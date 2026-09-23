import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from threading import Event
from zoneinfo import ZoneInfo

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import requests
from asgiref.sync import sync_to_async
from temporalio.exceptions import ApplicationError

from posthog.security.url_validation import PinnedUrlVerdict

from products.exports.backend.models.subscription import Subscription
from products.exports.backend.temporal.subscriptions.delivery_webhook import (
    _WEBHOOK_SEND_CAPACITY,
    deliver_teams_webhook,
)
from products.exports.backend.temporal.subscriptions.types import RecipientResult

from ee.tasks.test.subscriptions.subscriptions_test_factory import create_subscription

pytestmark = pytest.mark.asyncio

WEBHOOK_URL = (
    "https://prod-25.westeurope.logic.azure.com:443/workflows/abc123/triggers/manual/paths/invoke?sig=supersecret"
)
WEBHOOK_HOST = "prod-25.westeurope.logic.azure.com"
CARD = {"type": "message", "attachments": []}

_PINNED_SESSION = "products.exports.backend.temporal.subscriptions.delivery_webhook.pinned_session"
_VALIDATE_URL = "posthog.security.pinned_requests.validate_url_and_pin_ips"
_CAPTURE_FAILED = "products.exports.backend.temporal.subscriptions.delivery_webhook._capture_delivery_failed_event"
_DISABLED_EMAIL = "ee.tasks.subscriptions.auto_disable.send_notifications_for_disabled_subscription"


def _unsaved_teams_subscription(url: str = WEBHOOK_URL) -> Subscription:
    return Subscription(
        id=1,
        team_id=1,
        target_type="teams",
        target_value=url,
        frequency="daily",
        interval=1,
        start_date=datetime(2022, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC")),
    )


@contextmanager
def _destination_responds(status: int) -> Iterator[MagicMock]:
    with patch(_PINNED_SESSION) as pinned_session:
        request = pinned_session.return_value.__enter__.return_value.request
        request.return_value = MagicMock(status_code=status)
        yield request


@pytest.mark.parametrize("target_value", ["https://[::1", "", "not a url"])
async def test_a_target_value_with_no_parseable_host_still_gets_a_label(target_value) -> None:
    # The label is what every delivery receipt and log line names the destination by, so a stored
    # value that no longer parses has to degrade to a placeholder rather than raise mid-delivery.
    assert _unsaved_teams_subscription(target_value).recipient_label == "webhook"


@override_settings(DEBUG=False)
async def test_a_url_that_stops_resolving_stays_retryable() -> None:
    subscription = _unsaved_teams_subscription()
    recipient_results: list[RecipientResult] = []
    unresolvable = PinnedUrlVerdict(allowed=False, reason="DNS resolution failed", pinned_ips=set())

    with patch(_VALIDATE_URL, return_value=unresolvable), patch("requests.Session.request") as mock_request:
        with patch(_CAPTURE_FAILED), pytest.raises(ApplicationError) as error:
            await deliver_teams_webhook(subscription, recipient_results, body=CARD)

    # A Microsoft host that fails to resolve now may resolve on the next run, so the delivery must
    # not be written off as permanently broken.
    assert mock_request.call_count == 0
    assert error.value.non_retryable is False
    assert recipient_results[0].error is not None
    assert recipient_results[0].error["type"] == "webhook_url_blocked"


async def test_a_stored_url_outside_the_microsoft_hosts_is_never_posted_to() -> None:
    # The serializer is not the only writer of target_value, so the host allowlist runs again here.
    subscription = _unsaved_teams_subscription("https://evil.example.com/workflows/abc")
    recipient_results: list[RecipientResult] = []

    with patch(_PINNED_SESSION) as pinned_session, patch(_CAPTURE_FAILED):
        with pytest.raises(ApplicationError) as error:
            await deliver_teams_webhook(subscription, recipient_results, body=CARD)

    assert pinned_session.call_count == 0
    assert error.value.non_retryable is False
    assert recipient_results[0].error is not None
    assert recipient_results[0].error["type"] == "webhook_url_blocked"


async def test_a_worker_out_of_send_slots_refuses_the_send_instead_of_queueing_it() -> None:
    # Every slot taken means every thread is inside a send that has not returned. Queueing behind
    # them would hold this delivery past the activity timeout with nothing to show for it.
    subscription = _unsaved_teams_subscription()
    recipient_results: list[RecipientResult] = []

    held = 0
    while _WEBHOOK_SEND_CAPACITY.acquire(blocking=False):
        held += 1
    try:
        with patch(_PINNED_SESSION) as pinned_session, patch(_CAPTURE_FAILED):
            with pytest.raises(ApplicationError) as error:
                await deliver_teams_webhook(subscription, recipient_results, body=CARD)
    finally:
        for _ in range(held):
            _WEBHOOK_SEND_CAPACITY.release()

    assert pinned_session.call_count == 0
    assert error.value.non_retryable is False
    assert recipient_results[0].error is not None
    assert recipient_results[0].error["type"] == "webhook_send_capacity_exhausted"


async def test_cancelling_a_delivery_keeps_its_send_slot_until_the_thread_stops() -> None:
    subscription = _unsaved_teams_subscription()
    recipient_results: list[RecipientResult] = []
    send_started = Event()
    release_send = Event()
    send_stopped = Event()

    def blocked_post(*_args, **_kwargs) -> int:
        send_started.set()
        release_send.wait()
        send_stopped.set()
        return 202

    held = 0
    while _WEBHOOK_SEND_CAPACITY.acquire(blocking=False):
        held += 1
    _WEBHOOK_SEND_CAPACITY.release()
    try:
        with patch(
            "products.exports.backend.temporal.subscriptions.delivery_webhook._post_webhook", side_effect=blocked_post
        ):
            delivery = asyncio.create_task(deliver_teams_webhook(subscription, recipient_results, body=CARD))
            await asyncio.wait_for(asyncio.to_thread(send_started.wait), timeout=1)
            delivery.cancel()
            with pytest.raises(asyncio.CancelledError):
                await delivery

            assert not _WEBHOOK_SEND_CAPACITY.acquire(blocking=False)

            release_send.set()
            await asyncio.wait_for(asyncio.to_thread(send_stopped.wait), timeout=1)
            assert _WEBHOOK_SEND_CAPACITY.acquire(blocking=False)
            _WEBHOOK_SEND_CAPACITY.release()
    finally:
        release_send.set()
        for _ in range(held - 1):
            _WEBHOOK_SEND_CAPACITY.release()


async def test_a_destination_that_stops_answering_stays_retryable() -> None:
    subscription = _unsaved_teams_subscription()
    recipient_results: list[RecipientResult] = []

    with patch(_PINNED_SESSION) as pinned_session, patch(_CAPTURE_FAILED):
        pinned_session.return_value.__enter__.return_value.request.side_effect = requests.ReadTimeout(
            f"Read timed out for {WEBHOOK_URL}"
        )
        with pytest.raises(ApplicationError) as error:
            await deliver_teams_webhook(subscription, recipient_results, body=CARD)

    assert error.value.non_retryable is False
    assert recipient_results[0].error is not None
    assert recipient_results[0].error["type"] == "webhook_request_failed"
    # The exception text carries the URL, so only its class name may reach the receipt.
    assert recipient_results[0].error["message"] == "Webhook request failed: ReadTimeout"
    assert "supersecret" not in str(error.value.details)


@pytest.mark.parametrize("status", [200, 202])
async def test_any_2xx_is_a_successful_delivery(status) -> None:
    subscription = _unsaved_teams_subscription()
    recipient_results: list[RecipientResult] = []

    with _destination_responds(status) as request:
        result = await deliver_teams_webhook(subscription, recipient_results, body=CARD)

    assert request.call_args.kwargs["json"] == CARD
    # A destination can answer with a body of any size, and only the status is ever read.
    assert request.call_args.kwargs["stream"] is True
    assert [(r.recipient, r.status) for r in result.recipient_results] == [(WEBHOOK_HOST, "success")]


@pytest.mark.parametrize("status,expected_non_retryable", [(429, False), (500, False), (400, True)])
async def test_error_status_raises_with_the_right_retry_semantics(status, expected_non_retryable) -> None:
    subscription = _unsaved_teams_subscription()
    recipient_results: list[RecipientResult] = []

    with _destination_responds(status), patch(_CAPTURE_FAILED):
        with pytest.raises(ApplicationError) as error:
            await deliver_teams_webhook(subscription, recipient_results, body=CARD)

    assert error.value.non_retryable is expected_non_retryable
    assert subscription.enabled is True


@pytest.mark.parametrize("status", [202, 500])
async def test_delivery_receipt_never_holds_the_webhook_url(status) -> None:
    subscription = _unsaved_teams_subscription()
    recipient_results: list[RecipientResult] = []

    with _destination_responds(status), patch(_CAPTURE_FAILED):
        try:
            await deliver_teams_webhook(subscription, recipient_results, body=CARD)
        except ApplicationError as error:
            assert "supersecret" not in str(error)
            assert "supersecret" not in str(error.details)

    assert recipient_results
    for result in recipient_results:
        assert result.recipient == WEBHOOK_HOST
        assert "supersecret" not in str(result.error)
        assert "supersecret" not in str(result.human_readable_error)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("status", [403, 404, 410])
async def test_permanent_status_auto_disables_the_subscription(team, user, status) -> None:
    subscription = await sync_to_async(create_subscription)(
        team=team, created_by=user, target_type="teams", target_value=WEBHOOK_URL
    )
    recipient_results: list[RecipientResult] = []

    with _destination_responds(status), patch(_DISABLED_EMAIL), patch(_CAPTURE_FAILED):
        result = await deliver_teams_webhook(subscription, recipient_results, body=CARD)

    await sync_to_async(subscription.refresh_from_db)()
    assert subscription.enabled is False
    assert result.recipient_results[0].recipient == WEBHOOK_HOST
    assert result.recipient_results[0].error is not None
    assert result.recipient_results[0].error["type"] == "webhook_rejected"
