import io
import gzip
import json
import base64
import zipfile
from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.amplitude import (
    AmplitudeResumeConfig,
    AmplitudeRetryableError,
    _auth_headers,
    _iter_export_window,
    _normalize_event,
    _parse_amplitude_ts,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.settings import (
    ANNOTATIONS_ENDPOINT,
    COHORTS_ENDPOINT,
    EVENT_PROPERTIES_ENDPOINT,
    EVENTS_ENDPOINT,
    GROUP_PROPERTIES_ENDPOINT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.source import AmplitudeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.amplitude import (
    AmplitudeSourceConfig,
)


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


def _driver() -> SourceDriver:
    return SourceDriver(AmplitudeSource(), AmplitudeSourceConfig(api_key="key", secret_key="secret", region="us"))


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
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_valid: bool) -> None:
        # The adapter retries a 500, so every try gets the same answer.
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            is_valid, message = validate_credentials("key", "secret", "us")

        assert {request.path for request in network.requests_log} == {"/api/2/annotations"}
        assert is_valid is expected_valid
        if expected_valid:
            assert message is None
        else:
            assert message is not None

    def test_network_error_is_not_valid(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            is_valid, message = validate_credentials("key", "secret", "us")

        # The real stack retries a dropped connection.
        assert {request.path for request in network.requests_log} == {"/api/2/annotations"}
        assert is_valid is False
        assert message is not None

    def test_uses_eu_host_when_region_is_eu(self) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            validate_credentials("key", "secret", "eu")

        assert network.requests_log[0].url.startswith("https://analytics.eu.amplitude.com")


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

    def test_invalid_zip_body_raises_retryable_error(self) -> None:
        # Amplitude has occasionally served a 2xx response whose body isn't a valid archive
        # (e.g. truncated by a network blip). That must surface as a retryable failure so
        # Temporal retries the activity, not as an unhandled BadZipFile crash.
        session = self._session_returning(_response(status=200, content=b"not a zip file"))

        with pytest.raises(AmplitudeRetryableError):
            list(
                _iter_export_window(
                    session, "https://amplitude.com", {}, "20260101T00", "20260101T23", mock.MagicMock()
                )
            )

    def test_corrupt_entry_payload_raises_retryable_error(self) -> None:
        # The central directory parses fine, but an entry's payload isn't valid gzip data.
        # That only surfaces while the entry is being read, not when the archive is opened.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("part_0.json.gz", b"not actually gzip data")
        session = self._session_returning(_response(status=200, content=buf.getvalue()))

        with pytest.raises(AmplitudeRetryableError):
            list(
                _iter_export_window(
                    session, "https://amplitude.com", {}, "20260101T00", "20260101T23", mock.MagicMock()
                )
            )

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
    @time_machine.travel("2026-06-04 12:00:00", tick=False)
    def test_windows_advance_and_state_is_saved_per_window(self) -> None:
        result = _driver().run(
            EVENTS_ENDPOINT,
            [
                ScriptedResponse(body=_make_export_zip([[{"uuid": "first"}]])),
                ScriptedResponse(body=_make_export_zip([[{"uuid": "second"}]])),
                ScriptedResponse(body=_make_export_zip([[{"uuid": "third"}]])),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 2, 9, 30, tzinfo=UTC),
        )

        # now=12:00, latency 2h => end boundary floored to 10:00. Cursor floored from last value to 09:00.
        assert result.params("start") == ["20260602T09", "20260603T09", "20260604T09"]
        assert result.params("end") == ["20260603T08", "20260604T08", "20260604T10"]
        assert [row["uuid"] for row in result.rows] == ["first", "second", "third"]
        assert result.saved_states == [
            AmplitudeResumeConfig(window_start=datetime(2026, 6, 3, 9, tzinfo=UTC).isoformat()),
            AmplitudeResumeConfig(window_start=datetime(2026, 6, 4, 9, tzinfo=UTC).isoformat()),
            AmplitudeResumeConfig(window_start=datetime(2026, 6, 4, 11, tzinfo=UTC).isoformat()),
        ]
        assert result.raised is None

    @time_machine.travel("2026-06-04 12:00:00", tick=False)
    def test_resume_state_takes_precedence_over_incremental_value(self) -> None:
        result = _driver().run(
            EVENTS_ENDPOINT,
            [ScriptedResponse(status=404)],
            resume_state=AmplitudeResumeConfig(window_start="2026-06-04T09:00:00+00:00"),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.params("start") == ["20260604T09"]
        assert result.params("end") == ["20260604T10"]
        assert result.raised is None

    @time_machine.travel("2026-06-04 12:00:00", tick=False)
    def test_full_refresh_starts_from_lookback_window(self) -> None:
        result = _driver().run(EVENTS_ENDPOINT, always(ScriptedResponse(status=404)))

        # 30-day lookback from the 10:00 boundary => first window starts 30 days earlier at 10:00.
        assert result.requests[0].param("start") == "20260505T10"
        assert result.raised is None


class TestListRows:
    @parameterized.expand(
        [
            (COHORTS_ENDPOINT, {"cohorts": [{"id": "c1"}, {"id": "c2"}]}, "/api/3/cohorts", "id", ["c1", "c2"]),
            (ANNOTATIONS_ENDPOINT, {"data": [{"id": 1}]}, "/api/2/annotations", "id", [1]),
            (COHORTS_ENDPOINT, {"cohorts": []}, "/api/3/cohorts", "id", []),
            (COHORTS_ENDPOINT, {"unexpected": []}, "/api/3/cohorts", "id", []),
            (
                GROUP_PROPERTIES_ENDPOINT,
                {
                    "success": True,
                    "data": [
                        {"group_property": "grp:plan_tier", "type": "string", "is_hidden": False},
                        {"group_property": "grp:seat_count", "type": "number", "is_array_type": False},
                    ],
                },
                "/api/2/taxonomy/group-property",
                "group_property",
                ["grp:plan_tier", "grp:seat_count"],
            ),
            (
                GROUP_PROPERTIES_ENDPOINT,
                {"success": True, "data": []},
                "/api/2/taxonomy/group-property",
                "group_property",
                [],
            ),
        ]
    )
    def test_data_selector_extraction(
        self, endpoint: str, body: Any, expected_path: str, key_field: str, expected_keys: list[Any]
    ) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=body)])

        assert [row[key_field] for row in result.rows] == expected_keys
        assert result.paths == [expected_path]
        # A `group_type` param would narrow group properties to one group type instead of the shared set.
        assert "?" not in result.urls[0]
        assert result.raised is None

    def test_bare_list_response_is_yielded(self) -> None:
        result = _driver().run(ANNOTATIONS_ENDPOINT, [ScriptedResponse(json=[{"id": 7}])])

        assert [row["id"] for row in result.rows] == [7]
        assert result.raised is None


