import json
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock, patch

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.splunk_observability_cloud.settings import (
    PAGE_SIZE,
    SIGNALFLOW_DEFAULT_LOOKBACK_DAYS,
    SPLUNK_OBSERVABILITY_CLOUD_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.splunk_observability_cloud.splunk_observability_cloud import (
    SplunkObservabilityCloudResumeConfig,
    _iter_sse_events,
    _ms_to_datetime,
    _to_epoch_ms,
    get_rows,
    normalize_realm,
    splunk_observability_cloud_source,
    validate_credentials,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.splunk_observability_cloud.splunk_observability_cloud"


def _json_response(body: Any, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.is_redirect = False
    response.json.return_value = body
    response.text = json.dumps(body)
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status_code} Client Error", response=response)
    return response


def _wrapped(rows: list[dict[str, Any]], count: int | None = None) -> dict[str, Any]:
    return {"count": count if count is not None else len(rows), "results": rows}


def _make_manager(resume: SplunkObservabilityCloudResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _drive_rest(
    endpoint: str,
    responses: list[MagicMock],
    manager: MagicMock | None = None,
    **kwargs: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], MagicMock]:
    """Run get_rows against canned responses; returns (rows, per-request query params, manager)."""
    manager = manager if manager is not None else _make_manager()
    requested: list[dict[str, Any]] = []
    response_iter = iter(responses)

    def fake_get(url: str, **_kw: Any) -> MagicMock:
        parsed = urlparse(url)
        params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        params["__path"] = parsed.path
        requested.append(params)
        return next(response_iter)

    with patch(f"{_MODULE}.make_tracked_session") as mock_session_factory:
        mock_session_factory.return_value.get.side_effect = fake_get
        rows = [
            row
            for page in get_rows(
                realm="us0",
                access_token="test-token",
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=manager,
                **kwargs,
            )
            for row in page
        ]
    return rows, requested, manager


class TestNormalizeRealm:
    @pytest.mark.parametrize(("raw", "expected"), [("us0", "us0"), (" EU0 ", "eu0"), ("jp0", "jp0")])
    def test_valid(self, raw: str, expected: str) -> None:
        assert normalize_realm(raw) == expected

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
            _json_response(_wrapped(full_page, count=PAGE_SIZE + 1)),
            _json_response(_wrapped([{"id": "last"}], count=PAGE_SIZE + 1)),
        ]
        rows, requested, manager = _drive_rest("detectors", responses)

        assert len(rows) == PAGE_SIZE + 1
        assert [(p["offset"], p["limit"]) for p in requested] == [
            ("0", str(PAGE_SIZE)),
            (str(PAGE_SIZE), str(PAGE_SIZE)),
        ]
        # Resume state is saved only while there is a next page to resume to, and after
        # the page has been yielded.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [SplunkObservabilityCloudResumeConfig(offset=PAGE_SIZE)]

    def test_single_short_page_saves_no_state(self) -> None:
        rows, requested, manager = _drive_rest("detectors", [_json_response(_wrapped([{"id": "a"}]))])

        assert [row["id"] for row in rows] == ["a"]
        assert len(requested) == 1
        manager.save_state.assert_not_called()

    def test_resume_seeds_offset(self) -> None:
        manager = _make_manager(SplunkObservabilityCloudResumeConfig(offset=PAGE_SIZE))
        rows, requested, _ = _drive_rest("detectors", [_json_response(_wrapped([{"id": "resumed"}]))], manager)

        assert [row["id"] for row in rows] == ["resumed"]
        assert requested[0]["offset"] == str(PAGE_SIZE)

    def test_incidents_parses_bare_array_and_includes_resolved(self) -> None:
        responses = [_json_response([{"incidentId": "inc-1"}, {"incidentId": "inc-2"}])]
        rows, requested, _ = _drive_rest("incidents", responses)

        assert [row["incidentId"] for row in rows] == ["inc-1", "inc-2"]
        assert requested[0]["includeResolved"] == "true"
        assert requested[0]["__path"] == "/v2/incident"

    def test_metrics_sends_match_all_query(self) -> None:
        _, requested, _ = _drive_rest("metrics", [_json_response(_wrapped([]))])
        assert requested[0]["query"] == "name:*"

    def test_client_error_raises_without_retry(self) -> None:
        with pytest.raises(requests.HTTPError):
            _drive_rest("detectors", [_json_response({"message": "unauthorized"}, status_code=401)])


class TestDetectorEventsFanOut:
    def _detector_page(self, ids: list[str]) -> MagicMock:
        return _json_response(_wrapped([{"id": detector_id} for detector_id in ids]))

    def test_fans_out_and_normalizes_timestamps(self) -> None:
        responses = [
            self._detector_page(["det-1", "det-2"]),
            _json_response([{"id": "ev-1", "detectorId": "det-1", "timestamp": 1767225600000}]),
            _json_response([{"id": "ev-2", "detectorId": "det-2", "timestamp": 1767225660000}]),
        ]
        rows, requested, manager = _drive_rest("detector_events", responses)

        assert [row["id"] for row in rows] == ["ev-1", "ev-2"]
        # Epoch-ms timestamps become real datetimes so incremental/partitioning works.
        assert rows[0]["timestamp"] == datetime(2026, 1, 1, tzinfo=UTC)

        event_requests = [p for p in requested if "/events" in p["__path"]]
        assert [p["__path"] for p in event_requests] == [
            "/v2/detector/det-1/events",
            "/v2/detector/det-2/events",
        ]
        # Full refresh pulls all history: from=0, to=now.
        assert all(p["from"] == "0" for p in event_requests)
        assert all(int(p["to"]) > 0 for p in event_requests)

        # Bookmark advances to the next detector between detectors so a crash resumes
        # in the right place.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert SplunkObservabilityCloudResumeConfig(offset=0, detector_id="det-2") in saved

    def test_incremental_watermark_sets_from(self) -> None:
        responses = [
            self._detector_page(["det-1"]),
            _json_response([]),
        ]
        watermark = datetime(2026, 1, 1, tzinfo=UTC)
        _, requested, _ = _drive_rest(
            "detector_events",
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        event_requests = [p for p in requested if "/events" in p["__path"]]
        assert event_requests[0]["from"] == "1767225600000"

    def test_resume_skips_earlier_detectors_and_seeds_offset(self) -> None:
        manager = _make_manager(SplunkObservabilityCloudResumeConfig(offset=PAGE_SIZE, detector_id="det-2"))
        responses = [
            self._detector_page(["det-1", "det-2", "det-3"]),
            _json_response([{"id": "ev", "detectorId": "det-2", "timestamp": 1}]),
            _json_response([]),
        ]
        _, requested, _ = _drive_rest("detector_events", responses, manager)

        event_requests = [p for p in requested if "/events" in p["__path"]]
        assert [p["__path"] for p in event_requests] == [
            "/v2/detector/det-2/events",
            "/v2/detector/det-3/events",
        ]
        # The bookmarked detector resumes at its saved offset; the next one starts fresh.
        assert [p["offset"] for p in event_requests] == [str(PAGE_SIZE), "0"]

    def test_resume_with_deleted_detector_starts_over(self) -> None:
        manager = _make_manager(SplunkObservabilityCloudResumeConfig(offset=50, detector_id="det-gone"))
        responses = [
            self._detector_page(["det-1"]),
            _json_response([]),
        ]
        _, requested, _ = _drive_rest("detector_events", responses, manager)

        event_requests = [p for p in requested if "/events" in p["__path"]]
        assert [p["__path"] for p in event_requests] == ["/v2/detector/det-1/events"]
        assert event_requests[0]["offset"] == "0"


def _sse_lines(events: list[tuple[str, dict[str, Any]]]) -> list[str]:
    lines: list[str] = []
    for name, payload in events:
        lines.append(f"event: {name}")
        lines.append(f"data: {json.dumps(payload)}")
        lines.append("")
    return lines


def _stream_response(events: list[tuple[str, dict[str, Any]]]) -> MagicMock:
    response = MagicMock()
    response.ok = True
    response.status_code = 200
    response.is_redirect = False
    response.iter_lines.return_value = _sse_lines(events)
    return response


class TestSignalFlow:
    def _drive(
        self,
        events: list[tuple[str, dict[str, Any]]],
        **kwargs: Any,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        with patch(f"{_MODULE}.make_tracked_session") as mock_session_factory:
            mock_session = mock_session_factory.return_value
            mock_session.post.return_value = _stream_response(events)
            rows = [
                row
                for page in get_rows(
                    realm="us0",
                    access_token="test-token",
                    endpoint="metric_time_series",
                    logger=MagicMock(),
                    resumable_source_manager=_make_manager(),
                    signalflow_program="data('cpu.utilization').publish()",
                    **kwargs,
                )
                for row in page
            ]
            post_kwargs = mock_session.post.call_args.kwargs
        return rows, post_kwargs

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
        rows, _ = self._drive(
            [
                ("control-message", {"event": "JOB_START", "timestampMs": 1, "handle": "h"}),
                ("metadata", {"tsId": "AAAA", "properties": {"sf_metric": "cpu.utilization", "host": "web-1"}}),
                ("data", {"logicalTimestampMs": 1767225600000, "data": [{"tsId": "AAAA", "value": 42.5}]}),
                ("data", {"logicalTimestampMs": 1767225660000, "data": [{"tsId": "AAAA", "value": 43.0}]}),
                ("control-message", {"event": "END_OF_CHANNEL", "timestampMs": 2}),
            ]
        )

        assert [row["value"] for row in rows] == [42.5, 43.0]
        assert rows[0]["tsId"] == "AAAA"
        assert rows[0]["timestamp"] == datetime(2026, 1, 1, tzinfo=UTC)
        assert rows[0]["metric"] == "cpu.utilization"
        assert json.loads(rows[0]["properties"])["host"] == "web-1"

    def test_datapoint_without_metadata_still_yields(self) -> None:
        rows, _ = self._drive(
            [
                ("data", {"logicalTimestampMs": 1767225600000, "data": [{"tsId": "B", "value": 1.0}]}),
                ("control-message", {"event": "END_OF_CHANNEL", "timestampMs": 2}),
            ]
        )
        assert rows[0]["metric"] is None
        assert rows[0]["properties"] is None

    def test_error_message_raises(self) -> None:
        with pytest.raises(Exception, match="SignalFlow computation failed"):
            self._drive([("error", {"errors": [{"code": "ANALYTICS_PROGRAM_NAME_ERROR"}]})])

    def test_channel_abort_raises(self) -> None:
        with pytest.raises(Exception, match="aborted"):
            self._drive(
                [
                    (
                        "control-message",
                        {"event": "CHANNEL_ABORT", "timestampMs": 1, "abortInfo": {"sf_job_abortState": "FAILED"}},
                    )
                ]
            )

    def test_missing_program_is_actionable_error(self) -> None:
        with patch(f"{_MODULE}.make_tracked_session"), pytest.raises(ValueError, match="SignalFlow program"):
            list(
                get_rows(
                    realm="us0",
                    access_token="test-token",
                    endpoint="metric_time_series",
                    logger=MagicMock(),
                    resumable_source_manager=_make_manager(),
                    signalflow_program="   ",
                )
            )

    def test_incremental_watermark_sets_start(self) -> None:
        watermark = datetime(2026, 1, 1, tzinfo=UTC)
        _, post_kwargs = self._drive(
            [("control-message", {"event": "END_OF_CHANNEL", "timestampMs": 1})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )
        assert post_kwargs["params"]["start"] == "1767225600000"

    def test_full_refresh_uses_default_lookback(self) -> None:
        _, post_kwargs = self._drive([("control-message", {"event": "END_OF_CHANNEL", "timestampMs": 1})])
        params = post_kwargs["params"]
        expected_window_ms = SIGNALFLOW_DEFAULT_LOOKBACK_DAYS * 24 * 60 * 60 * 1000
        assert int(params["stop"]) - int(params["start"]) == expected_window_ms


class TestSourceResponse:
    @pytest.mark.parametrize("endpoint", list(SPLUNK_OBSERVABILITY_CLOUD_ENDPOINTS.keys()))
    def test_primary_keys_and_partitioning_match_settings(self, endpoint: str) -> None:
        config = SPLUNK_OBSERVABILITY_CLOUD_ENDPOINTS[endpoint]
        response = splunk_observability_cloud_source(
            realm="us0",
            access_token="test-token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=_make_manager(),
        )

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None

    def test_detector_events_defers_watermark_to_job_end(self) -> None:
        # The fan-out is not globally time-ordered, so the watermark must not
        # checkpoint per batch (desc mode persists it only at successful job end).
        response = splunk_observability_cloud_source(
            realm="us0",
            access_token="test-token",
            endpoint="detector_events",
            logger=MagicMock(),
            resumable_source_manager=_make_manager(),
        )
        assert response.sort_mode == "desc"

    def test_metric_time_series_streams_ascending(self) -> None:
        response = splunk_observability_cloud_source(
            realm="us0",
            access_token="test-token",
            endpoint="metric_time_series",
            logger=MagicMock(),
            resumable_source_manager=_make_manager(),
        )
        assert response.sort_mode == "asc"


class TestRedirectHardening:
    # requests strips only `Authorization` when a redirect crosses hosts, so a session
    # that follows redirects would replay the X-SF-TOKEN header to whatever host a 3xx
    # names. Both session constructions must pin redirects off.
    def test_get_rows_session_never_follows_redirects(self) -> None:
        with patch(f"{_MODULE}.make_tracked_session") as factory:
            factory.return_value.get.side_effect = [_json_response(_wrapped([]))]
            list(
                get_rows(
                    realm="us0",
                    access_token="test-token",
                    endpoint="detectors",
                    logger=MagicMock(),
                    resumable_source_manager=_make_manager(),
                )
            )
        assert factory.call_args.kwargs["allow_redirects"] is False

    def test_validate_credentials_session_never_follows_redirects(self) -> None:
        with patch(f"{_MODULE}.make_tracked_session") as factory:
            response = MagicMock()
            response.status_code = 200
            factory.return_value.get.return_value = response
            validate_credentials("us0", "test-token")
        assert factory.call_args.kwargs["allow_redirects"] is False


class TestSampleCaptureDisabled:
    # Detector/dashboard/chart response bodies and the SignalFlow program hold arbitrary
    # customer content the name-based scrubber can't redact. Dropping capture=False (back
    # to the default) would serialize that tenant content into the HTTP sample bucket.
    def test_get_rows_disables_capture(self) -> None:
        with patch(f"{_MODULE}.make_tracked_session") as factory:
            factory.return_value.get.side_effect = [_json_response(_wrapped([]))]
            list(
                get_rows(
                    realm="us0",
                    access_token="test-token",
                    endpoint="detectors",
                    logger=MagicMock(),
                    resumable_source_manager=_make_manager(),
                )
            )
        assert factory.call_args.kwargs["capture"] is False

    def test_validate_credentials_disables_capture(self) -> None:
        with patch(f"{_MODULE}.make_tracked_session") as factory:
            response = MagicMock()
            response.status_code = 200
            factory.return_value.get.return_value = response
            validate_credentials("us0", "test-token")
        assert factory.call_args.kwargs["capture"] is False


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [(200, True), (401, False), (403, False), (500, False)],
    )
    def test_status_code_mapping(self, status_code: int, expected_valid: bool) -> None:
        with patch(f"{_MODULE}.make_tracked_session") as mock_session_factory:
            response = MagicMock()
            response.status_code = status_code
            response.is_redirect = False
            mock_session_factory.return_value.get.return_value = response

            valid, error = validate_credentials("us0", "test-token")

        assert valid is expected_valid
        assert (error is None) is expected_valid

    def test_redirect_returns_actionable_realm_message(self) -> None:
        # A 3xx passes `status_code < 400` checks; with redirects pinned off it must
        # surface as "wrong realm", not a confusing unexpected-status error.
        with patch(f"{_MODULE}.make_tracked_session") as mock_session_factory:
            response = MagicMock()
            response.status_code = 302
            response.is_redirect = True
            mock_session_factory.return_value.get.return_value = response

            valid, error = validate_credentials("us0", "test-token")

        assert valid is False
        assert error is not None and "realm" in error

    def test_invalid_realm_fails_without_request(self) -> None:
        with patch(f"{_MODULE}.make_tracked_session") as mock_session_factory:
            valid, error = validate_credentials("not a realm!", "test-token")

        assert valid is False
        assert error is not None and "realm" in error
        mock_session_factory.assert_not_called()

    def test_network_error_returns_message(self) -> None:
        with patch(f"{_MODULE}.make_tracked_session") as mock_session_factory:
            mock_session_factory.return_value.get.side_effect = Exception("boom")
            valid, error = validate_credentials("us0", "test-token")

        assert valid is False
        assert error == "boom"
