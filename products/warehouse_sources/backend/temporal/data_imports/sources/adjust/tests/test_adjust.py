from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract import validate_incremental_sync
from products.warehouse_sources.backend.temporal.data_imports.sources.adjust import adjust
from products.warehouse_sources.backend.temporal.data_imports.sources.adjust.adjust import (
    MAX_HISTORY_DAYS,
    MAX_PAGES_PER_WINDOW,
    AdjustCredentialsError,
    AdjustResumeConfig,
    AdjustRetryableError,
    build_report_params,
    date_windows,
    extract_rows,
    get_rows,
    next_page_url,
    parse_app_tokens,
    resolve_start_date,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adjust.settings import ADJUST_REPORTS
from products.warehouse_sources.backend.temporal.data_imports.sources.adjust.source import AdjustSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.adjust import AdjustSourceConfig

TODAY = date(2024, 6, 30)


class _FakeResponse:
    def __init__(
        self, status_code: int = 200, json_data: Any = None, text: str = "", reason: str = "Bad Request"
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.reason = reason

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data


class _FakeSession:
    """Returns queued responses in order and records every URL requested."""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.requested_urls: list[str] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.requested_urls.append(url)
        return self._responses.pop(0)


class _FakeResumeManager(ResumableSourceManager[AdjustResumeConfig]):
    def __init__(self, state: AdjustResumeConfig | None = None) -> None:
        self.state = state
        self.saved: list[AdjustResumeConfig] = []

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> AdjustResumeConfig | None:
        return self.state

    def save_state(self, data: AdjustResumeConfig) -> None:
        self.saved.append(data)


def _scripted_page(rows: list[dict[str, Any]], next_url: str | None = None) -> ScriptedResponse:
    pagination = {"next": next_url} if next_url else None
    return ScriptedResponse(json={"rows": rows, "totals": {}, "pagination": pagination})


def _driver(app_tokens: str | None = None) -> SourceDriver:
    return SourceDriver(AdjustSource(), AdjustSourceConfig(api_token="token", app_tokens=app_tokens))


def _run_get_rows(
    session: _FakeSession,
    report: str = "daily_report",
    manager: _FakeResumeManager | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    app_tokens: str | None = None,
) -> list[list[dict[str, Any]]]:
    resume_manager = manager if manager is not None else _FakeResumeManager()
    with (
        mock.patch.object(adjust, "make_tracked_session", return_value=session),
        mock.patch.object(adjust, "_today", return_value=TODAY),
    ):
        return list(
            get_rows(
                api_token="token",
                app_tokens=app_tokens,
                report=report,
                logger=mock.MagicMock(),
                resumable_source_manager=resume_manager,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            )
        )


class TestParseAppTokens:
    @parameterized.expand(
        [
            ("blank", None, []),
            ("empty_string", "", []),
            ("single", "abc123", ["abc123"]),
            ("whitespace_and_trailing_comma", " abc123 , def456 ,", ["abc123", "def456"]),
        ]
    )
    def test_parses(self, _name: str, raw: str | None, expected: list[str]) -> None:
        assert parse_app_tokens(raw) == expected

    @parameterized.expand([("space", "abc 123"), ("query_injection", "abc&metrics=cost"), ("path", "abc/def")])
    def test_rejects_malformed_tokens(self, _name: str, raw: str) -> None:
        # A malformed token must fail loudly rather than silently narrowing the report or leaking
        # extra query params into the request.
        with pytest.raises(AdjustCredentialsError):
            parse_app_tokens(raw)


class TestBuildReportParams:
    def test_app_token_filter_included_when_configured(self) -> None:
        params = build_report_params("daily_report", date(2024, 1, 1), date(2024, 1, 2), ["abc123", "def456"])
        assert params["app_token__in"] == "abc123,def456"

    @parameterized.expand([(name,) for name in ADJUST_REPORTS])
    def test_every_report_groups_by_day(self, name: str) -> None:
        # `day` is the incremental cursor and partition key, so every report must return it.
        assert "day" in ADJUST_REPORTS[name].dimensions
        assert "day" in build_report_params(name, date(2024, 1, 1), date(2024, 1, 2), [])["dimensions"]

    @parameterized.expand([(name,) for name in ADJUST_REPORTS])
    def test_primary_keys_are_requested_dimensions(self, name: str) -> None:
        # A primary key that isn't a requested dimension would be absent from every row, so merges
        # would collapse the whole table onto null keys.
        config = ADJUST_REPORTS[name]
        unpivoted_keys = {"event_slug"} if config.event_metrics else set()
        assert set(config.primary_keys) <= set(config.dimensions) | unpivoted_keys


class TestRequest:
    @parameterized.expand([(429,), (500,), (502,), (503,)])
    def test_throttle_and_5xx_are_retryable(self, status: int) -> None:
        with mock.patch.object(adjust, "_today", return_value=TODAY):
            result = _driver().run(
                "daily_report",
                always(ScriptedResponse(status=status)),
                incremental_field="day",
                db_incremental_field_last_value="2024-06-30",
            )

        assert isinstance(result.raised, AdjustRetryableError)
        assert len(result.requests) > 1

    @parameterized.expand([(400,), (401,), (403,), (404,), (422,)])
    def test_client_errors_raise_http_error_with_url(self, status: int) -> None:
        with mock.patch.object(adjust, "_today", return_value=TODAY):
            result = _driver().run(
                "daily_report",
                # A JSON body that is not an object: the error message must still build.
                [ScriptedResponse(status=status, body=b"null")],
                incremental_field="day",
                db_incremental_field_last_value="2024-06-30",
            )

        assert isinstance(result.raised, requests.HTTPError)
        # get_non_retryable_errors matches on the status text plus the host, so both must be present.
        assert str(status) in str(result.raised)
        assert "https://automate.adjust.com" in str(result.raised)

    @parameterized.expand(
        [
            ("nested_error", {"error": {"message": "Unknown metric: bogus"}}, "Unknown metric: bogus"),
            ("flat_error", {"error": "Invalid app_token"}, "Invalid app_token"),
            ("message_key", {"message": "Access denied"}, "Access denied"),
        ]
    )
    def test_error_body_detail_is_surfaced(self, _name: str, body: dict[str, Any], expected: str) -> None:
        with mock.patch.object(adjust, "_today", return_value=TODAY):
            result = _driver().run(
                "daily_report",
                [ScriptedResponse(status=400, json=body)],
                incremental_field="day",
                db_incremental_field_last_value="2024-06-30",
            )

        assert isinstance(result.raised, requests.HTTPError)
        assert expected in str(result.raised)

    def test_non_json_error_body_does_not_break_error_construction(self) -> None:
        with mock.patch.object(adjust, "_today", return_value=TODAY):
            result = _driver().run(
                "daily_report",
                [ScriptedResponse(status=400, body=b"<html>")],
                incremental_field="day",
                db_incremental_field_last_value="2024-06-30",
            )

        assert isinstance(result.raised, requests.HTTPError)

    def test_non_dict_payload_raises(self) -> None:
        with mock.patch.object(adjust, "_today", return_value=TODAY):
            result = _driver().run(
                "daily_report",
                [ScriptedResponse(json=[{"day": "2024-01-01"}])],
                incremental_field="day",
                db_incremental_field_last_value="2024-06-30",
            )

        assert isinstance(result.raised, ValueError)


class TestExtractRows:
    @parameterized.expand(
        [
            ("rows_key", {"rows": [{"day": "2024-01-01"}]}, 1),
            ("data_key", {"data": [{"day": "2024-01-01"}]}, 1),
            ("empty_rows", {"rows": []}, 0),
            ("missing", {"totals": {}}, 0),
            ("rows_not_a_list", {"rows": {"day": "2024-01-01"}}, 0),
        ]
    )
    def test_extracts(self, _name: str, payload: dict[str, Any], expected: int) -> None:
        assert len(extract_rows(payload)) == expected


class TestNextPageUrl:
    @parameterized.expand(
        [
            ("absolute_next", {"pagination": {"next": "https://automate.adjust.com/x?page=2"}}, True),
            ("next_url_alias", {"pagination": {"next_url": "https://automate.adjust.com/x?page=2"}}, True),
            ("null_pagination", {"pagination": None}, False),
            ("missing_pagination", {}, False),
            ("empty_next", {"pagination": {"next": ""}}, False),
            # The mechanism is undocumented, so anything that isn't a link on the Adjust API host
            # terminates the loop instead of being guessed at.
            ("relative_next", {"pagination": {"next": "/report?page=2"}}, False),
            ("numeric_next", {"pagination": {"next": 2}}, False),
            # The credentialed session follows this URL, so an off-host or non-HTTPS link — which
            # could exfiltrate the Bearer token or hit an internal host — is rejected.
            ("off_host_next", {"pagination": {"next": "https://evil.example.com/x?page=2"}}, False),
            ("subdomain_spoof_next", {"pagination": {"next": "https://automate.adjust.com.evil.com/x"}}, False),
            ("http_scheme_next", {"pagination": {"next": "http://automate.adjust.com/x?page=2"}}, False),
        ]
    )
    def test_only_adjust_host_links_are_followed(self, _name: str, payload: dict[str, Any], expected: bool) -> None:
        assert (next_page_url(payload) is not None) is expected


class TestDateHelpers:
    @parameterized.expand(
        [
            ("date", date(2024, 1, 5), date(2024, 1, 5)),
            ("naive_datetime", datetime(2024, 1, 5, 23, 0), date(2024, 1, 5)),
            ("aware_datetime", datetime(2024, 1, 5, 23, 0, tzinfo=UTC), date(2024, 1, 5)),
            ("iso_date_string", "2024-01-05", date(2024, 1, 5)),
            ("iso_datetime_string", "2024-01-05T12:34:56Z", date(2024, 1, 5)),
            ("garbage", "not-a-date", None),
            ("none", None, None),
        ]
    )
    def test_to_date(self, _name: str, value: Any, expected: date | None) -> None:
        assert adjust._to_date(value) == expected

    @parameterized.expand(
        [
            ("exact_multiple", date(2024, 1, 1), date(2024, 1, 20), 10, [(1, 10), (11, 20)]),
            ("partial_last_window", date(2024, 1, 1), date(2024, 1, 15), 10, [(1, 10), (11, 15)]),
            ("single_day", date(2024, 1, 1), date(2024, 1, 1), 10, [(1, 1)]),
        ]
    )
    def test_date_windows(
        self, _name: str, start: date, end: date, window: int, expected: list[tuple[int, int]]
    ) -> None:
        assert date_windows(start, end, window) == [(date(2024, 1, a), date(2024, 1, b)) for a, b in expected]

    def test_date_windows_empty_when_start_after_end(self) -> None:
        assert date_windows(date(2024, 2, 1), date(2024, 1, 1)) == []


class TestResolveStartDate:
    def test_full_refresh_starts_at_the_history_cap(self) -> None:
        assert resolve_start_date(False, None, TODAY) == TODAY - adjust.timedelta(days=MAX_HISTORY_DAYS)


class TestGetRows:
    def test_unknown_report_raises(self) -> None:
        with pytest.raises(ValueError):
            _run_get_rows(_FakeSession([]), report="nope")

    def test_pagination_stops_at_the_page_cap(self) -> None:
        # A next link that never clears would otherwise loop forever.
        looping = "https://automate.adjust.com/reports-service/report?page=next"
        with mock.patch.object(adjust, "_today", return_value=TODAY):
            result = _driver().run(
                "daily_report",
                always(_scripted_page([{"day": "2024-06-30"}], next_url=looping)),
                incremental_field="day",
                db_incremental_field_last_value="2024-06-30",
            )

        assert result.raised is None
        assert len(result.items) == MAX_PAGES_PER_WINDOW
        assert len(result.requests) == MAX_PAGES_PER_WINDOW
        assert result.params("page") == [None, *["next"] * (MAX_PAGES_PER_WINDOW - 1)]

    def test_resume_skips_windows_already_completed(self) -> None:
        with mock.patch.object(adjust, "_today", return_value=TODAY):
            result = _driver().run(
                "daily_report",
                [_scripted_page([{"day": "2024-06-05"}]) for _ in range(2)],
                resume_state=AdjustResumeConfig(next_start_date="2024-05-28"),
                incremental_field="day",
                db_incremental_field_last_value="2024-05-01",
            )

        assert result.raised is None
        assert result.params("date_period") == [
            "2024-05-28:2024-06-26",
            "2024-06-27:2024-06-30",
        ]

    @parameterized.expand(
        [
            ("daily_report", "2024-06-27"),
            ("retention_report", "2024-05-30"),
            ("skad_report", "2024-05-26"),
        ]
    )
    def test_incremental_lookback_covers_the_report_revision_window(self, report: str, expected_start: str) -> None:
        # Cohort and SKAN figures keep changing for weeks, so a short lookback would freeze them
        # at their first, immature value.
        with mock.patch.object(adjust, "_today", return_value=TODAY):
            result = _driver().run(
                report,
                always(_scripted_page([])),
                incremental_field="day",
                db_incremental_field_last_value="2024-06-30",
            )

        assert result.raised is None
        assert (result.params("date_period")[0] or "").startswith(f"{expected_start}:")

    def test_event_report_unpivots_event_metrics_in_day_order(self) -> None:
        catalog = [
            {"id": "purchase", "name": "Purchase", "is_skad_event": False},
            {"id": "signup", "name": "Sign up", "is_skad_event": False},
            {"id": "skad_purchase", "name": "SKAN purchase", "is_skad_event": True},
        ]
        dims = {"app": "App", "app_token": "abc123", "partner_name": "Organic"}
        with (
            mock.patch.object(adjust, "_today", return_value=TODAY),
            mock.patch.object(adjust, "MAX_EVENT_METRICS_PER_REQUEST", 1),
        ):
            result = _driver(app_tokens="abc123").run(
                "event_report",
                [
                    ScriptedResponse(json=catalog),
                    _scripted_page(
                        [
                            {"day": "2024-06-29", **dims, "purchase_events": "2"},
                            {"day": "2024-06-30", **dims, "purchase_events": "0"},
                        ]
                    ),
                    _scripted_page([{"day": "2024-06-29", **dims, "signup_events": "5"}]),
                ],
                incremental_field="day",
                db_incremental_field_last_value="2024-06-30",
            )

        assert result.raised is None
        assert result.requests[0].path == "/reports-service/events"
        assert result.requests[0].param("app_token__in") == "abc123"
        assert result.params("metrics") == [None, "purchase_events", "signup_events"]
        assert result.items == [
            [
                {**dims, "day": "2024-06-29", "event_slug": "purchase", "event_name": "Purchase", "events": "2"},
                {**dims, "day": "2024-06-29", "event_slug": "signup", "event_name": "Sign up", "events": "5"},
            ]
        ]

    @parameterized.expand([("no_content", ScriptedResponse(status=204)), ("empty_list", ScriptedResponse(json=[]))])
    def test_event_report_with_empty_catalog_requests_no_report(self, _name: str, catalog: ScriptedResponse) -> None:
        with mock.patch.object(adjust, "_today", return_value=TODAY):
            result = _driver().run("event_report", [catalog], incremental_field="day")

        assert result.raised is None
        assert len(result.requests) == 1
        assert result.items == []

    def test_exhausted_throttle_surfaces_as_retryable_without_a_second_retry_layer(self) -> None:
        # The tracked session owns 429/5xx retries. Anything that reaches get_rows has already been
        # retried, so it must propagate for Temporal to retry the job rather than being re-looped
        # here (which would multiply the request count against Adjust's rate limit).
        with mock.patch.object(adjust, "_today", return_value=TODAY):
            result = _driver().run(
                "daily_report",
                always(ScriptedResponse(status=429)),
                incremental_field="day",
                db_incremental_field_last_value="2024-06-30",
            )

        assert isinstance(result.raised, AdjustRetryableError)
        assert len(result.requests) == 4


class TestValidateCredentials:
    def _validate(self, response: ScriptedResponse, app_tokens: str | None = None) -> bool:
        with scripted_network(always(response)):
            return validate_credentials("token", app_tokens)

    def test_probe_is_minimal_and_includes_app_token_filter(self) -> None:
        with scripted_network([ScriptedResponse(json={"rows": []})]) as network:
            validate_credentials("token", "abc123")

        assert network.requests_log[0].param("dimensions") == "day"
        assert network.requests_log[0].param("metrics") == "installs"
        assert network.requests_log[0].param("app_token__in") == "abc123"

    @parameterized.expand([(429,), (500,), (503,)])
    def test_throttle_and_5xx_are_retryable(self, status: int) -> None:
        with pytest.raises(AdjustRetryableError):
            self._validate(ScriptedResponse(status=status))

    @parameterized.expand([(401, "API token"), (403, "denied access"), (400, "app tokens"), (404, "app tokens")])
    def test_rejections_are_credential_errors_with_specific_messages(self, status: int, expected: str) -> None:
        with pytest.raises(AdjustCredentialsError) as exc:
            self._validate(ScriptedResponse(status=status))
        assert expected in str(exc.value)

    def test_unexpected_status_does_not_blame_the_token(self) -> None:
        with pytest.raises(AdjustCredentialsError) as exc:
            self._validate(ScriptedResponse(status=418))
        assert "unexpected response (HTTP 418)" in str(exc.value)

    def test_malformed_app_token_fails_before_any_request(self) -> None:
        with scripted_network([]) as network:
            with pytest.raises(AdjustCredentialsError):
                validate_credentials("token", "abc 123")
        assert network.requests_log == []

    def test_transport_errors_propagate(self) -> None:
        def reset_connection(_request: RecordedRequest) -> ScriptedResponse:
            raise ConnectionResetError("boom")

        with scripted_network(reset_connection):
            with pytest.raises(requests.ConnectionError):
                validate_credentials("token")


class TestAdjustSource:
    @parameterized.expand([(name,) for name in ADJUST_REPORTS])
    def test_source_response_shape(self, name: str) -> None:
        script = [ScriptedResponse(json=[])] if ADJUST_REPORTS[name].event_metrics else always(_scripted_page([]))
        with mock.patch.object(adjust, "_today", return_value=TODAY):
            result = _driver().run(
                name,
                script,
                incremental_field="day",
                db_incremental_field_last_value="2024-06-30",
            )

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == name
        assert response.primary_keys == ADJUST_REPORTS[name].primary_keys
        # Windows are walked oldest-first and each report is sorted by day, so rows arrive ascending.
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["day"]
        # Blank dimension values (e.g. organic traffic with no campaign) can collide, but that's
        # expected for report data and must not block incremental syncing (the only incremental
        # field these reports offer is `day`) - regression test for the schema-wide incremental
        # sync outage this caused when has_duplicate_primary_keys was set unconditionally.
        assert not response.has_duplicate_primary_keys
        validate_incremental_sync(True, response)

    def test_items_streams_rows(self) -> None:
        with mock.patch.object(adjust, "_today", return_value=TODAY):
            result = _driver().run(
                "daily_report",
                [_scripted_page([{"day": "2024-06-30", "installs": "3"}])],
                incremental_field="day",
                db_incremental_field_last_value="2024-06-30",
            )

        assert result.raised is None
        assert result.items == [[{"day": "2024-06-30", "installs": "3"}]]
