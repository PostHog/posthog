import io
import gzip
import json
import base64
import zipfile
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Literal

import pytest
import time_machine
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.amplitude._config import AmplitudeSourceConfig
from products.warehouse_sources.sources.amplitude.amplitude import (
    AmplitudeResumeConfig,
    AmplitudeRetryableError,
    _auth_headers,
    _iter_export_window,
    _normalize_event,
    _parse_amplitude_ts,
    _parse_chart_date,
    validate_credentials,
)
from products.warehouse_sources.sources.amplitude.settings import (
    ANNOTATIONS_ENDPOINT,
    COHORTS_ENDPOINT,
    COMPOSITION_ENDPOINT,
    COMPOSITION_PROPERTIES,
    DEPLOYMENTS_ENDPOINT,
    EVENT_PROPERTIES_ENDPOINT,
    EVENTS_ENDPOINT,
    EXPERIMENTS_ENDPOINT,
    FLAGS_ENDPOINT,
    GROUP_PROPERTIES_ENDPOINT,
    LOOKUP_TABLES_ENDPOINT,
    RETENTION_ENDPOINT,
    REVENUE_LTV_ENDPOINT,
)
from products.warehouse_sources.sources.amplitude.source import MISSING_MANAGEMENT_KEY_MESSAGE, AmplitudeSource
from products.warehouse_sources.sources.sdk.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    error_message_matches,
    scripted_network,
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


def _driver(region: Literal["us", "eu"] = "us", management_api_key: str | None = None) -> SourceDriver:
    return SourceDriver(
        AmplitudeSource(),
        AmplitudeSourceConfig(api_key="key", secret_key="secret", region=region, management_api_key=management_api_key),
    )


def _non_retryable_messages(error: BaseException | None) -> list[str | None]:
    return [
        message
        for pattern, message in AmplitudeSource().get_non_retryable_errors().items()
        if error_message_matches(str(error), [pattern])
    ]


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
            (
                LOOKUP_TABLES_ENDPOINT,
                [
                    {"name": "sku_to_product", "columnHeaders": ["Category"], "keyColumnHeader": "SKU", "rowCount": 3},
                    {"name": "store_to_region", "columnHeaders": ["Region"], "keyColumnHeader": "Store", "rowCount": 9},
                ],
                "/api/3/lookup_table",
                "name",
                ["sku_to_product", "store_to_region"],
            ),
            (LOOKUP_TABLES_ENDPOINT, [], "/api/3/lookup_table", "name", []),
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


class TestApiHosts:
    @parameterized.expand(
        [
            (LOOKUP_TABLES_ENDPOINT, "us", None, [], "https://data-api.amplitude.com"),
            (LOOKUP_TABLES_ENDPOINT, "eu", None, [], "https://data-api.eu.amplitude.com"),
            (FLAGS_ENDPOINT, "us", "mgmt-key", {"flags": []}, "https://experiment.amplitude.com"),
            (FLAGS_ENDPOINT, "eu", "mgmt-key", {"flags": []}, "https://experiment.eu.amplitude.com"),
        ]
    )
    def test_endpoint_uses_its_regional_host(
        self,
        endpoint: str,
        region: Literal["us", "eu"],
        management_api_key: str | None,
        body: Any,
        expected_origin: str,
    ) -> None:
        result = _driver(region=region, management_api_key=management_api_key).run(
            endpoint, [ScriptedResponse(json=body)]
        )

        assert [request.origin for request in result.requests] == [expected_origin]
        assert result.raised is None


