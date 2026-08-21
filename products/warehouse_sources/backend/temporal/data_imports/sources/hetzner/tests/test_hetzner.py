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
from products.warehouse_sources.backend.temporal.data_imports.sources.hetzner.hetzner import (
    HETZNER_BASE_URL,
    HetznerResumeConfig,
    hetzner_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the hetzner module.
HETZNER_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.hetzner.hetzner.make_tracked_session"
)
# Retryable tests: silence tenacity's backoff so retries don't actually sleep.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _page(
    items: list[dict[str, Any]] | None,
    *,
    endpoint: str = "servers",
    last_page: int = 1,
    status: int = 200,
    drop_key: bool = False,
    reason: str = "",
) -> Response:
    body: dict[str, Any] = {"meta": {"pagination": {"last_page": last_page}}}
    if not drop_key:
        body[endpoint] = items or []
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = f"{HETZNER_BASE_URL}/{endpoint}"
    resp.reason = reason
    return resp


def _make_manager(resume_state: HetznerResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's query params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared rather than inspecting the shared dict after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock):
    return hetzner_source(
        api_token="token",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_last_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _page([{"id": 1}, {"id": 2}], last_page=2),
                _page([{"id": 3}], last_page=2),
            ],
        )
        manager = _make_manager()

        rows = _rows(_source("servers", manager))

        assert [r["id"] for r in rows] == [1, 2, 3]
        # last_page=2 stops after page 2 — no extra empty-page request.
        assert session.send.call_count == 2
        assert params[0]["page"] == 1
        assert params[0]["per_page"] == 50
        assert params[1]["page"] == 2
        # Checkpoint saved after the first page, pointing at the next page.
        manager.save_state.assert_called_once_with(HetznerResumeConfig(page=2))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_makes_one_request_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([{"id": 1}, {"id": 2}], last_page=1)])
        manager = _make_manager()

        rows = _rows(_source("servers", manager))

        assert [r["id"] for r in rows] == [1, 2]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_response_key_empty(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([], last_page=1)])
        manager = _make_manager()

        rows = _rows(_source("servers", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_response_key_stops_without_raising(self, MockSession) -> None:
        # The hand-rolled source treated a missing envelope key as an empty page (stop), not an error;
        # a non-required data_selector preserves that — the paginator stops rather than failing loud.
        session = MockSession.return_value
        _wire(session, [_page(None, drop_key=True, last_page=1)])
        manager = _make_manager()

        rows = _rows(_source("servers", manager))

        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        # A saved page must skip already-synced pages instead of restarting at page 1.
        session = MockSession.return_value
        params = _wire(session, [_page([{"id": 99}], last_page=2)])
        manager = _make_manager(HetznerResumeConfig(page=2))

        rows = _rows(_source("servers", manager))

        assert [r["id"] for r in rows] == [99]
        assert params[0]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sort_param_present_for_resource_endpoint(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page([{"id": 1}], last_page=1)])

        _rows(_source("servers", _make_manager()))

        assert params[0]["sort"] == "id:asc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_catalog_endpoint_omits_sort(self, MockSession) -> None:
        # server_types has no verified sort support, so we must not send a sort param that could 400.
        session = MockSession.return_value
        params = _wire(session, [_page([{"id": 1}], endpoint="server_types", last_page=1)])

        _rows(_source("server_types", _make_manager()))

        assert "sort" not in params[0]


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    @mock.patch(SLEEP_PATCH, lambda *_: None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_transient_status_is_retried_then_reraised(self, _name: str, status: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([], status=status, reason="err") for _ in range(5)])

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("servers", _make_manager()))
        # 5 attempts (DEFAULT_RETRY_ATTEMPTS) before giving up.
        assert session.send.call_count == 5

    @mock.patch(SLEEP_PATCH, lambda *_: None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_then_succeeds(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _page([], status=503, reason="err"),
                _page([{"id": 7}], last_page=1),
            ],
        )

        rows = _rows(_source("servers", _make_manager()))

        assert [r["id"] for r in rows] == [7]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_is_not_retried(self, MockSession) -> None:
        # A 401 is fatal; raising HTTPError immediately (not retrying) lets get_non_retryable_errors act.
        session = MockSession.return_value
        _wire(session, [_page([], status=401, reason="Unauthorized")])

        with pytest.raises(requests.HTTPError):
            _rows(_source("servers", _make_manager()))
        assert session.send.call_count == 1


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, True, None),
            ("unauthorized", 401, False, "Invalid Hetzner Cloud API token"),
            ("forbidden", 403, False, "Invalid Hetzner Cloud API token"),
        ]
    )
    @mock.patch(HETZNER_SESSION_PATCH)
    def test_status_maps_to_validity(
        self, _name: str, status: int, expected_valid: bool, expected_message: str | None, mock_session
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        valid, message = validate_credentials("token")
        assert valid is expected_valid
        assert message == expected_message

    @mock.patch(HETZNER_SESSION_PATCH)
    def test_network_error_is_invalid_not_raised(self, mock_session) -> None:
        # A probe transport failure must return "not validated", never raise out of source creation.
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        valid, message = validate_credentials("token")
        assert valid is False
        assert message == "Could not reach the Hetzner Cloud API"


class TestSourceResponse:
    def test_datetime_partition_for_resource_endpoint(self) -> None:
        with mock.patch(CLIENT_SESSION_PATCH):
            response = _source("servers", _make_manager())
        assert response.name == "servers"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created"]

    @parameterized.expand([("actions",), ("server_types",), ("locations",)])
    def test_no_partition_for_timestampless_endpoints(self, endpoint: str) -> None:
        # actions has no `created`; catalog endpoints carry no timestamps — partitioning on a null or
        # absent field would rewrite partitions every sync, so these must stay unpartitioned.
        with mock.patch(CLIENT_SESSION_PATCH):
            response = _source(endpoint, _make_manager())
        assert response.partition_mode is None
        assert response.partition_keys is None
