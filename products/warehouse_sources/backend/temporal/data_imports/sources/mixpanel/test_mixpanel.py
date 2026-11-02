from datetime import UTC, date, datetime
from typing import Any, Literal, Optional

import pytest
import time_machine
from unittest.mock import patch

import orjson
import requests
import structlog
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mixpanel import (
    MixpanelSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mixpanel import mixpanel as mp
from products.warehouse_sources.backend.temporal.data_imports.sources.mixpanel.mixpanel import (
    MAX_RETRY_AFTER_SECONDS,
    MixpanelResumeConfig,
    MixpanelRetryableError,
    _check_response,
    _export_base,
    _ingestion_base,
    _parse_retry_after,
    _query_base,
    _retry_wait,
    _to_date,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mixpanel.settings import (
    MIXPANEL_API_VERSION_2_0,
    MIXPANEL_API_VERSION_V1,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mixpanel.source import MixpanelSource

LOGGER = structlog.get_logger()


def _driver(region: Literal["us", "eu", "in"] = "us") -> SourceDriver:
    return SourceDriver(
        MixpanelSource(),
        MixpanelSourceConfig(project_id="123", service_account_username="u", service_account_secret="s", region=region),
    )


def _export_answer(*lines: bytes) -> ScriptedResponse:
    return ScriptedResponse(body=b"\n".join(lines) + (b"\n" if lines else b""))


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        json_data: Any = None,
        lines: Optional[list[bytes]] = None,
        text: str = "",
        headers: Optional[dict[str, str]] = None,
        error: Optional[BaseException] = None,
    ) -> None:
        self.status_code = status_code
        self._json = json_data
        self._lines = lines or []
        self.text = text
        self.headers = headers or {}
        # Raised after the available lines are yielded, to simulate a connection dropped
        # mid-stream while reading the export body.
        self._error = error

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    def json(self) -> Any:
        return self._json

    def iter_lines(self):
        yield from self._lines
        if self._error is not None:
            raise self._error

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)  # type: ignore[arg-type]

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: Any) -> None:
        return None


class FakeManager:
    """Stand-in for ResumableSourceManager that records saved state in memory."""

    def __init__(self, resume_state: Optional[MixpanelResumeConfig] = None) -> None:
        self._state = resume_state
        self.saved: list[MixpanelResumeConfig] = []
        self.safe_points = 0

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> Optional[MixpanelResumeConfig]:
        return self._state

    def save_state(self, data: MixpanelResumeConfig) -> None:
        self.saved.append(data)

    def safe_point(self) -> None:
        self.safe_points += 1


class TestToDate:
    @parameterized.expand(
        [
            ("epoch_int", 1700000000, date(2023, 11, 14)),
            ("epoch_float", 1700000000.0, date(2023, 11, 14)),
            ("aware_datetime", datetime(2024, 5, 1, 23, 0, tzinfo=UTC), date(2024, 5, 1)),
            ("naive_datetime", datetime(2024, 5, 1, 12, 0), date(2024, 5, 1)),
            ("date_value", date(2024, 5, 1), date(2024, 5, 1)),
            ("iso_string", "2024-05-01T10:00:00Z", date(2024, 5, 1)),
            ("date_string", "2024-05-01", date(2024, 5, 1)),
            ("none", None, None),
            ("bad_string", "not-a-date", None),
            ("bool", True, None),
        ]
    )
    def test_to_date(self, _name: str, value: Any, expected: Optional[date]) -> None:
        assert _to_date(value) == expected


class TestRegionHosts:
    @parameterized.expand(
        [
            ("us", "https://mixpanel.com", "https://data.mixpanel.com", "https://api.mixpanel.com"),
            ("eu", "https://eu.mixpanel.com", "https://data-eu.mixpanel.com", "https://api-eu.mixpanel.com"),
            ("in", "https://in.mixpanel.com", "https://data-in.mixpanel.com", "https://api-in.mixpanel.com"),
            ("unknown", "https://mixpanel.com", "https://data.mixpanel.com", "https://api.mixpanel.com"),
        ]
    )
    def test_region_resolution(
        self, region: str, expected_query: str, expected_export: str, expected_ingestion: str
    ) -> None:
        assert _query_base(region) == expected_query
        assert _export_base(region) == expected_export
        assert _ingestion_base(region) == expected_ingestion


