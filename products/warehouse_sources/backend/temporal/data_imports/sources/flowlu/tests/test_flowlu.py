import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.flowlu.flowlu import (
    FlowluResumeConfig,
    flowlu_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flowlu.settings import ENDPOINTS, FLOWLU_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the flowlu module.
FLOWLU_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.flowlu.flowlu.make_tracked_session"
)

_REASONS = {401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 500: "Internal Server Error"}


def _envelope(items: list[dict[str, Any]], total: int | None = None) -> dict[str, Any]:
    return {"response": {"items": items, "total": total if total is not None else len(items), "count": len(items)}}


def _response(
    items: list[dict[str, Any]] | None = None,
    *,
    status: int = 200,
    body: Any = None,
    url: str | None = None,
) -> Response:
    resp = Response()
    resp.status_code = status
    if body is not None:
        resp._content = json.dumps(body).encode()
    elif items is not None:
        resp._content = json.dumps(_envelope(items)).encode()
    else:
        resp._content = b"{}"
    resp.url = url or "https://acme.flowlu.com/api/v1/module/crm/account/list?api_key=fl-key&page=1"
    resp.reason = _REASONS.get(status)
    return resp


def _make_manager(resume_state: FlowluResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[Any]]:
    """Wire a mock session; return (param_snapshots, url_snapshots) captured AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so a snapshot copy per
    prepared request is the only way to see each page's params (see alguna's test).
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    url_snapshots: list[Any] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        url_snapshots.append(request.url)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, url_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: Any, endpoint: str = "accounts") -> Any:
    return flowlu_source(
        api_key="fl-key",
        subdomain="acme",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_pagination_until_empty_page(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response([{"id": 1}]), _response([{"id": 2}]), _response([])])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"id": 1}, {"id": 2}]
        # 1-indexed page param advances one page per request.
        assert [p["page"] for p in params] == [1, 2, 3]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_page_after_yielding_each_batch(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}]), _response([{"id": 2}]), _response([])])

        manager = _make_manager()
        _rows(_source(manager))

        # State is saved AFTER each non-empty page, pointing at the next page to fetch; the empty
        # terminating page saves nothing.
        assert [c.args[0].next_page for c in manager.save_state.call_args_list] == [2, 3]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response([{"id": 2}]), _response([])])

        manager = _make_manager(FlowluResumeConfig(next_page=2))
        rows = _rows(_source(manager))

        assert rows == [{"id": 2}]
        # Page 1 must never be fetched on resume.
        assert params[0]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing_and_saves_no_state(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_request_targets_account_host(self, MockSession) -> None:
        session = MockSession.return_value
        _, urls = _wire(session, [_response([])])

        _rows(_source(_make_manager(), endpoint="tasks"))
        assert urls[0] == "https://acme.flowlu.com/api/v1/module/task/tasks/list"


class TestErrorHandling:
    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_http_error(self, _name: str, status: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(status=status)])

        with pytest.raises(HTTPError):
            _rows(_source(_make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_message_omits_api_key_and_keeps_status_prefix(self, MockSession) -> None:
        # The 401 raise_for_status embeds the request URL, which carries the `api_key` query param.
        # The framework redacts the key's VALUE from the raised message while preserving the
        # "<status> Client Error: <reason> for url" prefix that get_non_retryable_errors matches on.
        session = MockSession.return_value
        _wire(
            session,
            [_response(status=401, url="https://acme.flowlu.com/api/v1/module/crm/account/list?api_key=fl-key&page=1")],
        )

        with pytest.raises(HTTPError) as exc_info:
            _rows(_source(_make_manager()))

        message = str(exc_info.value)
        assert "fl-key" not in message
        assert message.startswith("401 Client Error: Unauthorized for url")

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch("time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_transient_statuses_are_retried_then_recover(self, _name: str, status: int, MockSession, _sleep) -> None:
        session = MockSession.return_value
        # First page 500s once, then succeeds on retry; an empty page terminates.
        _wire(session, [_response(status=status), _response([{"id": 1}]), _response([])])

        rows = _rows(_source(_make_manager()))

        # A 429/5xx is transient: the client retries and recovers rather than failing loudly.
        assert rows == [{"id": 1}]
        assert session.send.call_count == 3


class TestMalformedPayload:
    @parameterized.expand(
        [
            ("bare_array", [{"id": 1}]),
            ("missing_response_key", {"data": []}),
            ("non_dict_response", {"response": []}),
            ("missing_items", {"response": {"total": 0}}),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unexpected_shape_fails_loudly(self, _name: str, body: Any, MockSession) -> None:
        # A 200 body that doesn't match `response.items` means the shape changed — fail loud
        # instead of silently syncing 0 rows.
        session = MockSession.return_value
        _wire(session, [_response(body=body)])

        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source(_make_manager()))


class TestValidateCredentials:
    def _probe(self, response_or_exc: Any) -> Any:
        session = mock.MagicMock()
        if isinstance(response_or_exc, Exception):
            session.get.side_effect = response_or_exc
        else:
            session.get.return_value = response_or_exc
        return mock.patch(FLOWLU_SESSION_PATCH, return_value=session)

    @parameterized.expand(
        [
            ("valid", 200, (True, None)),
            ("unauthorized", 401, (False, "Invalid Flowlu API key")),
            ("forbidden", 403, (False, "Invalid Flowlu API key")),
            ("server_error", 500, (False, "Flowlu returned HTTP 500")),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected: tuple[bool, str | None]) -> None:
        with self._probe(mock.MagicMock(status_code=status)):
            assert validate_credentials("fl-key", "acme") == expected

    def test_connection_error_maps_to_generic_message(self) -> None:
        # The probe swallows the exception (which could embed the api_key-carrying URL) and returns
        # a fixed message, so the raw exception text is never surfaced.
        with self._probe(RuntimeError("https://acme.flowlu.com/...?api_key=fl-key")):
            assert validate_credentials("fl-key", "acme") == (False, "Could not connect to Flowlu")


class TestFlowluSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _source(_make_manager(), endpoint=endpoint)
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No stable creation timestamp could be verified across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in FLOWLU_ENDPOINTS.values())
        assert set(FLOWLU_ENDPOINTS) == set(ENDPOINTS)
