import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.partnerize import (
    DEFAULT_START_DATE,
    PARTNERIZE_BASE_URL,
    PartnerizeResumeConfig,
    _format_start_date,
    _make_unwrap,
    partnerize_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.settings import (
    ENDPOINTS,
    PARTNERIZE_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the partnerize module.
PARTNERIZE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.partnerize.make_tracked_session"
)
# Backoff sleeps happen inside tenacity; patch its clock so retry tests don't actually wait.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(body: Any, *, status: int = 200, reason: str = "OK") -> Response:
    resp = Response()
    resp.status_code = status
    resp.reason = reason
    resp.url = PARTNERIZE_BASE_URL
    resp.headers["Content-Type"] = "application/json"
    resp._content = b"" if body is None else json.dumps(body).encode()
    return resp


def _make_manager(resume_state: PartnerizeResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _saved(manager: mock.MagicMock) -> list[PartnerizeResumeConfig]:
    return [call.args[0] for call in manager.save_state.call_args_list]


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[str], list[dict[str, Any]]]:
    """Wire a mock session, snapshotting each request's URL and params AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so a copy is taken per page.
    """
    session.headers = {}
    url_snapshots: list[str] = []
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        url_snapshots.append(request.url)
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return url_snapshots, param_snapshots


def _run(
    endpoint: str,
    manager: mock.MagicMock,
    **kwargs: Any,
) -> Any:
    return partnerize_source(
        application_key="app-key",
        user_api_key="api-key",
        publisher_id="111111l92",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _conversion_page(ids: list[str], limit: int) -> Response:
    return _response(
        {
            "conversions": [{"conversion_data": {"conversion_id": i}} for i in ids],
            "limit": limit,
            "count": len(ids),
        }
    )


class TestFormatStartDate:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2020, 3, 8, 17, 18, 33, tzinfo=UTC), "2020-03-08T17:18:33Z"),
            ("naive_datetime", datetime(2020, 3, 8, 17, 18, 33), "2020-03-08T17:18:33Z"),
            ("date", date(2020, 3, 8), "2020-03-08T00:00:00Z"),
            # Watermarks read back from the warehouse arrive as strings in Partnerize's own format.
            ("api_format_string", "2020-03-08 17:18:33", "2020-03-08T17:18:33Z"),
            ("iso_string", "2020-03-08T17:18:33+00:00", "2020-03-08T17:18:33Z"),
            ("unparseable_string", "not a date at all 12345 67890", DEFAULT_START_DATE),
            ("none", None, DEFAULT_START_DATE),
        ]
    )
    def test_coerces_watermark_to_iso_z(self, _name: str, value: Any, expected: str) -> None:
        assert _format_start_date(value) == expected


class TestUnwrap:
    def test_strips_single_key_item_wrapper(self) -> None:
        unwrap = _make_unwrap("campaign")
        assert unwrap({"campaign": {"campaign_id": "10l176", "title": "Demo"}}) == {
            "campaign_id": "10l176",
            "title": "Demo",
        }

    def test_missing_wrapper_key_yields_item_as_is(self) -> None:
        # Defensive: if the API returns flat rows, they pass through unmodified.
        unwrap = _make_unwrap("conversion_data")
        assert unwrap({"conversion_id": "111111l314"}) == {"conversion_id": "111111l314"}

    def test_no_item_key_yields_item_as_is(self) -> None:
        unwrap = _make_unwrap(None)
        assert unwrap({"id": 1}) == {"id": 1}


