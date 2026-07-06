from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import WebhookSource
from products.warehouse_sources.backend.temporal.data_imports.sources.slack.source import SlackSource


class TestSlackSourceWebhookEventSync:
    def test_does_not_override_reconcile_hooks(self):
        # Slack configures webhooks manually — inheriting the base no-ops keeps reconcile away from it.
        assert SlackSource.sync_webhook_events is WebhookSource.sync_webhook_events
        assert SlackSource.get_desired_webhook_events is WebhookSource.get_desired_webhook_events

    def test_get_desired_webhook_events_is_none(self):
        assert SlackSource().get_desired_webhook_events(MagicMock(), ["messages"]) is None

    def test_sync_webhook_events_is_noop_success(self):
        result = SlackSource().sync_webhook_events(
            MagicMock(), "https://example.com/h", team_id=1, eligible_schema_names=["messages"]
        )
        assert result.success is True
        assert result.error is None
