import json
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory.ezofficeinventory import (
    EZOfficeInventoryResumeConfig,
    ezofficeinventory_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the ezofficeinventory module.
EZO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory.ezofficeinventory."
    "make_tracked_session"
)


def _response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    resp.url = "https://acme.ezofficeinventory.com/assets.api"
    return resp


def _make_manager(resume_state: EZOfficeInventoryResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared instead of inspecting the final state after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = "https://acme.ezofficeinventory.com/assets.api"
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock):
    return ezofficeinventory_source(
        api_key="tok",
        subdomain="acme",
        endpoint=endpoint,
        team_id=1,
        job_id="job",
        resumable_source_manager=manager,
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_total_pages(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"assets": [{"identifier": 1}], "total_pages": 2}),
                _response({"assets": [{"identifier": 2}], "total_pages": 2}),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("assets", manager))

        assert rows == [{"identifier": 1}, {"identifier": 2}]
        assert params[0]["page"] == 1
        assert params[1]["page"] == 2
        # State saved once (after page 1), pointing at page 2 — never after the terminal page.
        manager.save_state.assert_called_once_with(EZOfficeInventoryResumeConfig(next_page=2))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_page_when_total_pages_absent(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"assets": [{"identifier": 1}]}), _response({"assets": []})])

        manager = _make_manager()
        rows = _rows(_source("assets", manager))

        assert rows == [{"identifier": 1}]
        assert session.send.call_count == 2
        manager.save_state.assert_called_once_with(EZOfficeInventoryResumeConfig(next_page=2))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_first_page_empty_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"assets": []})])

        manager = _make_manager()
        rows = _rows(_source("assets", manager))

        assert rows == []
        assert params[0]["page"] == 1
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"assets": [{"identifier": 30}], "total_pages": 3})])

        manager = _make_manager(EZOfficeInventoryResumeConfig(next_page=3))
        rows = _rows(_source("assets", manager))

        assert rows == [{"identifier": 30}]
        # Picks up at page 3 (the saved cursor), not page 1.
        assert params[0]["page"] == 3
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_extra_params_are_sent(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"assets": [{"identifier": 1}], "total_pages": 1})])

        _rows(_source("checked_out_assets", manager=_make_manager()))
        assert params[0]["status"] == "checked_out"
        assert params[0]["page"] == 1


class TestUnwrap:
    @mock.patch(CLIENT_SESSION_PATCH)
    @pytest.mark.parametrize(
        ("endpoint", "body", "expected"),
        [
            (
                "groups",
                {"groups": [{"group": {"id": 1}}, {"group": {"id": 2}}], "total_pages": 1},
                [{"id": 1}, {"id": 2}],
            ),
            ("vendors", {"vendors": [{"vendor": {"id": 9}}], "total_pages": 1}, [{"id": 9}]),
            # A row already shaped like the unwrapped object passes through untouched.
            ("groups", {"groups": [{"id": 5}], "total_pages": 1}, [{"id": 5}]),
        ],
    )
    def test_unwraps_single_key_items(
        self, MockSession, endpoint: str, body: dict[str, Any], expected: list[dict]
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response(body)])

        rows = _rows(_source(endpoint, _make_manager()))
        assert rows == expected

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_selector_yields_nothing(self, MockSession) -> None:
        # A response missing the data_selector key is treated as an empty page (full-refresh sources
        # don't fail loud here — they stop), mirroring the old _extract_items returning [].
        session = MockSession.return_value
        _wire(session, [_response({"other": [1]})])

        rows = _rows(_source("assets", _make_manager()))
        assert rows == []


class TestRetryableFetch:
    @mock.patch(CLIENT_SESSION_PATCH)
    @pytest.mark.parametrize("status_code", [429, 500, 503])
    def test_retryable_status_retries_then_succeeds(self, MockSession, status_code: int) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({}, status_code=status_code),
                _response({"assets": [{"identifier": 1}], "total_pages": 1}),
            ],
        )

        # Skip the client's real backoff sleep so the test stays fast.
        with mock.patch.object(RESTClient._send_request.retry, "sleep"):  # type: ignore[attr-defined]
            rows = _rows(_source("assets", _make_manager()))

        assert rows == [{"identifier": 1}]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_fails_loud(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "unauthorized"}, status_code=401)])

        with pytest.raises(Exception):
            _rows(_source("assets", _make_manager()))


class TestSourceResponse:
    def test_partitioned_endpoint_sets_datetime_partitioning(self) -> None:
        response = _source("assets", _make_manager())
        assert response.name == "assets"
        assert response.primary_keys == ["identifier"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
        assert response.partition_format == "month"

    def test_unpartitioned_endpoint_has_no_partitioning(self) -> None:
        response = _source("labels", _make_manager())
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestValidateCredentials:
    @pytest.mark.parametrize("bad_subdomain", ["", "has space", "bad/slash", "a.b", "http://x"])
    def test_rejects_unsafe_subdomain_without_network(self, bad_subdomain: str) -> None:
        with mock.patch(EZO_SESSION_PATCH) as mocked:
            assert validate_credentials("tok", bad_subdomain) == (False, None)
            mocked.assert_not_called()

    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [(200, True), (401, False), (403, False), (500, False)],
    )
    def test_maps_status_code(self, status_code: int, expected: bool) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response({}, status_code=status_code)
        with mock.patch(EZO_SESSION_PATCH, return_value=session):
            is_valid, _ = validate_credentials("tok", "acme")
            assert is_valid is expected

    def test_rate_limit_returns_specific_message(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response({}, status_code=429)
        with mock.patch(EZO_SESSION_PATCH, return_value=session):
            is_valid, error = validate_credentials("tok", "acme")
            assert is_valid is False
            assert error is not None
            assert "rate limit" in error.lower()

    def test_validation_session_disables_redirects_and_urllib3_retries(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response({}, status_code=200)
        with mock.patch(EZO_SESSION_PATCH, return_value=session) as mocked:
            validate_credentials("tok", "acme")
            assert mocked.call_args.kwargs["allow_redirects"] is False
            # Single-shot validation handles status codes itself; urllib3 retries stay off.
            assert mocked.call_args.kwargs["retry"].total == 0

    def test_network_error_is_false(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = Exception("boom")
        with mock.patch(EZO_SESSION_PATCH, return_value=session):
            assert validate_credentials("tok", "acme") == (False, None)
