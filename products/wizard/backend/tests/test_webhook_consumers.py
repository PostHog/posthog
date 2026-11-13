from datetime import UTC, datetime

from unittest.mock import patch

from django.test import SimpleTestCase

from celery.exceptions import Retry
from parameterized import parameterized

from posthog.ingress.contracts import WebhookDelivery
from posthog.ingress.dispatch.loading import get_consumer_registry, reset_consumer_registry

from products.wizard.backend.logic.artifacts.pull_requests import PullRequestArtifactNotStoredError
from products.wizard.backend.tasks.pull_requests import (
    MAX_PULL_REQUEST_EVENT_RETRIES,
    process_wizard_pull_request_event,
)
from products.wizard.backend.webhook_consumers import WEBHOOK_CONSUMERS

PULL_REQUEST_DELAY = "products.wizard.backend.facade.tasks.process_wizard_pull_request_event.delay"


def _delivery(head_ref: str) -> WebhookDelivery:
    return WebhookDelivery(
        provider="github",
        app="posthog",
        delivery_id="delivery-1",
        event_type="pull_request",
        payload={"action": "closed", "pull_request": {"head": {"ref": head_ref}}},
        received_at=datetime(2026, 11, 10, tzinfo=UTC),
        context={},
    )


class TestWizardWebhookConsumers(SimpleTestCase):
    def test_the_registry_routes_pull_request_deliveries_to_the_consumer(self) -> None:
        reset_consumer_registry()
        self.addCleanup(reset_consumer_registry)

        consumers = get_consumer_registry().consumers_for(provider="github", app="posthog", event_type="pull_request")

        assert "wizard_pull_request_state" in [consumer.name for consumer in consumers]

    @parameterized.expand(
        [
            ("wizard_branch", "posthog/wizard-019a6f2b3c4d", True),
            ("other_branch", "feature/x", False),
        ]
    )
    def test_only_wizard_branches_are_enqueued(self, _name: str, head_ref: str, enqueued: bool) -> None:
        delivery = _delivery(head_ref)

        with patch(PULL_REQUEST_DELAY) as delay:
            WEBHOOK_CONSUMERS[0].handler(delivery)

        if enqueued:
            delay.assert_called_once_with(payload=dict(delivery.payload))
        else:
            delay.assert_not_called()

    def test_a_close_without_an_artifact_is_retried_then_dropped(self) -> None:
        with patch(
            "products.wizard.backend.logic.artifacts.pull_requests.handle_pull_request_event",
            side_effect=PullRequestArtifactNotStoredError("https://github.com/acme/widgets/pull/7"),
        ):
            with self.assertRaises(Retry):
                process_wizard_pull_request_event.apply(kwargs={"payload": {}}, retries=0)

            result = process_wizard_pull_request_event.apply(
                kwargs={"payload": {}}, retries=MAX_PULL_REQUEST_EVENT_RETRIES
            )

        assert result.successful()
