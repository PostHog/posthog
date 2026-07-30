import json
from typing import Any

import pytest
from unittest import mock

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.omnisend import (
    OMNISEND_BASE_URL,
    OmnisendResumeConfig,
    omnisend_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.settings import OMNISEND_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the omnisend module.
OMNISEND_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.omnisend.make_tracked_session"
)


def _response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.url = f"{OMNISEND_BASE_URL}/contacts"
    resp.reason = "OK" if status_code == 200 else "Client Error"
    resp.headers["Content-Type"] = "application/json"
    return resp


def _page(items: list[dict[str, Any]], next_url: str | None = None, key: str = "contacts") -> Response:
    return _response({key: items, "paging": {"next": next_url}})


def _next_url(offset: int) -> str:
    return f"{OMNISEND_BASE_URL}/contacts?limit=250&offset={offset}"


def _make_manager(resume_state: OmnisendResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session; return a list capturing each request's url/params/auth AT SEND TIME.

    ``request.url``/``request.params`` are mutated in place across pages (the next-URL paginator
    rewrites them), so snapshot a copy when each request is prepared instead of after the run.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_paging_next_until_exhausted(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _page([{"contactID": "1"}], next_url=_next_url(250)),
                _page([{"contactID": "2"}], next_url=None),
            ],
        )

        manager = _make_manager()
        rows = _rows(omnisend_source("test-key", "contacts", team_id=1, job_id="j", resumable_source_manager=manager))

        # First request hits the limit-seeded base path; second follows paging.next verbatim.
        assert snaps[0]["params"]["limit"] == 250
        assert "offset" not in snaps[0]["params"]
        assert snaps[0]["url"] == f"{OMNISEND_BASE_URL}/contacts"
        assert snaps[1]["url"] == _next_url(250)
        assert snaps[1]["params"] == {}
        assert rows == [{"contactID": "1"}, {"contactID": "2"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_each_non_terminal_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _page([{"contactID": "1"}], next_url=_next_url(250)),
                _page([{"contactID": "2"}], next_url=None),
            ],
        )

        manager = _make_manager()
        _rows(omnisend_source("test-key", "contacts", team_id=1, job_id="j", resumable_source_manager=manager))

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [OmnisendResumeConfig(next_url=_next_url(250))]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_terminal_page_does_not_save_state(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([{"contactID": "1"}], next_url=None)])

        manager = _make_manager()
        _rows(omnisend_source("test-key", "contacts", team_id=1, job_id="j", resumable_source_manager=manager))

        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_paging_block_terminates(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"contacts": [{"contactID": "1"}]})])

        manager = _make_manager()
        rows = _rows(omnisend_source("test-key", "contacts", team_id=1, job_id="j", resumable_source_manager=manager))

        assert session.send.call_count == 1
        assert rows == [{"contactID": "1"}]
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([], next_url=None)])

        manager = _make_manager()
        rows = _rows(omnisend_source("test-key", "contacts", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == []


class TestResume:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_seeds_starting_url(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_page([{"contactID": "6"}], next_url=None)])

        manager = _make_manager(OmnisendResumeConfig(next_url=_next_url(500)))
        _rows(omnisend_source("test-key", "contacts", team_id=1, job_id="j", resumable_source_manager=manager))

        assert snaps[0]["url"] == _next_url(500)
        manager.load_state.assert_called_once()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_does_not_load_state_when_cannot_resume(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([{"contactID": "1"}], next_url=None)])

        manager = _make_manager()
        _rows(omnisend_source("test-key", "contacts", team_id=1, job_id="j", resumable_source_manager=manager))

        manager.load_state.assert_not_called()


class TestErrors:
    @pytest.mark.parametrize("status_code", [401, 403, 422])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_retryable_status_raises(self, MockSession, status_code: int) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "Forbidden"}, status_code=status_code)])

        manager = _make_manager()
        with pytest.raises(HTTPError):
            _rows(omnisend_source("test-key", "contacts", team_id=1, job_id="j", resumable_source_manager=manager))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_envelope_key_raises(self, MockSession) -> None:
        session = MockSession.return_value
        # 200 OK with an unexpected body shape must fail loudly, not sync zero rows.
        _wire(session, [_response({"unexpected": [], "paging": {"next": None}})])

        manager = _make_manager()
        with pytest.raises(ValueError, match="matched nothing"):
            _rows(omnisend_source("test-key", "contacts", team_id=1, job_id="j", resumable_source_manager=manager))

    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_on_429_then_succeeds(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"error": "rate limited"}, status_code=429),
                _page([{"contactID": "1"}], next_url=None),
            ],
        )

        manager = _make_manager()
        rows = _rows(omnisend_source("test-key", "contacts", team_id=1, job_id="j", resumable_source_manager=manager))

        assert session.send.call_count == 2
        assert rows == [{"contactID": "1"}]


class TestAuthAndRedaction:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_api_key_is_redacted_and_sent_as_header_auth(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_page([{"contactID": "1"}], next_url=None)])

        manager = _make_manager()
        _rows(omnisend_source("test-key", "contacts", team_id=1, job_id="j", resumable_source_manager=manager))

        # The client's session is built with the api_key in redact_values so it's masked in logs
        # and raised errors.
        assert "test-key" in MockSession.call_args.kwargs["redact_values"]

        # The key rides in the X-API-KEY header via framework api_key auth (not a hand-built header).
        auth = snaps[0]["auth"]
        assert auth.name == "X-API-KEY"
        assert auth.location == "header"
        assert auth.api_key == "test-key"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_ok"),
        [(200, True), (401, False), (403, False), (500, False)],
    )
    @mock.patch(OMNISEND_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code: int, expected_ok: bool) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        ok, code = validate_credentials("test-key")
        assert ok is expected_ok
        assert code == status_code

    @mock.patch(OMNISEND_SESSION_PATCH)
    def test_network_error(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("network down")
        ok, code = validate_credentials("test-key")
        assert ok is False
        assert code is None


class TestSourceResponse:
    @pytest.mark.parametrize(
        ("endpoint", "primary_key", "expects_partition"),
        [
            ("contacts", "contactID", True),
            ("campaigns", "campaignID", True),
            ("carts", "cartID", True),
            ("orders", "orderID", True),
            ("products", "productID", True),
            ("categories", "categoryID", False),
        ],
    )
    def test_source_response_shape(self, endpoint: str, primary_key: str, expects_partition: bool) -> None:
        response = omnisend_source(
            "test-key", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager()
        )

        assert response.name == endpoint
        assert response.primary_keys == [primary_key]
        assert response.sort_mode == "asc"

        if expects_partition:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["createdAt"]
            assert response.partition_format == "month"
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_every_endpoint_partition_key_is_stable(self) -> None:
        # Partition keys must be creation-time fields, never mutable ones.
        for config in OMNISEND_ENDPOINTS.values():
            if config.partition_key is not None:
                assert config.partition_key == "createdAt"
