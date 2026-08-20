from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from asgiref.sync import sync_to_async
from temporalio.exceptions import ApplicationError

from products.exports.backend.models.subscription import Subscription
from products.exports.backend.temporal.subscriptions.delivery_common import deliver_webhook
from products.exports.backend.temporal.subscriptions.types import RecipientResult

from ee.tasks.test.subscriptions.subscriptions_test_factory import create_subscription

pytestmark = pytest.mark.asyncio

WEBHOOK_URL = (
    "https://prod-25.westeurope.logic.azure.com:443/workflows/abc123/triggers/manual/paths/invoke?sig=supersecret"
)
WEBHOOK_HOST = "prod-25.westeurope.logic.azure.com"
CARD = {"type": "message", "attachments": []}

_PINNED_REQUEST = "products.exports.backend.temporal.subscriptions.delivery_common.pinned_request"
_CAPTURE_FAILED = "products.exports.backend.temporal.subscriptions.delivery_common._capture_delivery_failed_event"
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


@override_settings(DEBUG=False)
async def test_blocked_url_never_issues_a_request() -> None:
    subscription = _unsaved_teams_subscription("https://127.0.0.1/workflows/abc")
    recipient_results: list[RecipientResult] = []

    with patch("requests.Session.request") as mock_request, patch(_CAPTURE_FAILED):
        with pytest.raises(ApplicationError) as error:
            await deliver_webhook(subscription, recipient_results, url=subscription.target_value, body=CARD)

    assert mock_request.call_count == 0
    assert error.value.non_retryable is False
    assert recipient_results[0].error is not None
    assert recipient_results[0].error["type"] == "webhook_url_blocked"


@pytest.mark.parametrize("status", [200, 202])
async def test_any_2xx_is_a_successful_delivery(status) -> None:
    subscription = _unsaved_teams_subscription()
    recipient_results: list[RecipientResult] = []

    with patch(_PINNED_REQUEST, return_value=MagicMock(status_code=status)) as mock_post:
        result = await deliver_webhook(subscription, recipient_results, url=WEBHOOK_URL, body=CARD)

    assert mock_post.call_args.kwargs["json"] == CARD
    assert [(r.recipient, r.status) for r in result.recipient_results] == [(WEBHOOK_HOST, "success")]


@pytest.mark.parametrize("status,expected_non_retryable", [(429, False), (500, False), (400, True)])
async def test_error_status_raises_with_the_right_retry_semantics(status, expected_non_retryable) -> None:
    subscription = _unsaved_teams_subscription()
    recipient_results: list[RecipientResult] = []

    with patch(_PINNED_REQUEST, return_value=MagicMock(status_code=status)), patch(_CAPTURE_FAILED):
        with pytest.raises(ApplicationError) as error:
            await deliver_webhook(subscription, recipient_results, url=WEBHOOK_URL, body=CARD)

    assert error.value.non_retryable is expected_non_retryable
    assert subscription.enabled is True


@pytest.mark.parametrize("status", [202, 500])
async def test_delivery_receipt_never_holds_the_webhook_url(status) -> None:
    subscription = _unsaved_teams_subscription()
    recipient_results: list[RecipientResult] = []

    with patch(_PINNED_REQUEST, return_value=MagicMock(status_code=status)), patch(_CAPTURE_FAILED):
        try:
            await deliver_webhook(subscription, recipient_results, url=WEBHOOK_URL, body=CARD)
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

    with (
        patch(_PINNED_REQUEST, return_value=MagicMock(status_code=status)),
        patch(_DISABLED_EMAIL),
        patch(_CAPTURE_FAILED),
    ):
        result = await deliver_webhook(subscription, recipient_results, url=WEBHOOK_URL, body=CARD)

    await sync_to_async(subscription.refresh_from_db)()
    assert subscription.enabled is False
    assert result.recipient_results[0].recipient == WEBHOOK_HOST
    assert result.recipient_results[0].error is not None
    assert result.recipient_results[0].error["type"] == "webhook_rejected"
