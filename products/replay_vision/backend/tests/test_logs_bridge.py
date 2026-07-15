import logging

from unittest import mock

from django.test import SimpleTestCase

from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.resources import Resource

from posthog.otel_logs import OtelLogHandler, reset_otel_logs_for_tests

from products.replay_vision.backend.temporal import logs as bridge


class TestVisionLogBridge(SimpleTestCase):
    def setUp(self) -> None:
        self.logger = logging.getLogger(bridge._TEMPORAL_LOGGER_NAME)
        self._orig_handlers = list(self.logger.handlers)
        self._orig_installed = bridge._installed
        self._orig_level = self.logger.level
        self.addCleanup(self._restore)
        # Clean slate: the package __init__ already installed the bridge at import time.
        self.logger.handlers = [handler for handler in self.logger.handlers if not isinstance(handler, OtelLogHandler)]
        bridge._installed = False

    def _restore(self) -> None:
        self.logger.handlers = self._orig_handlers
        self.logger.setLevel(self._orig_level)
        bridge._installed = self._orig_installed

    def test_install_is_idempotent_and_attaches_one_handler(self) -> None:
        # Double-install would ship every record twice; a wrong service name would land the logs where
        # the Logs read filter (service.name = replay-vision) can't find them.
        bridge.install_vision_log_bridge()
        bridge.install_vision_log_bridge()
        handlers = [handler for handler in self.logger.handlers if isinstance(handler, OtelLogHandler)]
        assert len(handlers) == 1
        assert handlers[0]._service_name == bridge.VISION_LOGS_SERVICE_NAME
        # Fail-closed allowlist must be wired so payload-derived fields never reach the shared project.
        assert handlers[0]._attribute_allowlist == bridge.VISION_LOG_ATTRIBUTE_ALLOWLIST
        assert "response_preview" not in bridge.VISION_LOG_ATTRIBUTE_ALLOWLIST

    def test_pipeline_logs_reach_the_logs_product_under_the_service_name(self) -> None:
        # The load-bearing claim of the bridge: a record from any logger under the pipeline namespace
        # propagates to the handler and ships under service.name = replay-vision, with no call-site
        # change. A wrong namespace string would silently ship nothing.
        exporter = InMemoryLogExporter()
        provider = LoggerProvider(resource=Resource.create({"service.name": bridge.VISION_LOGS_SERVICE_NAME}))
        provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
        reset_otel_logs_for_tests()
        self.addCleanup(reset_otel_logs_for_tests)
        self.logger.setLevel(logging.INFO)

        with mock.patch("posthog.otel_logs._build_provider", return_value=provider):
            bridge.install_vision_log_bridge()
            child = logging.getLogger(f"{bridge._TEMPORAL_LOGGER_NAME}.activities.call_scanner_provider")
            child.info("scanner_call_failed")

        records = [item.log_record for item in exporter.get_finished_logs()]
        assert any(record.body == "scanner_call_failed" for record in records)
        assert all(record.resource.attributes["service.name"] == bridge.VISION_LOGS_SERVICE_NAME for record in records)