class TestCheckResponse:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        with pytest.raises(MixpanelRetryableError):
            _check_response(FakeResponse(status_code=status), "http://x", LOGGER)  # type: ignore[arg-type]

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error(self, _name: str, status: int) -> None:
        with pytest.raises(requests.HTTPError):
            _check_response(FakeResponse(status_code=status), "http://x", LOGGER)  # type: ignore[arg-type]

    def test_ok_returns_response(self) -> None:
        response = FakeResponse(status_code=200)
        assert _check_response(response, "http://x", LOGGER) is response  # type: ignore[arg-type, comparison-overlap]

    def test_retryable_error_carries_retry_after_header(self) -> None:
        response = FakeResponse(status_code=429, headers={"Retry-After": "30"})
        with pytest.raises(MixpanelRetryableError) as exc_info:
            _check_response(response, "http://x", LOGGER)  # type: ignore[arg-type]
        assert exc_info.value.retry_after == 30.0

    def test_retryable_error_without_retry_after_header(self) -> None:
        response = FakeResponse(status_code=503)
        with pytest.raises(MixpanelRetryableError) as exc_info:
            _check_response(response, "http://x", LOGGER)  # type: ignore[arg-type]
        assert exc_info.value.retry_after is None


class TestRetryableErrors:
    def test_retryable_marker_matches_raised_message(self) -> None:
        # The source keeps a self-recovering 429/5xx out of error tracking by matching
        # get_retryable_errors() against what _check_response raises; this guards the two in sync,
        # so a change to either the raised message or the marker can't silently revive the noise.
        with pytest.raises(MixpanelRetryableError) as exc_info:
            _check_response(FakeResponse(status_code=429), "https://data.mixpanel.com/api/2.0/export", LOGGER)  # type: ignore[arg-type]
        markers = MixpanelSource().get_retryable_errors()
        assert markers
        assert any(marker in str(exc_info.value) for marker in markers)


class TestParseRetryAfter:
    @parameterized.expand(
        [
            ("none", None, None),
            ("empty", "  ", None),
            ("integer_seconds", "30", 30.0),
            ("zero_seconds", "0", 0.0),
            ("float_seconds", "2.5", 2.5),
            ("negative_seconds", "-5", None),
            ("garbage", "soon", None),
        ]
    )
    def test_delta_seconds(self, _name: str, value: Optional[str], expected: Optional[float]) -> None:
        assert _parse_retry_after(value) == expected

    @time_machine.travel("2024-06-04T00:00:00Z", tick=False)
    def test_http_date_in_the_future(self) -> None:
        assert _parse_retry_after("Tue, 04 Jun 2024 00:00:30 GMT") == 30.0


class _FakeOutcome:
    def __init__(self, exc: Optional[BaseException]) -> None:
        self._exc = exc

    def exception(self) -> Optional[BaseException]:
        return self._exc


class _FakeRetryState:
    def __init__(self, exc: Optional[BaseException], attempt_number: int = 1) -> None:
        self.outcome = _FakeOutcome(exc)
        self.attempt_number = attempt_number


class TestRetryWait:
    def test_caps_large_retry_after(self) -> None:
        state = _FakeRetryState(MixpanelRetryableError("boom", retry_after=9999))
        assert _retry_wait(state) == MAX_RETRY_AFTER_SECONDS  # type: ignore[arg-type]

    def test_falls_back_for_non_retryable_exception_type(self) -> None:
        state = _FakeRetryState(requests.ReadTimeout("slow"))
        wait = _retry_wait(state)  # type: ignore[arg-type]
        assert 0 < wait <= 61


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("unauthorized", 401, None, False),
            ("forbidden_at_create", 403, None, True),
            ("forbidden_with_schema", 403, "export", False),
            ("bad_request", 400, None, False),
            ("unexpected", 500, None, False),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, schema_name: Optional[str], expected_ok: bool) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            ok, error = validate_credentials("us", "user", "secret", "123", schema_name=schema_name)
        assert ok is expected_ok
        assert network.requests_log[0].path == "/api/query/cohorts/list"
        assert network.requests_log[0].param("project_id") == "123"
        if expected_ok:
            assert error is None
        else:
            assert error is not None

    @parameterized.expand(
        [
            ("bad_request", 400, "project ID"),
            ("payment_required", 402, "plan"),
        ]
    )
    def test_rejections_explain_the_fix_without_the_status_code(self, _name: str, status: int, hint: str) -> None:
        with scripted_network([ScriptedResponse(status=status)]):
            ok, error = validate_credentials("us", "user", "secret", "123")
        assert ok is False
        assert error is not None and hint in error
        assert str(status) not in error

    def test_network_error_returns_failure(self) -> None:
        with scripted_network([requests.ConnectionError("boom")]) as network:
            ok, error = validate_credentials("eu", "user", "secret", "123")
        assert ok is False
        assert error is not None
        assert network.requests_log[0].url.startswith("https://eu.mixpanel.com/")


