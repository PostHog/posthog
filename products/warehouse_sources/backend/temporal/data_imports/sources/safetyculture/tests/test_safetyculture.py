import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock
from unittest.mock import MagicMock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture import safetyculture
from products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.safetyculture import (
    SafetyCultureResumeConfig,
    _format_modified_after,
    check_access,
    safetyculture_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.settings import (
    ENDPOINTS,
    SAFETYCULTURE_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# The client retries retryable errors 5 times with backoff sleeps — patch the sleep so failure-path
# tests don't actually wait.
SLEEP_PATCH = "tenacity.nap.time.sleep"

BASE_URL = "https://api.safetyculture.io"


def _response(
    items: Optional[list[dict[str, Any]]],
    next_page: Optional[str] = None,
    *,
    raw_body: Any = None,
    status: int = 200,
    url: str = f"{BASE_URL}/feed/users",
) -> Response:
    if raw_body is not None:
        body: Any = raw_body
    else:
        body = {"metadata": {"next_page": next_page, "remaining_records": 0}, "data": items or []}
    resp = Response()
    resp.status_code = status
    resp.url = url
    resp.reason = "OK" if status < 400 else "Error"
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: SafetyCultureResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: Any) -> tuple[list[str], list[dict[str, Any]]]:
    """Wire a mock session; capture each request's url and params AT SEND TIME.

    ``request.url``/``request.params`` are mutated in place across pages (the paginator retargets the
    same request object each page), so snapshot copies when each request is prepared.
    """
    session.headers = {}
    url_snapshots: list[str] = []
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        url_snapshots.append(request.url)
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return url_snapshots, param_snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any) -> Any:
    return safetyculture_source(
        api_token="sc-token",
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestFormatModifiedAfter:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2024, 1, 28, 23, 14, 23, tzinfo=UTC), "2024-01-28T23:14:23.000Z"),
            ("naive_datetime", datetime(2024, 1, 28, 23, 14, 23), "2024-01-28T23:14:23.000Z"),
            ("date", date(2024, 1, 28), "2024-01-28T00:00:00.000Z"),
            ("string_passthrough", "2024-01-28T23:14:23.000Z", "2024-01-28T23:14:23.000Z"),
        ]
    )
    def test_internet_date_time_format(self, _name: str, value: Any, expected: str) -> None:
        # Since 2025-02-01 SafetyCulture rejects timestamps that aren't Internet Date-Time format.
        assert _format_modified_after(value) == expected