class TestFanoutRows:
    def test_queries_each_event_type_and_stamps_it_onto_child_rows(self) -> None:
        parents = ScriptedResponse(
            json={
                "success": True,
                "data": [
                    {"event_type": "Play Song"},
                    {"event_type": "Onboard Start"},
                    # A parent with no usable name must not be queried.
                    {"category": {"name": "Attribution"}},
                ],
            },
        )
        # Amplitude omits `event_type` on shared properties, so the fan-out has to supply it.
        song_props = ScriptedResponse(json={"success": True, "data": [{"event_property": "genre"}]})
        onboard_props = ScriptedResponse(json={"success": True, "data": [{"event_property": "step"}]})

        result = _driver().run(EVENT_PROPERTIES_ENDPOINT, [parents, song_props, onboard_props])

        assert [(row["event_type"], row["event_property"]) for row in result.rows] == [
            ("Play Song", "genre"),
            ("Onboard Start", "step"),
        ]
        assert len(result.requests) == 3
        assert result.paths == [
            "/api/2/taxonomy/event",
            "/api/2/taxonomy/event-property",
            "/api/2/taxonomy/event-property",
        ]
        assert result.params("event_type") == [None, "Play Song", "Onboard Start"]
        assert result.urls[1].endswith("/api/2/taxonomy/event-property?event_type=Play+Song")
        assert result.urls[2].endswith("/api/2/taxonomy/event-property?event_type=Onboard+Start")
        assert result.raised is None

    def test_400_on_one_event_type_skips_it_and_keeps_going(self) -> None:
        parents = ScriptedResponse(json={"data": [{"event_type": "Deleted Event"}, {"event_type": "Play Song"}]})
        not_found = ScriptedResponse(status=400, json={"success": False, "errors": [{"message": "Not found"}]})
        song_props = ScriptedResponse(json={"data": [{"event_property": "genre"}]})

        result = _driver().run(EVENT_PROPERTIES_ENDPOINT, [parents, not_found, song_props])

        assert [row["event_type"] for row in result.rows] == ["Play Song"]
        assert result.params("event_type") == [None, "Deleted Event", "Play Song"]
        assert result.raised is None

    def test_other_http_errors_propagate(self) -> None:
        parents = ScriptedResponse(json={"data": [{"event_type": "Play Song"}]})
        forbidden = ScriptedResponse(status=403, body=b"Forbidden")

        result = _driver().run(EVENT_PROPERTIES_ENDPOINT, [parents, forbidden])

        assert isinstance(result.raised, requests.HTTPError)


class TestAmplitudeSourceResponse:
    @parameterized.expand([(COHORTS_ENDPOINT,), (ANNOTATIONS_ENDPOINT,)])
    def test_list_response_metadata(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json={})])
        response = result.response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None