class TestExportIterator:
    @parameterized.expand([("v1", MIXPANEL_API_VERSION_V1), ("2.0", MIXPANEL_API_VERSION_2_0)])
    @time_machine.travel("2024-01-01", tick=False)
    def test_export_hits_versioned_path(self, _name: str, api_version: str) -> None:
        # Both supported versions resolve to Mixpanel's `2.0` raw-export path; the segment is
        # derived from the pin, so this guards the version -> URL wiring per supported version.
        result = _driver().run(
            "export",
            [_export_answer()],
            api_version=api_version,
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2024, 1, 1),
        )
        assert result.raised is None
        assert result.urls[0].split("?", 1)[0] == "https://data.mixpanel.com/api/2.0/export"
        assert result.params("from_date") == ["2024-01-01"]
        assert result.params("to_date") == ["2024-01-01"]

    @time_machine.travel("2024-01-02", tick=False)
    def test_resumes_from_saved_state(self) -> None:
        result = _driver().run(
            "export",
            [_export_answer(orjson.dumps({"event": "B", "properties": {"time": 2}}))],
            resume_state=MixpanelResumeConfig(from_date="2024-01-02"),
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2024, 1, 1),
        )
        # Only the resumed day is fetched, the earlier day is skipped
        assert result.raised is None
        assert result.params("from_date") == ["2024-01-02"]
        assert [row["event"] for row in result.rows] == ["B"]

    @time_machine.travel("2024-01-01", tick=False)
    def test_browser_version_is_always_text(self) -> None:
        lines = [
            orjson.dumps({"event": "A", "properties": {"time": 1, "$browser_version": version}})
            for version in (120, 120.0, 17.4, "130.0.0.0")
        ]
        result = _driver().run(
            "export",
            [_export_answer(*lines)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2024, 1, 1),
        )
        assert result.raised is None
        assert [row["$browser_version"] for row in result.rows] == ["120", "120", "17.4", "130.0.0.0"]
        assert [row["time"] for row in result.rows] == [1, 1, 1, 1]