class TestExperimentManagementRows:
    @parameterized.expand(
        [
            (EXPERIMENTS_ENDPOINT, "experiments", "true"),
            (FLAGS_ENDPOINT, "flags", "true"),
            (DEPLOYMENTS_ENDPOINT, "deployments", None),
        ]
    )
    def test_walks_cursor_pages_with_the_management_key(
        self, endpoint: str, selector: str, include_archived: str | None
    ) -> None:
        pages = [
            ScriptedResponse(json={selector: [{"id": "101"}, {"id": "102"}], "nextCursor": 2}),
            ScriptedResponse(json={selector: [{"id": "103"}], "nextCursor": None}),
        ]

        result = _driver(management_api_key="mgmt-key").run(endpoint, pages)

        assert [row["id"] for row in result.rows] == ["101", "102", "103"]
        assert result.paths == [f"/api/1/{endpoint}"] * 2
        assert result.params("cursor") == [None, "2"]
        assert result.params("limit") == ["1000", "1000"]
        assert result.params("includeArchived") == [include_archived] * 2
        assert {request.headers["authorization"] for request in result.requests} == {"Bearer mgmt-key"}
        assert any("mgmt-key" in options.get("redact_values", ()) for options in result.session_options)
        assert result.raised is None

    @parameterized.expand(
        [
            ("null_cursor", {"flags": [{"id": "2"}], "nextCursor": None}),
            ("empty_cursor", {"flags": [{"id": "2"}], "nextCursor": ""}),
            ("no_cursor_key", {"flags": [{"id": "2"}]}),
            ("repeated_cursor", {"flags": [{"id": "2"}], "nextCursor": 1}),
        ]
    )
    def test_stops_at_the_last_page(self, _name: str, last_page: dict[str, Any]) -> None:
        pages = [ScriptedResponse(json={"flags": [{"id": "1"}], "nextCursor": 1}), ScriptedResponse(json=last_page)]

        result = _driver(management_api_key="mgmt-key").run(FLAGS_ENDPOINT, pages)

        assert [row["id"] for row in result.rows] == ["1", "2"]
        assert len(result.requests) == 2
        assert result.raised is None

    def test_deployment_keys_are_not_synced(self) -> None:
        body = {
            "deployments": [
                {
                    "id": "11",
                    "projectId": "200",
                    "label": "production",
                    "key": "server-fake-deployment-key",
                    "deleted": False,
                }
            ]
        }

        result = _driver(management_api_key="mgmt-key").run(DEPLOYMENTS_ENDPOINT, [ScriptedResponse(json=body)])

        assert result.rows == [{"id": "11", "projectId": "200", "label": "production", "deleted": False}]

    def test_missing_management_key_fails_without_a_request(self) -> None:
        result = _driver(management_api_key=None).run(EXPERIMENTS_ENDPOINT, always(ScriptedResponse(json={})))

        assert result.requests == []
        assert result.rows == []
        assert _non_retryable_messages(result.raised) == [MISSING_MANAGEMENT_KEY_MESSAGE]

    @parameterized.expand([(401,), (403,)])
    def test_rejected_management_key_maps_to_its_own_message(self, status: int) -> None:
        result = _driver(management_api_key="mgmt-key").run(
            FLAGS_ENDPOINT, [ScriptedResponse(status=status, json={"error": "Unauthorized"})]
        )

        messages = _non_retryable_messages(result.raised)
        assert len(messages) == 1
        assert messages[0] is not None and "Management API key" in messages[0]


class TestParseChartDate:
    @parameterized.expand(
        [
            ("iso", "2025-12-30", date(2026, 1, 5), date(2025, 12, 30)),
            ("label_same_year", "Jan 04", date(2026, 1, 5), date(2026, 1, 4)),
            ("label_previous_year", "Dec 31", date(2026, 1, 5), date(2025, 12, 31)),
            ("label_on_end_date", "Jan 5", date(2026, 1, 5), date(2026, 1, 5)),
            ("leap_day_previous_year", "Feb 29", date(2029, 1, 10), date(2028, 2, 29)),
        ]
    )
    def test_parses_labels(self, _name: str, label: str, end: date, expected: date) -> None:
        assert _parse_chart_date(label, end) == expected

    @parameterized.expand([("garbage", "not a date"), ("none", None), ("number", 20260105)])
    def test_unknown_label_raises(self, _name: str, label: Any) -> None:
        with pytest.raises(ValueError):
            _parse_chart_date(label, date(2026, 1, 5))