class TestReportRows:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_by_offset_and_saves_state_after_yield(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _, params = _wire(session, [_conversion_page(["a", "b"], limit=2), _conversion_page(["c"], limit=2)])
        manager = _make_manager()

        rows = _rows(_run("conversions", manager))

        assert [r["conversion_id"] for r in rows] == ["a", "b", "c"]
        assert [p["offset"] for p in params] == [0, 2]
        # State is saved after the full first page is yielded, then the short page terminates.
        assert [s.offset for s in _saved(manager)] == [2]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_stops_without_saving(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_conversion_page(["a"], limit=300)])
        manager = _make_manager()

        rows = _rows(_run("conversions", manager))

        assert len(rows) == 1
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _, params = _wire(session, [_conversion_page([], limit=300)])
        manager = _make_manager(PartnerizeResumeConfig(offset=600))

        _rows(_run("conversions", manager))

        assert params[0]["offset"] == 600

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_uses_default_start_date(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _, params = _wire(session, [_conversion_page([], limit=300)])

        _rows(_run("conversions", _make_manager()))

        assert params[0]["start_date"] == DEFAULT_START_DATE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_windows_from_watermark(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _, params = _wire(session, [_conversion_page([], limit=300)])

        _rows(
            _run(
                "conversions",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value="2024-05-01 12:00:00",
                incremental_field="conversion_time",
            )
        )

        assert params[0]["start_date"] == "2024-05-01T12:00:00Z"
        # The default window filters on the conversion time, no date_type override needed.
        assert "date_type" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_last_modified_cursor_sets_date_type(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _, params = _wire(session, [_conversion_page([], limit=300)])

        _rows(
            _run(
                "conversions",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value="2024-05-01 12:00:00",
                incremental_field="last_modified",
            )
        )

        assert params[0]["date_type"] == "last_updated"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_report_url_contains_publisher_id(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        urls, _ = _wire(session, [_conversion_page([], limit=300)])

        _rows(_run("conversions", _make_manager()))

        assert urls[0] == f"{PARTNERIZE_BASE_URL}/reporting/report_publisher/publisher/111111l92/conversion.json"

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_is_retried_then_reraises(
        self, MockSession: mock.MagicMock, _sleep: mock.MagicMock
    ) -> None:
        # A 200 body without the data key is an unexpected shape; the request is reissued and, if it
        # never recovers, surfaces as a retryable error after the attempt cap.
        session = MockSession.return_value
        _wire(session, [_response({"count": 0})] * 5)

        with pytest.raises(RESTClientRetryableError):
            _rows(_run("conversions", _make_manager()))
        assert session.send.call_count == 5

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_data_is_retried_then_reraises(self, MockSession: mock.MagicMock, _sleep: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"conversions": {"unexpected": "object"}})] * 5)

        with pytest.raises(RESTClientRetryableError):
            _rows(_run("conversions", _make_manager()))
        assert session.send.call_count == 5

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_dict_body_is_retried_then_reraises(self, MockSession: mock.MagicMock, _sleep: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response(["unexpected"])] * 5)

        with pytest.raises(RESTClientRetryableError):
            _rows(_run("conversions", _make_manager()))
        assert session.send.call_count == 5

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_malformed_body_then_valid_recovers(self, MockSession: mock.MagicMock, _sleep: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response(["glitch"]), _conversion_page(["a"], limit=300)])

        rows = _rows(_run("conversions", _make_manager()))

        assert [r["conversion_id"] for r in rows] == ["a"]
        assert session.send.call_count == 2

    @parameterized.expand([("rate_limited", 429, "Too Many Requests"), ("server_error", 503, "Service Unavailable")])
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_retries_then_raises(
        self, _name: str, status: int, reason: str, MockSession: mock.MagicMock, _sleep: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}, status=status, reason=reason)] * 5)

        with pytest.raises(RESTClientRetryableError):
            _rows(_run("conversions", _make_manager()))
        assert session.send.call_count == 5

    @parameterized.expand(
        [("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden"), ("not_found", 404, "Not Found")]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_raises_http_error_without_retry(
        self, _name: str, status: int, reason: str, MockSession: mock.MagicMock
    ) -> None:
        # 401/403/404 are credential/permission failures — never retried, surfaced as an HTTPError
        # whose message carries the stable status text that get_non_retryable_errors matches on.
        session = MockSession.return_value
        _wire(session, [_response({"error": "denied"}, status=status, reason=reason)])

        with pytest.raises(requests.HTTPError):
            _rows(_run("conversions", _make_manager()))
        assert session.send.call_count == 1


class TestListRows:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_hypermedia_next_page_and_saves_state(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        next_url = f"{PARTNERIZE_BASE_URL}/reference/country?page=2"
        urls, _ = _wire(
            session,
            [
                _response(
                    {
                        "countries": [{"country": {"ref_country_id": 1}}],
                        "hypermedia": {"pagination": {"next_page": next_url}},
                    }
                ),
                _response({"countries": [{"country": {"ref_country_id": 2}}]}),
            ],
        )
        manager = _make_manager()

        rows = _rows(_run("countries", manager))

        assert [r["ref_country_id"] for r in rows] == [1, 2]
        assert urls[1] == next_url
        assert [s.next_url for s in _saved(manager)] == [next_url]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_relative_next_page_is_resolved_against_base(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        urls, _ = _wire(
            session,
            [
                _response(
                    {
                        "campaigns": [{"campaign": {"campaign_id": "10l1"}}],
                        "hypermedia": {"pagination": {"next_page": "/user/publisher/111111l92/campaign/a?page=2"}},
                    }
                ),
                _response({"campaigns": []}),
            ],
        )

        _rows(_run("campaigns", _make_manager()))

        assert urls[1] == f"{PARTNERIZE_BASE_URL}/user/publisher/111111l92/campaign/a?page=2"

    @parameterized.expand(
        [
            ("different_host", "https://evil.example.com/steal"),
            ("lookalike_prefix", "https://api.partnerize.com.evil.example.com/steal"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_host_next_page_terminates_without_following(
        self, _name: str, next_page: str, MockSession: mock.MagicMock
    ) -> None:
        # The session carries the Basic auth header, so a tampered next_page pointing off-host (a
        # different host, or a lookalike that only prefixes the base) must not be followed (SSRF
        # guard). The first page's rows still surface; the cursor is not followed and not saved.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(
                    {
                        "countries": [{"country": {"ref_country_id": 1}}],
                        "hypermedia": {"pagination": {"next_page": next_page}},
                    }
                )
            ],
        )
        manager = _make_manager()

        rows = _rows(_run("countries", manager))

        assert [r["ref_country_id"] for r in rows] == [1]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_stops_without_saving(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"countries": [{"country": {"ref_country_id": 1}}]})])
        manager = _make_manager()

        rows = _rows(_run("countries", manager))

        assert len(rows) == 1
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_next_url(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        resume_url = f"{PARTNERIZE_BASE_URL}/reference/country?page=5"
        urls, _ = _wire(session, [_response({"countries": []})])
        manager = _make_manager(PartnerizeResumeConfig(next_url=resume_url))

        _rows(_run("countries", manager))

        assert urls[0] == resume_url


class TestPartnerizeSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _run(endpoint, _make_manager())
        config = PARTNERIZE_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.kind == "report":
            # The reports document no ordering guarantee, so the watermark only commits on completion.
            assert response.sort_mode == "desc"
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.sort_mode == "asc"
            assert response.partition_mode is None


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            (
                "unauthorized",
                401,
                False,
                "Invalid Partnerize API credentials. Check your user application key and user API key.",
            ),
            ("forbidden", 403, False, "Your Partnerize credentials do not have access to publisher '111111l92'."),
            ("not_found", 404, False, "Your Partnerize credentials do not have access to publisher '111111l92'."),
            ("server_error", 500, False, "Partnerize returned HTTP 500"),
        ]
    )
    @mock.patch(PARTNERIZE_SESSION_PATCH)
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: mock.MagicMock,
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("app-key", "api-key", "111111l92") == (expected_valid, expected_message)

    @mock.patch(PARTNERIZE_SESSION_PATCH)
    def test_connection_error_is_swallowed(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        valid, message = validate_credentials("app-key", "api-key", "111111l92")
        assert valid is False
        assert message == "Could not validate Partnerize credentials"
