import json
import base64
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.xmatters.settings import XMATTERS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.xmatters.xmatters import (
    PAGE_SIZE,
    XmattersResumeConfig,
    _base_url,
    _build_params,
    _format_incremental_value,
    _get_headers,
    is_valid_subdomain,
    validate_credentials,
    xmatters_source,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the xmatters module.
XMATTERS_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.xmatters.xmatters.make_tracked_session"
)


def _response(items: list[dict[str, Any]], next_url: Optional[str] = None) -> Response:
    body: dict[str, Any] = {"count": len(items), "total": len(items), "data": items}
    if next_url is not None:
        body["links"] = {"next": next_url}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: Optional[XmattersResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared instead of inspecting it after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return xmatters_source(
        "acme", "svc", "secret", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            (date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("already-a-cursor", "already-a-cursor"),
        ],
    )
    def test_format(self, value: Any, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestSubdomainValidation:
    @pytest.mark.parametrize("subdomain", ["acme", "acme-corp", "a", "acme123", "123acme"])
    def test_valid_subdomains(self, subdomain: str) -> None:
        assert is_valid_subdomain(subdomain) is True
        assert _base_url(subdomain) == f"https://{subdomain}.xmatters.com/api/xm/1"

    # An editor-controlled subdomain like `attacker.example/` would make the worker send its
    # requests (and Basic auth header) to an arbitrary host instead of *.xmatters.com (SSRF).
    @pytest.mark.parametrize(
        "subdomain",
        [
            "attacker.example/",
            "user@evil.example",
            "acme.evil.example",
            "127.0.0.1:8443/",
            "acme/path",
            "acme?x=",
            "acme#frag",
            "",
            "-acme",
            "acme-",
            "a" * 64,
        ],
    )
    def test_hostile_subdomains_rejected(self, subdomain: str) -> None:
        assert is_valid_subdomain(subdomain) is False
        with pytest.raises(ValueError):
            _base_url(subdomain)


class TestHeaders:
    def test_basic_auth_header(self) -> None:
        headers = _get_headers("svc", "secret")
        expected = base64.b64encode(b"svc:secret").decode("ascii")
        assert headers["Authorization"] == f"Basic {expected}"
        assert headers["Accept"] == "application/json"


class TestBuildParams:
    def test_events_full_refresh_sends_stable_sort_only(self) -> None:
        params = _build_params(
            XMATTERS_ENDPOINTS["events"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        assert params == {"sortBy": "START_TIME", "sortOrder": "ASCENDING"}

    def test_events_incremental_sends_from(self) -> None:
        params = _build_params(
            XMATTERS_ENDPOINTS["events"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert params["sortBy"] == "START_TIME"
        assert params["sortOrder"] == "ASCENDING"
        assert params["from"] == "2026-01-01T00:00:00+00:00"

    def test_reference_endpoint_has_no_sort_or_from(self) -> None:
        params = _build_params(
            XMATTERS_ENDPOINTS["people"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert params == {}


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,expected_ok,expected_status",
        [
            (200, True, 200),
            (401, False, 401),
            (403, False, 403),
            (500, False, 500),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_ok: bool, expected_status: int) -> None:
        with mock.patch(XMATTERS_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
            ok, status, _error = validate_credentials("acme", "svc", "secret")
        assert ok is expected_ok
        assert status == expected_status

    def test_transport_failure_returns_none_status(self) -> None:
        # A credential probe must never raise; a transport failure maps to "not validated".
        with mock.patch(XMATTERS_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.side_effect = Exception("no network")
            ok, status, error = validate_credentials("acme", "svc", "secret")
        assert ok is False
        assert status is None
        assert error is None

    def test_401_and_403_carry_custom_messages(self) -> None:
        with mock.patch(XMATTERS_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=401)
            assert validate_credentials("acme", "svc", "secret")[2] == "Invalid xMatters credentials"
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=403)
            assert validate_credentials("acme", "svc", "secret")[2] == (
                "Your xMatters account does not have access to this resource"
            )

    def test_probe_targets_instance_subdomain_and_endpoint_path(self) -> None:
        with mock.patch(XMATTERS_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
            validate_credentials("acme", "svc", "secret", endpoint="events")
            called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url.startswith("https://acme.xmatters.com/api/xm/1/events?")


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_following_links_next(self, MockSession) -> None:
        session = MockSession.return_value
        # Short pages (< PAGE_SIZE) — only a `links.next` keeps pagination going.
        _wire(
            session,
            [_response([{"id": "1"}, {"id": "2"}], next_url="/api/xm/1/events?offset=1000"), _response([{"id": "3"}])],
        )

        rows = _rows(_source("events", _make_manager()))

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_advances_offset_and_sets_page_params(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session, [_response([{"id": "1"}], next_url="/api/xm/1/events?offset=1000"), _response([{"id": "2"}])]
        )

        _rows(_source("events", _make_manager()))

        assert params[0]["offset"] == 0
        assert params[0]["limit"] == PAGE_SIZE
        assert params[1]["offset"] == PAGE_SIZE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_checkpoint_once_after_first_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "1"}], next_url="/api/xm/1/events?offset=1000"), _response([{"id": "2"}])])

        manager = _make_manager()
        _rows(_source("events", manager))

        # Checkpoint written once (next offset) after the first page; the last page has no
        # `links.next` and is short, so no further checkpoint.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == XmattersResumeConfig(offset=PAGE_SIZE)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_page_without_next_link_continues(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        params = _wire(session, [_response(full_page), _response([{"id": "last"}])])

        rows = _rows(_source("people", _make_manager()))

        # The page-fill heuristic keeps going even without a `links.next`.
        assert len(rows) == PAGE_SIZE + 1
        assert params[1]["offset"] == PAGE_SIZE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "x"}])])

        _rows(_source("events", _make_manager(XmattersResumeConfig(offset=PAGE_SIZE))))

        assert params[0]["offset"] == PAGE_SIZE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_stops_with_one_request_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], next_url="/api/xm/1/events?offset=1000")])

        manager = _make_manager()
        rows = _rows(_source("events", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_page_without_next_link_stops(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "1"}])])

        rows = _rows(_source("people", _make_manager()))

        assert [r["id"] for r in rows] == ["1"]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_events_incremental_sends_from_and_sort(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "1"}])])

        _rows(
            _source(
                "events",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert params[0]["from"] == "2026-01-01T00:00:00+00:00"
        assert params[0]["sortBy"] == "START_TIME"
        assert params[0]["sortOrder"] == "ASCENDING"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_reference_endpoint_sends_no_sort_or_from(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "1"}])])

        _rows(
            _source(
                "people",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        assert "from" not in params[0]
        assert "sortBy" not in params[0]


class TestXmattersSourceResponse:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_events_partitioned_on_created(self, MockSession) -> None:
        response = _source("events", _make_manager())
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["created"]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "asc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_reference_endpoint_has_no_partition_settings(self, MockSession) -> None:
        response = _source("people", _make_manager())
        assert response.primary_keys == ["id"]
        assert response.partition_keys is None
        assert response.partition_mode is None

    @pytest.mark.parametrize("endpoint", list(XMATTERS_ENDPOINTS.keys()))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_every_endpoint_builds_a_response(self, MockSession, endpoint: str) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == [XMATTERS_ENDPOINTS[endpoint].primary_key]
        assert callable(response.items)
