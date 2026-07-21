import json
import base64
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.wufoo.settings import ENDPOINTS, WUFOO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.wufoo.wufoo import (
    PAGE_SIZE,
    WufooResumeConfig,
    _headers,
    validate_credentials,
    wufoo_source,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the wufoo module.
WUFOO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.wufoo.wufoo.make_tracked_session"
)


def _response(count: int, *, data_key: str = "Forms", status: int = 200, drop_key: bool = False) -> Response:
    body: dict[str, Any] = {}
    if not drop_key:
        body[data_key] = [{"Hash": f"h{i}"} for i in range(count)]
    resp = Response()
    resp.status_code = status
    resp.reason = {401: "Unauthorized", 403: "Forbidden", 404: "Not Found"}.get(status, "OK")
    resp.url = "https://acme.wufoo.com/api/v3/forms.json"
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: WufooResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session, returning a list capturing each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy per prepare.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: mock.MagicMock, endpoint: str = "forms"):
    return wufoo_source(
        api_key="wufoo-key",
        subdomain="acme",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestHeaders:
    def test_basic_auth_uses_api_key_as_username_with_any_password(self) -> None:
        # Wufoo authenticates with HTTP Basic where the API key is the username; a wrong header
        # construction silently 401s every request, so pin the exact encoding.
        header = _headers("secret-key")["Authorization"]
        assert header.startswith("Basic ")
        decoded = base64.b64decode(header.removeprefix("Basic ")).decode("ascii")
        assert decoded == "secret-key:footastic"


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_yields_and_stops_without_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(2)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert len(rows) == 2
        # A short (< PAGE_SIZE) first page ends the sync after one request with no checkpoint.
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_offset_until_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response(PAGE_SIZE), _response(PAGE_SIZE), _response(3)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert len(rows) == 2 * PAGE_SIZE + 3
        # pageStart advances by PAGE_SIZE per page; pageSize is pinned on every request.
        assert [p["pageStart"] for p in params] == [0, PAGE_SIZE, 2 * PAGE_SIZE]
        assert all(p["pageSize"] == PAGE_SIZE for p in params)
        # State is checkpointed after each full page (points at the next offset), never for the short one.
        assert [s.page_start for s in (c.args[0] for c in manager.save_state.call_args_list)] == [
            PAGE_SIZE,
            2 * PAGE_SIZE,
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response(2)])

        manager = _make_manager(WufooResumeConfig(page_start=PAGE_SIZE))
        rows = _rows(_source(manager))

        # Offset 0 is never fetched on resume — the first request targets the saved offset.
        assert params[0]["pageStart"] == PAGE_SIZE
        assert len(rows) == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(0)])

        rows = _rows(_source(_make_manager()))
        assert rows == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_uses_endpoint_data_key(self, MockSession) -> None:
        # Each endpoint wraps its rows under a distinct key; selecting the wrong one drops all rows.
        session = MockSession.return_value
        _wire(session, [_response(1, data_key="Users")])

        rows = _rows(_source(_make_manager(), endpoint="users"))
        assert len(rows) == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(0, drop_key=True)])

        # A 200 body without the expected list key means the shape changed — fail loud, not 0 rows.
        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source(_make_manager()))


class TestRetryClassification:
    @parameterized.expand([("server_error", 500), ("bad_gateway", 503), ("rate_limited", 429)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_transient_statuses_are_retried(self, _name: str, status: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(0, status=status), _response(1)])

        with mock.patch("time.sleep"):  # don't actually back off between retries
            rows = _rows(_source(_make_manager()))

        # The transient status is retried and the sync completes on the follow-up 200.
        assert session.send.call_count == 2
        assert len(rows) == 1

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_fail_loud(self, _name: str, status: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(0, status=status)])

        # 4xx (other than 429) is a permanent error: it is not retried and surfaces as an HTTPError.
        with pytest.raises(requests.HTTPError):
            _rows(_source(_make_manager()))
        assert session.send.call_count == 1


class TestValidateCredentials:
    @pytest.mark.parametrize("status", [200, 401, 403, 500])
    @mock.patch(WUFOO_SESSION_PATCH)
    def test_returns_status_code(self, mock_session, status: int) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("wufoo-key", "acme") == status

    @mock.patch(WUFOO_SESSION_PATCH)
    def test_invalid_subdomain_short_circuits_without_request(self, mock_session) -> None:
        assert validate_credentials("wufoo-key", "bad subdomain!") is None
        mock_session.return_value.get.assert_not_called()

    @mock.patch(WUFOO_SESSION_PATCH)
    def test_connection_error_maps_to_none(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("wufoo-key", "acme") is None


class TestWufooSourceResponse:
    @parameterized.expand([("forms",), ("reports",), ("users",)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_uses_hash_primary_key(self, endpoint: str, MockSession) -> None:
        response = _source(_make_manager(), endpoint=endpoint)
        assert response.name == endpoint
        assert response.primary_keys == ["Hash"]

    def test_every_endpoint_uses_hash_primary_key(self) -> None:
        assert all(config.primary_keys == ["Hash"] for config in WUFOO_ENDPOINTS.values())
        assert set(WUFOO_ENDPOINTS) == set(ENDPOINTS)
