import io
import gzip
import json
import base64
import zipfile
from datetime import UTC, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.amplitude import (
    AmplitudeResumeConfig,
    _auth_headers,
    _coerce_datetime,
    _get_events_rows,
    _get_list_rows,
    _iter_export_window,
    _normalize_event,
    _parse_amplitude_ts,
    amplitude_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.settings import (
    AMPLITUDE_ENDPOINTS,
    ANNOTATIONS_ENDPOINT,
    COHORTS_ENDPOINT,
    EVENTS_ENDPOINT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.amplitude"


def _make_export_zip(files: list[list[dict[str, Any]]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for idx, events in enumerate(files):
            gz_buf = io.BytesIO()
            with gzip.GzipFile(fileobj=gz_buf, mode="wb") as gz:
                gz.write("\n".join(json.dumps(event) for event in events).encode())
            archive.writestr(f"part_{idx}.json.gz", gz_buf.getvalue())
    return buf.getvalue()


def _response(status: int = 200, content: bytes = b"", json_body: Any = None, text: str = "") -> mock.MagicMock:
    response = mock.MagicMock(spec=requests.Response)
    response.status_code = status
    response.ok = 200 <= status < 300
    response.content = content
    response.text = text
    # Export downloads are streamed via iter_content; chunk the body so the spooled-file path is exercised.
    response.iter_content.side_effect = lambda chunk_size=None: iter(
        [
            content[i : i + (chunk_size or len(content) or 1)]
            for i in range(0, len(content), chunk_size or len(content) or 1)
        ]
    )
    if json_body is not None:
        response.json.return_value = json_body
    return response


class TestParseAmplitudeTimestamp:
    @parameterized.expand(
        [
            ("with_micros", "2026-03-04 02:58:14.123000", datetime(2026, 3, 4, 2, 58, 14, 123000, tzinfo=UTC)),
            ("without_micros", "2026-03-04 02:58:14", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)),
        ]
    )
    def test_parses_known_formats(self, _name: str, value: str, expected: datetime) -> None:
        assert _parse_amplitude_ts(value) == expected

    @parameterized.expand([("none", None), ("number", 12345), ("garbage", "not-a-date")])
    def test_returns_none_for_unparseable(self, _name: str, value: Any) -> None:
        assert _parse_amplitude_ts(value) is None


class TestNormalizeEvent:
    def test_converts_timestamp_fields_to_datetimes(self) -> None:
        event = _normalize_event(
            {
                "uuid": "abc",
                "event_type": "click",
                "event_time": "2026-03-04 02:58:14.000000",
                "server_upload_time": "2026-03-04 02:58:15.000000",
                "amplitude_id": 42,
            }
        )

        assert event["event_time"] == datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)
        assert event["server_upload_time"] == datetime(2026, 3, 4, 2, 58, 15, tzinfo=UTC)
        # Non-timestamp fields are passed through untouched.
        assert event["uuid"] == "abc"
        assert event["event_type"] == "click"
        assert event["amplitude_id"] == 42

    def test_leaves_unparseable_timestamps_in_place(self) -> None:
        event = _normalize_event({"event_time": ""})
        assert event["event_time"] == ""


class TestCoerceDatetime:
    def test_passes_through_aware_datetime(self) -> None:
        dt = datetime(2026, 1, 1, tzinfo=UTC)
        assert _coerce_datetime(dt) == dt

    def test_adds_utc_to_naive_datetime(self) -> None:
        assert _coerce_datetime(datetime(2026, 1, 1)) == datetime(2026, 1, 1, tzinfo=UTC)

    def test_parses_iso_string(self) -> None:
        assert _coerce_datetime("2026-01-01T05:00:00+00:00") == datetime(2026, 1, 1, 5, tzinfo=UTC)


class TestAuthHeaders:
    def test_builds_basic_auth_header(self) -> None:
        headers = _auth_headers("my-key", "my-secret")
        expected = base64.b64encode(b"my-key:my-secret").decode("ascii")
        assert headers["Authorization"] == f"Basic {expected}"
        assert headers["Accept"] == "application/json"


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_valid: bool) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as make_session:
            make_session.return_value.get.return_value = _response(status=status)
            is_valid, message = validate_credentials("key", "secret", "us")

        assert is_valid is expected_valid
        if expected_valid:
            assert message is None
        else:
            assert message is not None

    def test_network_error_is_not_valid(self) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as make_session:
            make_session.return_value.get.side_effect = requests.ConnectionError("boom")
            is_valid, message = validate_credentials("key", "secret", "us")

        assert is_valid is False
        assert message is not None

    def test_uses_eu_host_when_region_is_eu(self) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as make_session:
            make_session.return_value.get.return_value = _response(status=200)
            validate_credentials("key", "secret", "eu")

        called_url = make_session.return_value.get.call_args.args[0]
        assert called_url.startswith("https://analytics.eu.amplitude.com")


class TestIterExportWindow:
    def _session_returning(self, response: mock.MagicMock) -> mock.MagicMock:
        session = mock.MagicMock(spec=requests.Session)
        session.get.return_value = response
        return session

    def test_parses_zipped_gzipped_events(self) -> None:
        zip_bytes = _make_export_zip(
            [
                [{"uuid": "a", "event_time": "2026-01-01 00:00:00.000000"}],
                [{"uuid": "b", "event_time": "2026-01-01 01:00:00.000000"}],
            ]
        )
        session = self._session_returning(_response(status=200, content=zip_bytes))

        rows = list(
            _iter_export_window(session, "https://amplitude.com", {}, "20260101T00", "20260101T23", mock.MagicMock())
        )

        assert [row["uuid"] for row in rows] == ["a", "b"]
        # Timestamps are normalized to datetimes during parsing.
        assert rows[0]["event_time"] == datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

    def test_404_yields_no_rows(self) -> None:
        session = self._session_returning(_response(status=404, text="no data"))
        rows = list(
            _iter_export_window(session, "https://amplitude.com", {}, "20260101T00", "20260101T23", mock.MagicMock())
        )
        assert rows == []

    def test_skips_blank_lines(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            gz_buf = io.BytesIO()
            with gzip.GzipFile(fileobj=gz_buf, mode="wb") as gz:
                gz.write(b'{"uuid": "a"}\n\n{"uuid": "b"}\n')
            archive.writestr("part.json.gz", gz_buf.getvalue())
        session = self._session_returning(_response(status=200, content=buf.getvalue()))

        rows = list(
            _iter_export_window(session, "https://amplitude.com", {}, "20260101T00", "20260101T23", mock.MagicMock())
        )
        assert [row["uuid"] for row in rows] == ["a", "b"]

    def test_non_ok_status_raises(self) -> None:
        response = _response(status=400, text="bad request")
        # Assign the class (not an instance) so the requests-stubs `response` arg isn't required;
        # the mock raises `HTTPError()` when `raise_for_status` is called.
        response.raise_for_status.side_effect = requests.HTTPError
        session = self._session_returning(response)

        with pytest.raises(requests.HTTPError):
            list(
                _iter_export_window(
                    session, "https://amplitude.com", {}, "20260101T00", "20260101T23", mock.MagicMock()
                )
            )


class TestEventsWindowing:
    @freeze_time("2026-06-04 12:00:00")
    def test_windows_advance_and_state_is_saved_per_window(self) -> None:
        manager = mock.MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        windows: list[tuple[str, str]] = []

        def fake_iter(session, host, headers, start_param, end_param, logger):
            windows.append((start_param, end_param))
            yield {"uuid": f"{start_param}"}

        with mock.patch(f"{MODULE}.make_tracked_session"), mock.patch(f"{MODULE}._iter_export_window", fake_iter):
            rows = list(
                _get_events_rows(
                    api_key="key",
                    secret_key="secret",
                    region="us",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2026, 6, 2, 9, 30, tzinfo=UTC),
                )
            )

        # now=12:00, latency 2h => end boundary floored to 10:00. Cursor floored from last value to 09:00.
        assert windows == [
            ("20260602T09", "20260603T08"),
            ("20260603T09", "20260604T08"),
            ("20260604T09", "20260604T10"),
        ]
        assert len(rows) == 3

        saved = [call.args[0].window_start for call in manager.save_state.call_args_list]
        assert saved == [
            datetime(2026, 6, 3, 9, tzinfo=UTC).isoformat(),
            datetime(2026, 6, 4, 9, tzinfo=UTC).isoformat(),
            datetime(2026, 6, 4, 11, tzinfo=UTC).isoformat(),
        ]

    @freeze_time("2026-06-04 12:00:00")
    def test_resume_state_takes_precedence_over_incremental_value(self) -> None:
        manager = mock.MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = AmplitudeResumeConfig(window_start="2026-06-04T09:00:00+00:00")

        windows: list[tuple[str, str]] = []

        def fake_iter(session, host, headers, start_param, end_param, logger):
            windows.append((start_param, end_param))
            return iter(())

        with mock.patch(f"{MODULE}.make_tracked_session"), mock.patch(f"{MODULE}._iter_export_window", fake_iter):
            list(
                _get_events_rows(
                    api_key="key",
                    secret_key="secret",
                    region="us",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                )
            )

        manager.load_state.assert_called_once()
        assert windows == [("20260604T09", "20260604T10")]

    @freeze_time("2026-06-04 12:00:00")
    def test_full_refresh_starts_from_lookback_window(self) -> None:
        manager = mock.MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        windows: list[tuple[str, str]] = []

        def fake_iter(session, host, headers, start_param, end_param, logger):
            windows.append((start_param, end_param))
            return iter(())

        with mock.patch(f"{MODULE}.make_tracked_session"), mock.patch(f"{MODULE}._iter_export_window", fake_iter):
            list(
                _get_events_rows(
                    api_key="key",
                    secret_key="secret",
                    region="us",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    should_use_incremental_field=False,
                    db_incremental_field_last_value=None,
                )
            )

        # 30-day lookback from the 10:00 boundary => first window starts 30 days earlier at 10:00.
        assert windows[0][0] == "20260505T10"


class TestListRows:
    @parameterized.expand(
        [
            (COHORTS_ENDPOINT, {"cohorts": [{"id": "c1"}, {"id": "c2"}]}, ["c1", "c2"]),
            (ANNOTATIONS_ENDPOINT, {"data": [{"id": 1}]}, [1]),
            (COHORTS_ENDPOINT, {"cohorts": []}, []),
            (COHORTS_ENDPOINT, {"unexpected": []}, []),
        ]
    )
    def test_data_selector_extraction(self, endpoint: str, body: Any, expected_ids: list[Any]) -> None:
        config = AMPLITUDE_ENDPOINTS[endpoint]
        with mock.patch(f"{MODULE}.make_tracked_session") as make_session:
            make_session.return_value.get.return_value = _response(status=200, json_body=body)
            rows = list(_get_list_rows("key", "secret", "us", config, mock.MagicMock()))

        assert [row["id"] for row in rows] == expected_ids

    def test_bare_list_response_is_yielded(self) -> None:
        config = AMPLITUDE_ENDPOINTS[ANNOTATIONS_ENDPOINT]
        with mock.patch(f"{MODULE}.make_tracked_session") as make_session:
            make_session.return_value.get.return_value = _response(status=200, json_body=[{"id": 7}])
            rows = list(_get_list_rows("key", "secret", "us", config, mock.MagicMock()))

        assert [row["id"] for row in rows] == [7]


class TestAmplitudeSourceResponse:
    def test_events_response_metadata(self) -> None:
        manager = mock.MagicMock(spec=ResumableSourceManager)
        response = amplitude_source(
            api_key="key",
            secret_key="secret",
            region="us",
            endpoint=EVENTS_ENDPOINT,
            logger=mock.MagicMock(),
            resumable_source_manager=manager,
        )

        assert response.name == EVENTS_ENDPOINT
        assert response.primary_keys == ["uuid"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["event_time"]
        assert response.partition_format == "week"
        assert response.sort_mode == "asc"

    @parameterized.expand([(COHORTS_ENDPOINT,), (ANNOTATIONS_ENDPOINT,)])
    def test_list_response_metadata(self, endpoint: str) -> None:
        manager = mock.MagicMock(spec=ResumableSourceManager)
        response = amplitude_source(
            api_key="key",
            secret_key="secret",
            region="us",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=manager,
        )

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None