class TestDashboardCharts:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self) -> Iterator[None]:
        with time_machine.travel("2026-01-05 12:00:00", tick=False):
            yield

    def test_retention_sends_default_chart_and_emits_one_row_per_cohort_day(self) -> None:
        body = {
            "data": {
                "series": [
                    {
                        "dates": ["Jan 05", "Dec 31"],
                        "values": {
                            "Dec 31": [
                                {"count": 100, "outof": 100, "incomplete": False},
                                {"count": 40, "outof": 100, "incomplete": False},
                                {"count": 25, "outof": 100, "incomplete": True},
                            ],
                            "Jan 05": [{"count": 80, "outof": 80, "incomplete": False}],
                        },
                    }
                ],
                "seriesMeta": [{"segmentIndex": 0, "eventIndex": 0}],
            }
        }

        result = _driver().run(RETENTION_ENDPOINT, [ScriptedResponse(json=body)])

        assert result.raised is None
        assert result.paths == ["/api/2/retention"]
        request = result.requests[0]
        assert json.loads(request.param("se") or "null") == {"event_type": "_new"}
        assert json.loads(request.param("re") or "null") == {"event_type": "_all"}
        assert (request.param("rm"), request.param("i")) == ("nday", "1")
        assert (request.param("start"), request.param("end")) == ("20251008", "20260105")
        # Index 0 is the cohort size, so day 0 is the second bucket.
        assert [(row["date"], row["day"], row["count"], row["incomplete"]) for row in result.rows] == [
            (date(2025, 12, 31), 0, 40, False),
            (date(2025, 12, 31), 1, 25, True),
        ]

    def test_composition_queries_each_built_in_property(self) -> None:
        charts = {
            "version": {"series": [[50, 20]], "seriesLabels": ["version"], "xValues": ["1.0", "(none)"]},
            "country": {"series": [[7]], "xValues": ["US"]},
            "city": {"series": [[]], "xValues": []},
            "paying": {"series": [[3, 9]], "xValues": [True, False]},
        }

        result = _driver().run(
            COMPOSITION_ENDPOINT,
            [ScriptedResponse(json={"data": charts.get(prop, {})}) for prop in COMPOSITION_PROPERTIES],
        )

        assert result.raised is None
        assert result.params("p") == list(COMPOSITION_PROPERTIES)
        assert set(result.params("start")) == {"20251008"}
        assert set(result.params("end")) == {"20260105"}
        assert result.rows == [
            {"property": "version", "value": "1.0", "users": 50},
            {"property": "version", "value": "(none)", "users": 20},
            {"property": "country", "value": "US", "users": 7},
            {"property": "paying", "value": "True", "users": 3},
            {"property": "paying", "value": "False", "users": 9},
        ]

    def test_revenue_ltv_queries_each_metric_and_stamps_it_onto_rows(self) -> None:
        def ltv_body(r1d: float) -> dict[str, Any]:
            return {
                "data": {
                    "seriesLabels": [""],
                    "series": [
                        {
                            "dates": ["2026-01-05"],
                            "values": {"2026-01-05": {"r1d": r1d, "r90d": r1d * 2, "count": 10, "paid": 2}},
                        }
                    ],
                }
            }

        result = _driver().run(
            REVENUE_LTV_ENDPOINT,
            [ScriptedResponse(json=ltv_body(value)) for value in (1.5, 7.5, 15.0, 2.0)],
        )

        assert result.raised is None
        assert result.paths == ["/api/2/revenue/ltv"] * 4
        assert result.params("m") == ["0", "1", "2", "3"]
        assert set(result.params("i")) == {"1"}
        assert [(row["date"], row["metric"], row["r1d"], row["count"]) for row in result.rows] == [
            (date(2026, 1, 5), "arpu", 1.5, 10),
            (date(2026, 1, 5), "arppu", 7.5, 10),
            (date(2026, 1, 5), "total_revenue", 15.0, 10),
            (date(2026, 1, 5), "paying_users", 2.0, 10),
        ]

    @parameterized.expand([(RETENTION_ENDPOINT,), (COMPOSITION_ENDPOINT,), (REVENUE_LTV_ENDPOINT,)])
    def test_http_errors_propagate(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(status=400, json={"error": "invalid"})])

        assert isinstance(result.raised, requests.HTTPError)
        assert result.rows == []


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