class TestExportStreamRetry:
    def _line(self, insert_id: str) -> bytes:
        return orjson.dumps({"event": "A", "properties": {"time": 1, "$insert_id": insert_id}})

    @time_machine.travel("2024-01-01", tick=False)
    def test_retries_day_when_the_stream_carries_the_abort_marker(self) -> None:
        result = _driver().run(
            "export",
            [
                _export_answer(self._line("i1"), b"terminated early"),
                _export_answer(self._line("i1"), self._line("i2")),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2024, 1, 1),
        )

        assert result.raised is None
        assert [row["$insert_id"] for row in result.rows] == ["i1", "i2"]
        assert result.params("from_date") == ["2024-01-01", "2024-01-01"]
        assert [state.from_date for state in result.saved_states] == ["2024-01-02"]

    @time_machine.travel("2024-01-01", tick=False)
    def test_does_not_retry_a_line_without_the_abort_marker(self) -> None:
        result = _driver().run(
            "export",
            [_export_answer(self._line("i1"), b"<html>gateway</html>")],
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2024, 1, 1),
        )

        assert isinstance(result.raised, orjson.JSONDecodeError)
        assert result.params("from_date") == ["2024-01-01"]

    def test_gives_up_after_max_attempts(self) -> None:
        manager = FakeManager()
        day = date(2024, 1, 1)
        responses = [
            FakeResponse(lines=[], error=requests.exceptions.ChunkedEncodingError("Connection broken"))
            for _ in range(mp.STREAM_MAX_ATTEMPTS)
        ]
        with (
            patch.object(mp, "_request", side_effect=responses) as mock_request,
            patch.object(mp.time, "sleep") as mock_sleep,
        ):
            with pytest.raises(requests.exceptions.ChunkedEncodingError):
                list(
                    mp._iter_export(
                        "us",
                        "u",
                        "s",
                        "123",
                        LOGGER,
                        manager,  # type: ignore[arg-type]
                        start_date=day,
                        end_date=day,
                        api_version=MIXPANEL_API_VERSION_V1,
                    )
                )

        assert mock_request.call_count == mp.STREAM_MAX_ATTEMPTS
        assert mock_sleep.call_count == mp.STREAM_MAX_ATTEMPTS - 1
        # The failing day's cursor is never advanced.
        assert manager.saved == []

    def test_does_not_retry_unrelated_error(self) -> None:
        manager = FakeManager()
        day = date(2024, 1, 1)
        failing = FakeResponse(lines=[], error=ValueError("malformed payload"))
        with (
            patch.object(mp, "_request", side_effect=[failing]) as mock_request,
            patch.object(mp.time, "sleep") as mock_sleep,
        ):
            with pytest.raises(ValueError):
                list(
                    mp._iter_export(
                        "us",
                        "u",
                        "s",
                        "123",
                        LOGGER,
                        manager,  # type: ignore[arg-type]
                        start_date=day,
                        end_date=day,
                        api_version=MIXPANEL_API_VERSION_V1,
                    )
                )

        assert mock_request.call_count == 1
        mock_sleep.assert_not_called()

    @parameterized.expand(
        [
            ("read_timeout", requests.ReadTimeout("stalled")),
            ("connection_error", requests.ConnectionError("refused")),
        ]
    )
    def test_does_not_refetch_when_request_gave_up(self, _name: str, error: Exception) -> None:
        manager = FakeManager()
        day = date(2024, 1, 1)
        with (
            patch.object(mp, "_request", side_effect=error) as mock_request,
            patch.object(mp.time, "sleep") as mock_sleep,
        ):
            with pytest.raises(type(error)):
                list(
                    mp._iter_export(
                        "us",
                        "u",
                        "s",
                        "123",
                        LOGGER,
                        manager,  # type: ignore[arg-type]
                        start_date=day,
                        end_date=day,
                        api_version=MIXPANEL_API_VERSION_V1,
                    )
                )

        assert mock_request.call_count == 1
        mock_sleep.assert_not_called()


class TestEngageIterator:
    def test_paginates_with_session_id_and_saves_state(self) -> None:
        page0 = ScriptedResponse(
            json={
                "page": 0,
                "page_size": 2,
                "session_id": "sess-1",
                "results": [
                    {"$distinct_id": "a", "$properties": {"x": 1}},
                    {"$distinct_id": "b", "$properties": {"x": 2}},
                ],
            }
        )
        page1 = ScriptedResponse(
            json={
                "page": 1,
                "page_size": 2,
                "session_id": "sess-1",
                "results": [{"$distinct_id": "c", "$properties": {"x": 3}}],
            }
        )
        result = _driver().run("engage", [page0, page1])

        assert result.raised is None
        assert [row["$distinct_id"] for row in result.rows] == ["a", "b", "c"]
        # Second request carries the session_id and the next page
        assert result.params("page") == ["0", "1"]
        assert result.requests[1].param("session_id") == "sess-1"
        assert result.saved_states[-1].page == 2
        assert result.saved_states[-1].session_id == "sess-1"

    def test_resumes_from_saved_page(self) -> None:
        page = ScriptedResponse(json={"page": 3, "page_size": 10, "session_id": "sess-9", "results": []})
        result = _driver().run("engage", [page], resume_state=MixpanelResumeConfig(session_id="sess-9", page=3))
        assert result.raised is None
        assert result.params("page") == ["3"]
        assert result.params("session_id") == ["sess-9"]