class TestInitialRequest:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_static_params_sent_on_first_request(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        urls, params = _wire(session, [_response([{"id": "a"}])])

        _rows(_source("inspections", _make_manager()))

        assert urls[0] == f"{BASE_URL}/feed/inspections"
        assert params[0] == {"archived": "both", "completed": "both"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_params_endpoint_sends_bare_path(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        urls, params = _wire(session, [_response([{"id": "a"}])])

        _rows(_source("users", _make_manager()))

        assert urls[0] == f"{BASE_URL}/feed/users"
        assert params[0] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_first_request_carries_modified_after(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        _, params = _wire(session, [_response([{"id": "a"}])])

        _rows(
            _source(
                "inspections",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 3, 1, tzinfo=UTC),
            )
        )

        assert params[0] == {
            "archived": "both",
            "completed": "both",
            "modified_after": "2024-03-01T00:00:00.000Z",
        }

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_endpoint_never_sends_modified_after(self, MockSession: MagicMock) -> None:
        # The issues feed documents no modified_after — a stale watermark must never leak into it.
        session = MockSession.return_value
        _, params = _wire(session, [_response([{"id": "a"}])])

        _rows(
            _source(
                "issues",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 3, 1, tzinfo=UTC),
            )
        )

        assert "modified_after" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_without_watermark_omits_modified_after(self, MockSession: MagicMock) -> None:
        # First incremental run has no cursor yet — send an unfiltered request, never modified_after=None.
        session = MockSession.return_value
        _, params = _wire(session, [_response([{"id": "a"}])])

        _rows(
            _source(
                "inspections", _make_manager(), should_use_incremental_field=True, db_incremental_field_last_value=None
            )
        )

        assert "modified_after" not in params[0]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_no_next_yields_and_stops(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "a"}, {"id": "b"}], next_page=None)])

        manager = _make_manager()
        rows = _rows(_source("users", manager))

        assert rows == [{"id": "a"}, {"id": "b"}]
        assert session.send.call_count == 1
        # A null next_page ends the feed without persisting resume state.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_next_page_verbatim_and_checkpoints(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        urls, params = _wire(
            session,
            [
                _response([{"id": "a"}], next_page="/feed/users?opaque-cursor=xyz"),
                _response([{"id": "b"}], next_page=None),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("users", manager))

        assert rows == [{"id": "a"}, {"id": "b"}]
        # Page 2 targets the server-issued next_page (resolved to the API host), and carries no
        # re-appended query params.
        assert urls[1] == f"{BASE_URL}/feed/users?opaque-cursor=xyz"
        assert params[1] == {}
        # State is saved after the first page yields, holding the next page to fetch.
        manager.save_state.assert_called_once_with(
            SafetyCultureResumeConfig(next_page=f"{BASE_URL}/feed/users?opaque-cursor=xyz")
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_offhost_next_page_rejected_before_send(self, MockSession: MagicMock) -> None:
        # An absolute, off-host metadata.next_page is followed verbatim, so it must be rejected by the
        # client's host pin before the Bearer token can be replayed to an attacker-controlled host.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "a"}], next_page="https://evil.example/feed/users?opaque-cursor=xyz"),
                _response([{"id": "b"}], next_page=None),
            ],
        )

        with pytest.raises(ValueError, match="disallowed host"):
            _rows(_source("users", _make_manager()))

        # Only the on-host first page went out; the off-host next_page never reached the network.
        assert session.send.call_count == 1

    @parameterized.expand(
        [
            ("relative_saved_path", "/feed/users?opaque-cursor=xyz"),
            ("absolute_saved_url", f"{BASE_URL}/feed/users?opaque-cursor=xyz"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_next_page(self, _name: str, saved: str, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        urls, _ = _wire(session, [_response([{"id": "b"}], next_page=None)])

        # A relative path (historic save) and an absolute URL (new save) both resolve to the same
        # request, and the initial unfiltered page is never fetched.
        manager = _make_manager(SafetyCultureResumeConfig(next_page=saved))
        rows = _rows(_source("users", manager))

        assert rows == [{"id": "b"}]
        assert session.send.call_count == 1
        assert urls[0] == f"{BASE_URL}/feed/users?opaque-cursor=xyz"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing_and_no_checkpoint(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], next_page=None)])

        manager = _make_manager()
        assert _rows(_source("users", manager)) == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_with_lingering_next_page_terminates(self, MockSession: MagicMock) -> None:
        # A lingering next_page on an empty page must not loop forever.
        session = MockSession.return_value
        _wire(session, [_response([], next_page="/feed/users?opaque-cursor=xyz")])

        manager = _make_manager()
        assert _rows(_source("users", manager)) == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @parameterized.expand(
        [
            ("null_next_page", {"metadata": {"next_page": None}, "data": [{"id": "a"}]}),
            ("missing_metadata", {"data": [{"id": "a"}]}),
            ("empty_next_page", {"metadata": {"next_page": ""}, "data": [{"id": "a"}]}),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_terminal_next_page_shapes_stop(self, _name: str, body: dict, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, raw_body=body)])

        manager = _make_manager()
        rows = _rows(_source("users", manager))

        assert rows == [{"id": "a"}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(SLEEP_PATCH, return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_raise_retryable_after_exhausting(
        self, _name: str, status: int, MockSession: MagicMock, _sleep: MagicMock
    ) -> None:
        session = MockSession.return_value
        _wire(session, lambda *a, **k: _response([{"id": "a"}], status=status))

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("users", _make_manager()))
        # Retried up to the client's attempt cap before giving up.
        assert session.send.call_count == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_for_status(self, _name: str, status: int, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, raw_body={}, status=status)])

        with pytest.raises(requests.HTTPError):
            _rows(_source("users", _make_manager()))
        # A permanent client error is not retried.
        assert session.send.call_count == 1

    @parameterized.expand(
        [
            ("non_dict_body", [{"id": "a"}]),
            ("non_list_data", {"metadata": {}, "data": {"id": "a"}}),
            ("dict_without_data", {"metadata": {}}),
        ]
    )
    @mock.patch(SLEEP_PATCH, return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unexpected_200_payload_is_retryable(
        self, _name: str, body: Any, MockSession: MagicMock, _sleep: MagicMock
    ) -> None:
        # A 200 whose body isn't the documented {"metadata", "data": [...]} envelope is retried.
        session = MockSession.return_value
        _wire(session, lambda *a, **k: _response(None, raw_body=body))

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("users", _make_manager()))
        assert session.send.call_count == 5

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bearer_token_redacted_from_errors(self, MockSession: MagicMock) -> None:
        # The framework auth scrubs the token from any raised error message.
        session = MockSession.return_value
        _wire(session, [_response(None, raw_body={}, status=401, url=f"{BASE_URL}/feed/users")])

        with pytest.raises(requests.HTTPError) as exc:
            _rows(_source("users", _make_manager()))
        assert "sc-token" not in str(exc.value)


class TestCheckAccess:
    def _patch_session(self, response: Any) -> Any:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return mock.patch.object(safetyculture, "make_tracked_session", return_value=session)

    @parameterized.expand(
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "SafetyCulture returned HTTP 500"),
        ]
    )
    def test_status_mapping(self, status: int, ok: bool, expected_status: int, expected_message: str | None) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        with self._patch_session(response):
            assert check_access("sc-token") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self) -> None:
        with self._patch_session(requests.ConnectionError("boom")):
            status, message = check_access("sc-token")
        assert status == 0
        assert message is not None and "boom" in message

    def test_probes_the_given_feed_path(self) -> None:
        session = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.ok = True
        session.get.return_value = response
        with mock.patch.object(safetyculture, "make_tracked_session", return_value=session):
            check_access("sc-token", "/feed/inspections")
        assert session.get.call_args.args[0] == f"{BASE_URL}/feed/inspections"


class TestSafetyCultureSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _source(endpoint, _make_manager())
        config = SAFETYCULTURE_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_incremental_endpoints_match_documented_modified_after_support(self) -> None:
        # Only these four feeds document a server-side modified_after filter; flipping any other
        # endpoint to incremental would silently ship a full-refresh-cost "incremental" sync.
        incremental = {name for name, config in SAFETYCULTURE_ENDPOINTS.items() if config.supports_incremental}
        assert incremental == {"inspections", "inspection_items", "templates", "actions"}
