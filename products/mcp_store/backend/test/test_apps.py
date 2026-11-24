from unittest.mock import patch

from django.apps import apps
from django.test import SimpleTestCase, override_settings

from celery.signals import worker_ready

QUEUE_SYNC = "products.mcp_store.backend.tasks.tasks.queue_sync_mcp_server_templates"


class TestCatalogSyncTrigger(SimpleTestCase):
    # TEST is overridden so the check doesn't pass only because of a test-mode guard.
    @override_settings(TEST=False, STATIC_COLLECTION=False)
    def test_app_ready_does_not_queue_the_sync(self) -> None:
        # Dagster runs and other processes that load Django may point at another broker.
        with patch(QUEUE_SYNC) as queue_sync:
            apps.get_app_config("mcp_store").ready()

        queue_sync.assert_not_called()

    @override_settings(MCP_CATALOG_SYNC_ON_WORKER_READY=True)
    def test_worker_ready_queues_the_sync_once(self) -> None:
        # ready() runs again above and in other tests; the dispatch_uid keeps it to one receiver.
        apps.get_app_config("mcp_store").ready()

        with patch(QUEUE_SYNC) as queue_sync:
            worker_ready.send(sender=None)

        queue_sync.assert_called_once_with()

    @override_settings(MCP_CATALOG_SYNC_ON_WORKER_READY=False)
    def test_worker_ready_skips_the_sync_when_disabled(self) -> None:
        apps.get_app_config("mcp_store").ready()

        with patch(QUEUE_SYNC) as queue_sync:
            worker_ready.send(sender=None)

        queue_sync.assert_not_called()