class TestSingleRequestEndpoints:
    def test_cohorts_handles_bare_list(self) -> None:
        result = _driver().run("cohorts", [ScriptedResponse(json=[{"id": 1}, {"id": 2}])])
        assert result.raised is None
        assert result.items == [[{"id": 1}, {"id": 2}]]

    def test_annotations_handles_results_wrapper(self) -> None:
        result = _driver().run("annotations", [ScriptedResponse(json={"results": [{"id": 5}]})])
        assert result.raised is None
        assert result.items == [[{"id": 5}]]

    @parameterized.expand(
        [
            (
                "lexicon_schemas_us",
                "lexicon_schemas",
                "us",
                "https://mixpanel.com/api/app/projects/123/schemas",
                None,
                [
                    {
                        "entityType": "event",
                        "name": "Song Played",
                        "schemaJson": {"properties": {"genre": {"type": "string"}}},
                    }
                ],
            ),
            (
                "lexicon_schemas_eu",
                "lexicon_schemas",
                "eu",
                "https://eu.mixpanel.com/api/app/projects/123/schemas",
                None,
                [{"entityType": "profile", "name": "$user", "schemaJson": {"properties": {}}}],
            ),
            (
                "lookup_tables_us",
                "lookup_tables",
                "us",
                "https://api.mixpanel.com/lookup-tables",
                "123",
                [{"id": "00000000-0000-4000-8000-000000000001", "name": "Plans"}],
            ),
            (
                "lookup_tables_in",
                "lookup_tables",
                "in",
                "https://api-in.mixpanel.com/lookup-tables",
                "123",
                [{"id": "00000000-0000-4000-8000-000000000002", "name": "Stores"}],
            ),
        ]
    )
    def test_list_endpoints_read_results_from_the_region_host(
        self,
        _name: str,
        endpoint: str,
        region: Literal["us", "eu", "in"],
        expected_url: str,
        expected_project_param: Optional[str],
        rows: list[dict[str, Any]],
    ) -> None:
        result = _driver(region).run(endpoint, [ScriptedResponse(json={"status": "ok", "results": rows})])
        assert result.raised is None
        assert result.urls[0].split("?", 1)[0] == expected_url
        assert result.params("project_id") == [expected_project_param]
        assert result.items == [rows]

    @parameterized.expand([("lexicon_schemas",), ("lookup_tables",)])
    def test_list_endpoints_yield_nothing_for_empty_results(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json={"status": "ok", "results": []})])
        assert result.raised is None
        assert result.items == []


