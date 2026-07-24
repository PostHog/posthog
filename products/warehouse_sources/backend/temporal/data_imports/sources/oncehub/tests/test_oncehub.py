import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.oncehub.oncehub import (
    PAGE_SIZE,
    OncehubResumeConfig,
    oncehub_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.oncehub.settings import (
    ENDPOINTS,
    ONCEHUB_ENDPOINTS,
)

# The RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the oncehub module.
ONCEHUB_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.oncehub.oncehub.make_tracked_session"
)
# tenacity sleeps between retries; patch it so retry-path tests don't actually wait.
TENACITY_SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(items: list[dict[str, Any]] | None, has_more: bool, *, status: int = 200) -> Response:
    body = {"object": "list", "data": items if items is not None else [], "has_more": has_more}
    return _raw_response(body, status=status)


def _raw_response(body: Any, *, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = "https://api.oncehub.com/v2/bookings"
    return resp


def _make_manager(resume_state: OncehubResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so inspecting it after the run
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


def _full_page(prefix: str) -> list[dict[str, Any]]:
    return [{"id": f"{prefix}-{i}"} for i in range(PAGE_SIZE)]


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: mock.MagicMock, endpoint: str = "bookings") -> Any:
    return oncehub_source(
        api_key="oncehub-key",
        endpoint=endpoint,
        team_id=1,
        job_id="job",
        resumable_source_manager=manager,
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_has_more_false_yields_and_stops(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "BKNG-1"}, {"id": "BKNG-2"}], has_more=False)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"id": "BKNG-1"}, {"id": "BKNG-2"}]
        assert session.send.call_count == 1
        # has_more is false, so we stop without persisting resume state.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_after_cursor_until_has_more_false(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        first_page = _full_page("BKNG")
        last_id = first_page[-1]["id"]
        params = _wire(
            session, [_response(first_page, has_more=True), _response([{"id": "BKNG-final"}], has_more=False)]
        )

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert len(rows) == PAGE_SIZE + 1
        # First page carries only the limit; the second advances by the last item's id via `after`.
        assert params[0] == {"limit": PAGE_SIZE}
        assert params[1] == {"limit": PAGE_SIZE, "after": last_id}
        # State is saved once after the first page (cursor = last id), then the short page ends it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == OncehubResumeConfig(cursor=last_id)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "BKNG-100"}], has_more=False)])

        manager = _make_manager(OncehubResumeConfig(cursor="BKNG-99"))
        rows = _rows(_source(manager))

        assert rows == [{"id": "BKNG-100"}]
        # The initial (cursor-less) page must never be fetched on resume: the first request carries `after`.
        assert session.send.call_count == 1
        assert params[0] == {"limit": PAGE_SIZE, "after": "BKNG-99"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], has_more=False)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_has_more_true_but_empty_page_stops_without_checkpoint(self, MockSession: mock.MagicMock) -> None:
        # A truthy has_more with no items must still terminate (matches the hand-rolled `not items` guard).
        session = MockSession.return_value
        _wire(session, [_response([], has_more=True)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(TENACITY_SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_retry_then_raise(
        self, _name: str, status: int, MockSession: mock.MagicMock, _sleep: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], has_more=False, status=status)] * 5)

        with pytest.raises(RESTClientRetryableError):
            _rows(_source(_make_manager()))
        # 429/5xx are retried by the client up to its attempt cap, then reraised.
        assert session.send.call_count == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_for_status(self, _name: str, status: int, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], has_more=False, status=status)])

        with pytest.raises(requests.HTTPError):
            _rows(_source(_make_manager()))
        # Permanent 4xx is not retried.
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_raises_loudly(self, MockSession: mock.MagicMock) -> None:
        # A 200 payload that is a bare list (not the {"data": [...]} envelope) means the shape changed.
        session = MockSession.return_value
        _wire(session, [_raw_response([{"id": "BKNG-1"}])])

        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source(_make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_raises_loudly(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_raw_response({"object": "list", "has_more": False})])

        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source(_make_manager()))


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid OnceHub API key"),
            ("forbidden", 403, False, "Invalid OnceHub API key"),
            ("server_error", 500, False, "OnceHub returned HTTP 500"),
        ]
    )
    @mock.patch(ONCEHUB_SESSION_PATCH)
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: mock.MagicMock,
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("oncehub-key") == (expected_valid, expected_message)

    @mock.patch(ONCEHUB_SESSION_PATCH)
    def test_unreachable_probe_is_not_validated(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("oncehub-key") == (False, "Could not validate OnceHub API key")

    @mock.patch(ONCEHUB_SESSION_PATCH)
    def test_probe_sends_api_key_header(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("oncehub-key")
        _, kwargs = mock_session.return_value.get.call_args
        assert kwargs["headers"]["API-Key"] == "oncehub-key"


class TestOncehubSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, endpoint: str, MockSession: mock.MagicMock) -> None:
        response = _source(_make_manager(), endpoint=endpoint)
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Lists paginate newest-first with no stable ascending order, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in ONCEHUB_ENDPOINTS.values())
        assert set(ONCEHUB_ENDPOINTS) == set(ENDPOINTS)
