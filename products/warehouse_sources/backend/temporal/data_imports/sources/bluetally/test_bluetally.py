import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.bluetally import (
    PAGE_SIZE,
    BluetallyResumeConfig,
    bluetally_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.settings import (
    BLUETALLY_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    DEFAULT_RETRY_ATTEMPTS,
    RESTClientRetryableError,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the bluetally module.
BLUETALLY_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.bluetally.make_tracked_session"
)


def _response(items: list[dict[str, Any]], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(items).encode()
    return resp


def _error_response(status_code: int) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.url = "https://app.bluetallyapp.com/api/v1/assets"
    resp._content = b""
    return resp


def _non_list_response() -> Response:
    resp = Response()
    resp.status_code = 200
    resp.url = "https://app.bluetallyapp.com/api/v1/assets"
    resp._content = b'{"error": "unexpected"}'
    return resp


def _make_manager(resume_state: BluetallyResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(
    endpoint: str = "assets",
    manager: mock.MagicMock | None = None,
    tenant_id: str | None = None,
):
    return bluetally_source(
        api_key="key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager if manager is not None else _make_manager(),
        tenant_id=tenant_id,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_first_request_params(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 1}])])

        _rows(_source())

        # offset=0 is the first page; it must not be dropped as a falsy value.
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == PAGE_SIZE
        assert params[0]["sort"] == "created_at"
        assert params[0]["order"] == "asc"
        assert "tenant_id" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_threads_tenant_id_into_requests(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"id": i} for i in range(PAGE_SIZE)]
        params = _wire(session, [_response(full_page), _response([{"id": PAGE_SIZE}])])

        _rows(_source(tenant_id="99"))

        assert all(p["tenant_id"] == "99" for p in params)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"id": i} for i in range(PAGE_SIZE)]
        params = _wire(session, [_response(full_page), _response([{"id": PAGE_SIZE}])])

        manager = _make_manager()
        rows = _rows(_source(manager=manager))

        assert len(rows) == PAGE_SIZE + 1
        assert params[0]["offset"] == 0
        assert params[1]["offset"] == PAGE_SIZE
        # State is saved after the full page (pointing at the next offset), then we stop on the short page.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == BluetallyResumeConfig(offset=PAGE_SIZE)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_short_page_stops_without_saving_state(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}, {"id": 2}])])

        manager = _make_manager()
        rows = _rows(_source(manager=manager))

        assert rows == [{"id": 1}, {"id": 2}]
        assert session.send.call_count == 1
        # A short first page never advances the offset, so no resume state is persisted.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        rows = _rows(_source(manager=manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": PAGE_SIZE}])])

        manager = _make_manager(BluetallyResumeConfig(offset=PAGE_SIZE))
        rows = _rows(_source(manager=manager))

        # Resuming at offset=PAGE_SIZE skips the already-synced first page.
        assert rows == [{"id": PAGE_SIZE}]
        assert params[0]["offset"] == PAGE_SIZE


class TestErrors:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch("time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_exhaust_retries(self, _name: str, status: int, MockSession, _mock_sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_error_response(status)] * DEFAULT_RETRY_ATTEMPTS)

        with pytest.raises(RESTClientRetryableError):
            _rows(_source())

        assert session.send.call_count == DEFAULT_RETRY_ATTEMPTS

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_http_error(self, _name: str, status: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_error_response(status)])

        with pytest.raises(requests.HTTPError):
            _rows(_source())

        # Client errors are permanent — no retries.
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_payload_raises_value_error(self, MockSession) -> None:
        # A non-list 200 is a permanent contract violation (wrapped payload, proxy HTML, …) — it must
        # fail loud without burning the retry budget on something retries can't fix.
        session = MockSession.return_value
        _wire(session, [_non_list_response()])

        with pytest.raises(ValueError, match="list"):
            _rows(_source())

        assert session.send.call_count == 1


class TestBluetallySourceResponse:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, name: str, MockSession) -> None:
        response = _source(endpoint=name)
        assert response.name == name
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        # Stable creation timestamp drives datetime partitioning for every endpoint.
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"

    def test_every_endpoint_partitions_on_created_at(self) -> None:
        # Guards against accidentally partitioning on a churning field like updated_at.
        assert all(cfg.partition_key == "created_at" for cfg in BLUETALLY_ENDPOINTS.values())


class TestValidateCredentials:
    @mock.patch(BLUETALLY_SESSION_PATCH)
    def test_ok(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("key") is True

    @mock.patch(BLUETALLY_SESSION_PATCH)
    def test_unauthorized(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=401)
        assert validate_credentials("key") is False

    @mock.patch(BLUETALLY_SESSION_PATCH)
    def test_swallows_exceptions(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key") is False

    @mock.patch(BLUETALLY_SESSION_PATCH)
    def test_probes_given_path_with_tenant_id(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("key", tenant_id="42", path="/employees") is True
        url = mock_session.return_value.get.call_args.args[0]
        assert url.startswith("https://app.bluetallyapp.com/api/v1/employees?")
        assert "limit=1" in url
        assert "tenant_id=42" in url

    @mock.patch(BLUETALLY_SESSION_PATCH)
    def test_omits_unset_tenant_id(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("key")
        url = mock_session.return_value.get.call_args.args[0]
        assert "tenant_id" not in url
