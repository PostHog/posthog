import json
from typing import Any

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.mollie.mollie import (
    MollieResumeConfig,
    mollie_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mollie.settings import ENDPOINTS, MOLLIE_ENDPOINTS

# The RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the mollie module.
MOLLIE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.mollie.mollie.make_tracked_session"
)


def _response(embedded_key: str, items: list[dict[str, Any]], next_url: str | None = None) -> Response:
    body: dict[str, Any] = {"count": len(items), "_embedded": {embedded_key: items}, "_links": {}}
    if next_url:
        body["_links"]["next"] = {"href": next_url}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    resp.url = "https://api.mollie.com/v2/probe"
    return resp


def _bare_response(body: dict[str, Any]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    resp.url = "https://api.mollie.com/v2/probe"
    return resp


def _error_response(status_code: int) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = b"{}"
    resp.url = "https://api.mollie.com/v2/payments?limit=250"
    return resp


def _make_manager(resume_state: MollieResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[str], list[dict[str, Any]]]:
    """Wire a mock session and snapshot each request's url + params AT PREPARE TIME.

    ``request.url``/``request.params`` are mutated in place across pages (the paginator retargets
    the same Request to each next link), so inspecting them after the run shows only the final
    state — snapshot a copy when each request is prepared instead.
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


def _source(endpoint: str, manager: mock.MagicMock):
    return mollie_source("live_key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_hal_next_link(self, MockSession) -> None:
        session = MockSession.return_value
        next_url = "https://api.mollie.com/v2/payments?from=tr_next&limit=250"
        urls, _params = _wire(
            session,
            [
                _response("payments", [{"id": "tr_1"}, {"id": "tr_2"}], next_url=next_url),
                _response("payments", [{"id": "tr_3"}]),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("payments", manager))

        assert [r["id"] for r in rows] == ["tr_1", "tr_2", "tr_3"]
        # The next link is self-contained — the second request targets it directly.
        assert urls[1] == next_url
        # Checkpoint saved once after the first page (points at the next link); the short
        # final page (no next link) ends the run without another save.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == MollieResumeConfig(next_url=next_url)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_first_request_uses_endpoint_path_and_limit(self, MockSession) -> None:
        session = MockSession.return_value
        urls, params = _wire(session, [_response("payment_links", [])])

        _rows(_source("payment_links", _make_manager()))

        assert urls[0] == "https://api.mollie.com/v2/payment-links"
        assert params[0]["limit"] == 250

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession) -> None:
        session = MockSession.return_value
        resume_url = "https://api.mollie.com/v2/payments?from=tr_resume&limit=250"
        urls, params = _wire(session, [_response("payments", [{"id": "tr_9"}])])

        manager = _make_manager(MollieResumeConfig(next_url=resume_url))
        _rows(_source("payments", manager))

        # The saved next link becomes the first request; its self-contained query replaces the base params.
        assert urls[0] == resume_url
        assert params[0] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_stops_without_saving_state(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response("payments", [])])

        manager = _make_manager()
        rows = _rows(_source("payments", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_embedded_block_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        # A 200 body without an `_embedded` block is a legitimate empty page, not an error.
        _wire(session, [_bare_response({"count": 0, "_links": {}})])

        rows = _rows(_source("payments", _make_manager()))

        assert rows == []


class TestRetries:
    @pytest.mark.parametrize("retryable_status", [429, 500, 503])
    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_triggers_retry_then_succeeds(self, MockSession, _mock_sleep, retryable_status) -> None:
        session = MockSession.return_value
        # tenacity's backoff sleep is patched out so the retry resolves instantly.
        _wire(session, [_error_response(retryable_status), _response("payments", [{"id": "tr_1"}])])

        rows = _rows(_source("payments", _make_manager()))

        assert [r["id"] for r in rows] == ["tr_1"]
        assert session.send.call_count == 2

    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_retryable_4xx_raises_immediately(self, MockSession, _mock_sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_error_response(403)])

        with pytest.raises(requests.HTTPError):
            _rows(_source("payments", _make_manager()))

        assert session.send.call_count == 1


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            # Org access tokens 4xx without a profileId but are still valid keys.
            (400, True),
            (403, True),
            (401, False),
        ],
    )
    @mock.patch(MOLLIE_SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected) -> None:
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("live_key") is expected

    @mock.patch(MOLLIE_SESSION_PATCH)
    def test_validate_credentials_swallows_network_errors(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("live_key") is False


class TestMollieSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint) -> None:
        config = MOLLIE_ENDPOINTS[endpoint]
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]

    @pytest.mark.parametrize("config", list(MOLLIE_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config) -> None:
        assert config.partition_key == "createdAt"