class TestReportEndpoints:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel("2024-06-04", tick=False):
            yield

    def _funnel_response(self) -> FakeResponse:
        return FakeResponse(
            json_data={
                "meta": {"dates": ["2024-06-03", "2024-06-02"]},
                "data": {
                    "2024-06-03": {"steps": [{"count": 5, "event": "Signup"}], "analysis": {"completion": 5}},
                    "2024-06-02": {
                        "steps": [{"count": 10, "event": "Visit"}, {"count": 4, "event": "Signup"}],
                        "analysis": {"completion": 4},
                    },
                },
            }
        )

    @parameterized.expand([("fresh", None, [7, 9]), ("resumed", 7, [9])])
    def test_funnel_steps_walk_funnels_in_id_order(
        self, _name: str, resume_funnel_id: Optional[int], expected_funnel_ids: list[int]
    ) -> None:
        manager = FakeManager(MixpanelResumeConfig(funnel_id=resume_funnel_id) if resume_funnel_id else None)
        funnel_list = FakeResponse(json_data=[{"funnel_id": 9, "name": "Checkout"}, {"funnel_id": 7, "name": "Signup"}])
        funnel_responses = {7: FakeResponse(json_data={"meta": {"dates": []}, "data": {}}), 9: self._funnel_response()}

        def fake_request(method: str, url: str, **kwargs: Any) -> FakeResponse:
            if url.endswith("/funnels/list"):
                return funnel_list
            return funnel_responses[kwargs["params"]["funnel_id"]]

        with patch.object(mp, "_request", side_effect=fake_request) as mock_request:
            batches = list(mp.get_rows("us", "u", "s", "123", "funnel_steps", LOGGER, manager))  # type: ignore[arg-type]

        query_params = [c.kwargs["params"] for c in mock_request.call_args_list[1:]]
        assert [p["funnel_id"] for p in query_params] == expected_funnel_ids
        assert all((p["from_date"], p["to_date"]) == ("2024-03-06", "2024-06-04") for p in query_params)
        assert [s.funnel_id for s in manager.saved] == expected_funnel_ids
        assert manager.safe_points == (1 if 7 in expected_funnel_ids else 0)
        rows = [row for batch in batches for row in batch]
        assert [(r["funnel_id"], r["funnel_name"], r["date"], r["step_index"], r["event"]) for r in rows] == [
            (9, "Checkout", "2024-06-02", 0, "Visit"),
            (9, "Checkout", "2024-06-02", 1, "Signup"),
            (9, "Checkout", "2024-06-03", 0, "Signup"),
        ]

    def test_funnel_steps_skips_funnel_rejected_with_400_and_resumes_past_it(self) -> None:
        manager = FakeManager()
        funnel_list = FakeResponse(json_data=[{"funnel_id": 9, "name": "Checkout"}, {"funnel_id": 7, "name": "Signup"}])
        rejected = FakeResponse(status_code=400)

        def fake_request(method: str, url: str, **kwargs: Any) -> FakeResponse:
            if url.endswith("/funnels/list"):
                return funnel_list
            if kwargs["params"]["funnel_id"] == 7:
                raise requests.HTTPError("400 Client Error", response=rejected)  # type: ignore[arg-type]
            return self._funnel_response()

        with patch.object(mp, "_request", side_effect=fake_request):
            batches = list(mp.get_rows("us", "u", "s", "123", "funnel_steps", LOGGER, manager))  # type: ignore[arg-type]

        # Funnel 7 is rejected but the resume cursor still advances past it, so funnel 9
        # (and any funnel after a rejected one) still syncs instead of the whole sync aborting.
        assert [s.funnel_id for s in manager.saved] == [7, 9]
        rows = [row for batch in batches for row in batch]
        assert [r["funnel_id"] for r in rows] == [9, 9, 9]

    def test_retention_requests_compounded_retention_and_unnests_cohorts(self) -> None:
        response = FakeResponse(
            json_data={"2024-06-03": {"counts": [8], "first": 8}, "2024-06-02": {"counts": [10, 6], "first": 10}}
        )
        with patch.object(mp, "_request", return_value=response) as mock_request:
            batches = list(mp.get_rows("us", "u", "s", "123", "retention", LOGGER, FakeManager()))  # type: ignore[arg-type]

        params = mock_request.call_args.kwargs["params"]
        assert params["retention_type"] == "compounded"
        assert "born_event" not in params
        assert (params["from_date"], params["to_date"]) == ("2024-03-06", "2024-06-04")
        assert batches == [
            [
                {"date": "2024-06-02", "interval_index": 0, "count": 10, "first": 10},
                {"date": "2024-06-02", "interval_index": 1, "count": 6, "first": 10},
                {"date": "2024-06-03", "interval_index": 0, "count": 8, "first": 8},
            ]
        ]


class TestGetRowsExportWindow:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel("2024-06-04", tick=False):
            yield

    def test_future_cursor_clamps_start_to_today(self) -> None:
        future = int(datetime(2999, 1, 1, tzinfo=UTC).timestamp())
        result = _driver().run(
            "export",
            [_export_answer()],
            should_use_incremental_field=True,
            db_incremental_field_last_value=future,
        )
        assert result.raised is None
        assert result.params("from_date") == ["2024-06-04"]
        assert result.params("to_date") == ["2024-06-04"]


class TestMixpanelSource:
    @parameterized.expand(
        [
            ("export", ["$insert_id", "event", "distinct_id", "time"], "datetime", "time"),
            ("engage", ["$distinct_id"], None, None),
            ("cohorts", ["id"], "datetime", "created"),
            ("annotations", ["id"], None, None),
        ]
    )
    @time_machine.travel("2024-01-01", tick=False)
    def test_source_response_shape(
        self, endpoint: str, primary_keys: list[str], partition_mode: Optional[str], partition_key: Optional[str]
    ) -> None:
        answer = _export_answer() if endpoint == "export" else ScriptedResponse(json={"results": []})
        result = _driver().run(
            endpoint,
            [answer],
            should_use_incremental_field=endpoint == "export",
            db_incremental_field_last_value=date(2024, 1, 1),
        )
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_mode == partition_mode
        assert response.partition_keys == ([partition_key] if partition_key else None)
        assert response.sort_mode == "asc"
