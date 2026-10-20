import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.splunkobservabilitycloud import (
    SplunkObservabilityCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.splunk_observability_cloud.settings import (
    PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.splunk_observability_cloud.source import (
    SplunkObservabilityCloudSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.splunk_observability_cloud.splunk_observability_cloud import (
    SplunkObservabilityCloudResumeConfig,
    _iter_sse_events,
    _ms_to_datetime,
    _to_epoch_ms,
    normalize_realm,
    validate_credentials,
)


def _wrapped(rows: list[dict[str, Any]], count: int | None = None) -> dict[str, Any]:
    return {"count": count if count is not None else len(rows), "results": rows}


def _driver(*, signalflow_program: str | None = None) -> SourceDriver:
    return SourceDriver(
        SplunkObservabilityCloudSource(),
        SplunkObservabilityCloudSourceConfig(
            realm="us0", access_token="test-token", signalflow_program=signalflow_program
        ),
    )


class TestNormalizeRealm:
    @pytest.mark.parametrize("raw", ["", "evil.com", "us0/", "us0.attacker", "us 0", "us_0", "a" * 33])
    def test_invalid_raises(self, raw: str) -> None:
        # The realm is interpolated into the request hostname, so anything that isn't a
        # bare realm code must be rejected before a request is built.
        with pytest.raises(ValueError, match="realm"):
            normalize_realm(raw)


class TestTimestampConversion:
    @pytest.mark.parametrize(
        ("value", "expected_ms"),
        [
            (datetime(2026, 1, 1, tzinfo=UTC), 1767225600000),
            (datetime(2026, 1, 1), 1767225600000),  # naive treated as UTC
            (date(2026, 1, 1), 1767225600000),
            (1767225600000, 1767225600000),
        ],
    )
    def test_to_epoch_ms(self, value: Any, expected_ms: int) -> None:
        assert _to_epoch_ms(value) == expected_ms

    def test_ms_round_trip(self) -> None:
        assert _ms_to_datetime(1767225600000) == datetime(2026, 1, 1, tzinfo=UTC)
        assert _ms_to_datetime(None) is None


class TestRestPagination:
    def test_full_page_then_short_page(self) -> None:
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        responses = [
            ScriptedResponse(json=_wrapped(full_page, count=PAGE_SIZE + 1)),
            ScriptedResponse(json=_wrapped([{"id": "last"}], count=PAGE_SIZE + 1)),
        ]
        result = _driver().run("detectors", responses)

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 1
        assert list(zip(result.params("offset"), result.params("limit"))) == [
            ("0", str(PAGE_SIZE)),
            (str(PAGE_SIZE), str(PAGE_SIZE)),
        ]
        # Resume state is saved only while there is a next page to resume to, and after
        # the page has been yielded.
        assert result.saved_states == [SplunkObservabilityCloudResumeConfig(offset=PAGE_SIZE)]

    def test_client_error_raises_without_retry(self) -> None:
        result = _driver().run("detectors", [ScriptedResponse(status=401, json={"message": "unauthorized"})])
        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1


class TestDetectorEventsFanOut:
    def _detector_page(self, ids: list[str]) -> ScriptedResponse:
        return ScriptedResponse(json=_wrapped([{"id": detector_id} for detector_id in ids]))

    def test_incremental_watermark_sets_from(self) -> None:
        responses = [
            self._detector_page(["det-1"]),
            ScriptedResponse(json=[]),
        ]
        watermark = datetime(2026, 1, 1, tzinfo=UTC)
        result = _driver().run(
            "detector_events",
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        event_requests = [request for request in result.requests if "/events" in request.path]
        assert event_requests[0].param("from") == "1767225600000"

    def test_resume_skips_earlier_detectors_and_seeds_offset(self) -> None:
        responses = [
            self._detector_page(["det-1", "det-2", "det-3"]),
            ScriptedResponse(json=[{"id": "ev", "detectorId": "det-2", "timestamp": 1}]),
            ScriptedResponse(json=[]),
        ]
        result = _driver().run(
            "detector_events",
            responses,
            resume_state=SplunkObservabilityCloudResumeConfig(offset=PAGE_SIZE, detector_id="det-2"),
        )

        assert result.raised is None
        event_requests = [request for request in result.requests if "/events" in request.path]
        assert [request.path for request in event_requests] == [
            "/v2/detector/det-2/events",
            "/v2/detector/det-3/events",
        ]
        # The bookmarked detector resumes at its saved offset; the next one starts fresh.
        assert [request.param("offset") for request in event_requests] == [str(PAGE_SIZE), "0"]


def _sse_lines(events: list[tuple[str, dict[str, Any]]]) -> list[str]:
    lines: list[str] = []
    for name, payload in events:
        lines.append(f"event: {name}")
        lines.append(f"data: {json.dumps(payload)}")
        lines.append("")
    return lines


class TestSignalFlow:
    def _drive(
        self,
        events: list[tuple[str, dict[str, Any]]],
        **kwargs: Any,
    ) -> DriveResult:
        body = "\n".join(_sse_lines(events)).encode()
        return _driver(signalflow_program="data('cpu.utilization').publish()").run(
            "metric_time_series", [ScriptedResponse(body=body)], **kwargs
        )

    def test_sse_parser_handles_multi_event_stream(self) -> None:
        response = MagicMock()
        response.iter_lines.return_value = [
            ": keep-alive comment",
            "event: metadata",
            'data: {"tsId": "A"}',
            "",
            'data: {"note": "default event name"}',
            "",
        ]
        events = list(_iter_sse_events(response))
        assert events == [("metadata", '{"tsId": "A"}'), ("message", '{"note": "default event name"}')]

    def test_datapoints_join_metadata_and_convert_timestamps(self) -> None:
        result = self._drive(
            [
                ("control-message", {"event": "JOB_START", "timestampMs": 1, "handle": "h"}),
                ("metadata", {"tsId": "AAAA", "properties": {"sf_metric": "cpu.utilization", "host": "web-1"}}),
                ("data", {"logicalTimestampMs": 1767225600000, "data": [{"tsId": "AAAA", "value": 42.5}]}),
                ("data", {"logicalTimestampMs": 1767225660000, "data": [{"tsId": "AAAA", "value": 43.0}]}),
                ("control-message", {"event": "END_OF_CHANNEL", "timestampMs": 2}),
            ]
        )

        assert result.raised is None
        assert [row["value"] for row in result.rows] == [42.5, 43.0]
        assert result.rows[0]["tsId"] == "AAAA"
        assert result.rows[0]["timestamp"] == datetime(2026, 1, 1, tzinfo=UTC)
        assert result.rows[0]["metric"] == "cpu.utilization"
        assert json.loads(result.rows[0]["properties"])["host"] == "web-1"

    def test_error_message_raises(self) -> None:
        result = self._drive([("error", {"errors": [{"code": "ANALYTICS_PROGRAM_NAME_ERROR"}]})])
        assert isinstance(result.raised, Exception)
        assert "SignalFlow computation failed" in str(result.raised)

    def test_channel_abort_raises(self) -> None:
        result = self._drive(
            [
                (
                    "control-message",
                    {"event": "CHANNEL_ABORT", "timestampMs": 1, "abortInfo": {"sf_job_abortState": "FAILED"}},
                )
            ]
        )
        assert isinstance(result.raised, Exception)
        assert "aborted" in str(result.raised)

    def test_missing_program_is_actionable_error(self) -> None:
        result = _driver(signalflow_program="   ").run("metric_time_series", [])
        assert isinstance(result.raised, ValueError)
        assert "SignalFlow program" in str(result.raised)
        assert result.requests == []

    def test_incremental_watermark_sets_start(self) -> None:
        watermark = datetime(2026, 1, 1, tzinfo=UTC)
        result = self._drive(
            [("control-message", {"event": "END_OF_CHANNEL", "timestampMs": 1})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )
        assert result.raised is None
        assert result.requests[0].param("start") == "1767225600000"


class TestSourceResponse:
    def test_detector_events_defers_watermark_to_job_end(self) -> None:
        # The fan-out is not globally time-ordered, so the watermark must not
        # checkpoint per batch (desc mode persists it only at successful job end).
        result = _driver().run("detector_events", [ScriptedResponse(json=_wrapped([]))])

        assert result.raised is None
        assert result.response is not None
        assert result.response.sort_mode == "desc"


class TestRedirectHardening:
    # requests strips only `Authorization` when a redirect crosses hosts, so a session
    # that follows redirects would replay the X-SF-TOKEN header to whatever host a 3xx
    # names. Both session constructions must pin redirects off.
    def test_get_rows_session_never_follows_redirects(self) -> None:
        result = _driver().run("detectors", [ScriptedResponse(json=_wrapped([]))])

        assert result.raised is None
        assert result.session_options[0]["allow_redirects"] is False

    def test_validate_credentials_session_never_follows_redirects(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("us0", "test-token")

        assert network.session_options[0]["allow_redirects"] is False


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [(200, True), (401, False), (403, False), (500, False)],
    )
    def test_status_code_mapping(self, status_code: int, expected_valid: bool) -> None:
        # The transport retries a 500, so the script answers every try.
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            valid, error = validate_credentials("us0", "test-token")

        assert valid is expected_valid
        assert (error is None) is expected_valid
        assert {request.path for request in network.requests_log} == {"/v2/organization"}

    def test_redirect_returns_actionable_realm_message(self) -> None:
        # A 3xx passes `status_code < 400` checks; with redirects pinned off it must
        # surface as "wrong realm", not a confusing unexpected-status error.
        with scripted_network([ScriptedResponse(status=302, headers={"Location": "https://example.com/"})]) as network:
            valid, error = validate_credentials("us0", "test-token")

        assert valid is False
        assert error is not None and "realm" in error
        assert len(network.requests_log) == 1

    def test_invalid_realm_fails_without_request(self) -> None:
        with scripted_network([]) as network:
            valid, error = validate_credentials("not a realm!", "test-token")

        assert valid is False
        assert error is not None and "realm" in error
        assert network.requests_log == []

    def test_network_error_returns_message(self) -> None:
        def fail_request(_request: RecordedRequest) -> ScriptedResponse:
            raise Exception("boom")

        with scripted_network(fail_request) as network:
            valid, error = validate_credentials("us0", "test-token")

        assert valid is False
        assert error == "boom"
        assert len(network.requests_log) == 1
