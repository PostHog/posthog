import io

from unittest import mock

from django.test import SimpleTestCase, override_settings

import structlog
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.resources import Resource

from posthog.otel_logs import reset_otel_logs_for_tests
from posthog.temporal.common.logger import configure_logger

from products.replay_vision.backend.temporal.logs import (
    VISION_LOG_ATTRIBUTE_ALLOWLIST,
    VISION_LOGS_LOGGER_PREFIX,
    VISION_LOGS_SERVICE_NAME,
    build_vision_log_mirror,
)


class TestVisionLogMirror(SimpleTestCase):
    def setUp(self) -> None:
        reset_otel_logs_for_tests()
        self._structlog_config = structlog.get_config()
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        reset_otel_logs_for_tests()
        # configure_logger calls structlog.reset_defaults(), so restore the process-wide config.
        structlog.configure(**self._structlog_config)

    @override_settings(
        OTLP_LOGS_INGEST_ENDPOINT="http://capture-logs.posthog.svc.cluster.local:4318/i/v1/logs",
        OTLP_LOGS_INGEST_TOKEN="phc_x",
        TEMPORAL_LOG_LEVEL="DEBUG",
    )
    def test_pipeline_logs_reach_logs_through_the_real_worker_chain(self) -> None:
        # The load-bearing regression: the previous bridge attached a stdlib handler, but the worker
        # logs via a non-stdlib structlog factory, so it shipped nothing. This drives a log through the
        # actual configure_logger chain and asserts the mirror emits under service.name = replay-vision
        # with only allowlisted attributes. A mirror that isn't wired into the chain fails here.
        exporter = InMemoryLogExporter()
        provider = LoggerProvider(resource=Resource.create({"service.name": VISION_LOGS_SERVICE_NAME}))
        provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))

        with mock.patch("posthog.otel_logs._build_provider", return_value=provider):
            configure_logger(
                otel_log_mirror=build_vision_log_mirror(),
                cache_logger_on_first_use=False,
                file=io.StringIO(),
            )
            logger = structlog.get_logger(f"{VISION_LOGS_LOGGER_PREFIX}.activities.call_scanner_provider")
            logger.info("scanner_call_failed", observation_id="obs_1", response_preview="customer session text")

        matched = [
            item.log_record for item in exporter.get_finished_logs() if item.log_record.body == "scanner_call_failed"
        ]
        assert len(matched) == 1
        record = matched[0]
        attributes = record.attributes
        assert attributes is not None
        assert attributes["observation_id"] == "obs_1"
        assert "response_preview" not in attributes
        assert record.resource.attributes["service.name"] == VISION_LOGS_SERVICE_NAME

    def test_allowlist_excludes_payload_derived_fields(self) -> None:
        # The allowlist is the security boundary. Lock in that a content field a pipeline log is known
        # to carry (response_preview, model output derived from a customer session) is not on it.
        assert "response_preview" not in VISION_LOG_ATTRIBUTE_ALLOWLIST
        assert "observation_id" in VISION_LOG_ATTRIBUTE_ALLOWLIST
