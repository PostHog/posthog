import io

from unittest import mock

from django.test import SimpleTestCase, override_settings

import structlog
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest

from posthog import otel_logs
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
    def test_pipeline_logs_serialize_and_export_through_the_real_worker_chain(self) -> None:
        # The load-bearing regression, on two counts. First, the previous bridge attached a stdlib
        # handler, but the worker logs via a non-stdlib structlog factory, so it shipped nothing: this
        # drives a log through the real configure_logger chain and asserts the record is exported.
        # Second, it uses the real OTLPLogExporter (only the network session is mocked), so the record
        # is actually serialized to protobuf. An in-memory exporter skips serialization and hid a crash
        # on the default None span_id. A regression in either the wiring or the record shape fails here.
        mock_session = mock.MagicMock()
        mock_session.post.return_value = mock.MagicMock(status_code=200)

        with mock.patch("posthog.security.outbound_proxy.internal_requests_session", return_value=mock_session):
            configure_logger(
                otel_log_mirror=build_vision_log_mirror(), cache_logger_on_first_use=False, file=io.StringIO()
            )
            logger = structlog.get_logger(f"{VISION_LOGS_LOGGER_PREFIX}.activities.call_scanner_provider")
            logger.info("scanner_call_failed", observation_id="obs_1", response_preview="customer session text")
            provider = otel_logs._ensure_provider(VISION_LOGS_SERVICE_NAME)
            assert provider is not None
            provider.force_flush(5000)

        assert mock_session.post.called, "real OTLP exporter never POSTed (serialization or transport failed)"
        data = mock_session.post.call_args.kwargs.get("data") or mock_session.post.call_args.args[0]
        request = ExportLogsServiceRequest.FromString(data)

        records = [record for rl in request.resource_logs for sl in rl.scope_logs for record in sl.log_records]
        matched = [record for record in records if record.body.string_value == "scanner_call_failed"]
        assert len(matched) == 1
        record = matched[0]
        service_name = next(
            kv.value.string_value for kv in request.resource_logs[0].resource.attributes if kv.key == "service.name"
        )
        attributes = {kv.key: kv.value.string_value for kv in record.attributes}
        assert service_name == VISION_LOGS_SERVICE_NAME
        assert attributes["observation_id"] == "obs_1"
        assert "response_preview" not in attributes

    def test_allowlist_excludes_payload_derived_fields(self) -> None:
        # The allowlist is the security boundary. Lock in that a content field a pipeline log is known
        # to carry (response_preview, model output derived from a customer session) is not on it.
        assert "response_preview" not in VISION_LOG_ATTRIBUTE_ALLOWLIST
        assert "observation_id" in VISION_LOG_ATTRIBUTE_ALLOWLIST
