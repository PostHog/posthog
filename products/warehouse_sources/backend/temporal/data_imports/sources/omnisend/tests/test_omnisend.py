import json
from typing import Any

import pytest
from unittest import mock

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.omnisend import (
    OMNISEND_API_BASE_URL,
    OMNISEND_BASE_URL,
    UNSUPPORTED_ENDPOINT_ERROR,
    OmnisendResumeConfig,
    omnisend_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.settings import (
    OMNISEND_2026_03_15,
    OMNISEND_ENDPOINTS,
    OMNISEND_V3,
)

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
        # The client's allowed-hosts guard reads `prepared.url`, so it must be a real string.
        return mock.MagicMock(url=request.url)

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock, api_version: str = OMNISEND_V3):
    return omnisend_source(
        "test-key", endpoint, team_id=1, job_id="j", api_version=api_version, resumable_source_manager=manager
    )


def _cursor_page(items: list[dict[str, Any]], after: str | None, has_more: bool, key: str = "contacts") -> Response:
    return _response({key: items, "paging": {"limit": 250, "hasMore": has_more, "cursors": {"after": after}}})


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
        rows = _rows(_source("contacts", manager))

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
        _rows(_source("contacts", manager))

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [OmnisendResumeConfig(next_url=_next_url(250))]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_terminal_page_does_not_save_state(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([{"contactID": "1"}], next_url=None)])

        manager = _make_manager()
        _rows(_source("contacts", manager))

        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_paging_block_terminates(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"contacts": [{"contactID": "1"}]})])

        manager = _make_manager()
        rows = _rows(_source("contacts", manager))

        assert session.send.call_count == 1
        assert rows == [{"contactID": "1"}]
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_campaigns_rows_read_from_singular_key(self, MockSession) -> None:
        # Omnisend's `/campaigns` nests rows under the singular `campaign`, unlike every other
        # endpoint's plural key. Extraction must follow that, or the sync fails loud on 0 rows.
        session = MockSession.return_value
        _wire(session, [_page([{"campaignID": "c1"}], next_url=None, key="campaign")])

        manager = _make_manager()
        rows = _rows(_source("campaigns", manager))

        assert rows == [{"campaignID": "c1"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([], next_url=None)])

        manager = _make_manager()
        rows = _rows(_source("contacts", manager))

        assert rows == []

    @pytest.mark.parametrize("endpoint", ["contacts", "campaigns"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_2026_follows_after_cursor_and_saves_it(self, MockSession, endpoint: str) -> None:
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _cursor_page([{"id": "1"}], after="c1", has_more=True, key=endpoint),
                _cursor_page([{"id": "2"}], after=None, has_more=False, key=endpoint),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source(endpoint, manager, OMNISEND_2026_03_15))

        assert snaps[0]["url"] == f"{OMNISEND_API_BASE_URL}/{endpoint}"
        assert "after" not in snaps[0]["params"]
        assert snaps[1]["params"]["after"] == "c1"
        assert rows == [{"id": "1"}, {"id": "2"}]
        assert [call.args[0] for call in manager.save_state.call_args_list] == [OmnisendResumeConfig(cursor="c1")]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_2026_stops_when_has_more_is_false_even_with_a_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_cursor_page([{"id": "1"}], after="c1", has_more=False)])

        rows = _rows(_source("contacts", _make_manager(), OMNISEND_2026_03_15))

        assert session.send.call_count == 1
        assert rows == [{"id": "1"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_2026_products_follow_paging_next_on_the_api_base(self, MockSession) -> None:
        session = MockSession.return_value
        next_url = f"{OMNISEND_API_BASE_URL}/products?limit=250&offset=250"
        snaps = _wire(
            session,
            [
                _page([{"id": "p1"}], next_url=next_url, key="products"),
                _page([{"id": "p2"}], next_url=None, key="products"),
            ],
        )

        rows = _rows(_source("products", _make_manager(), OMNISEND_2026_03_15))

        assert snaps[0]["url"] == f"{OMNISEND_API_BASE_URL}/products"
        assert snaps[1]["url"] == next_url
        assert rows == [{"id": "p1"}, {"id": "p2"}]


class TestResume:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_seeds_starting_url(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_page([{"contactID": "6"}], next_url=None)])

        manager = _make_manager(OmnisendResumeConfig(next_url=_next_url(500)))
        _rows(_source("contacts", manager))

        assert snaps[0]["url"] == _next_url(500)
        manager.load_state.assert_called_once()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_seeds_cursor_on_2026(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_cursor_page([{"id": "6"}], after=None, has_more=False)])

        manager = _make_manager(OmnisendResumeConfig(cursor="c5"))
        _rows(_source("contacts", manager, OMNISEND_2026_03_15))

        assert snaps[0]["params"]["after"] == "c5"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_v3_next_url_is_not_followed_under_2026(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_page([{"id": "p1"}], next_url=None, key="products")])

        manager = _make_manager(OmnisendResumeConfig(next_url=f"{OMNISEND_BASE_URL}/products?limit=250&offset=500"))
        _rows(_source("products", manager, OMNISEND_2026_03_15))

        assert snaps[0]["url"] == f"{OMNISEND_API_BASE_URL}/products"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_does_not_load_state_when_cannot_resume(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([{"contactID": "1"}], next_url=None)])

        manager = _make_manager()
        _rows(_source("contacts", manager))

        manager.load_state.assert_not_called()


class TestErrors:
    @pytest.mark.parametrize("status_code", [401, 403, 422])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_retryable_status_raises(self, MockSession, status_code: int) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "Forbidden"}, status_code=status_code)])

        manager = _make_manager()
        with pytest.raises(HTTPError):
            _rows(_source("contacts", manager))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_host_paging_next_is_not_followed(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([{"contactID": "1"}], next_url="https://attacker.example.com/contacts?offset=250")])

        with pytest.raises(ValueError, match="disallowed host"):
            _rows(_source("contacts", _make_manager()))
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_envelope_key_raises(self, MockSession) -> None:
        session = MockSession.return_value
        # 200 OK with an unexpected body shape must fail loudly, not sync zero rows.
        _wire(session, [_response({"unexpected": [], "paging": {"next": None}})])

        manager = _make_manager()
        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source("contacts", manager))

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
        rows = _rows(_source("contacts", manager))

        assert session.send.call_count == 2
        assert rows == [{"contactID": "1"}]


class TestAuthAndRedaction:
    @pytest.mark.parametrize(
        ("api_version", "base_url", "auth_header", "auth_value", "version_header"),
        [
            (OMNISEND_V3, OMNISEND_BASE_URL, "X-API-KEY", "test-key", None),
            (OMNISEND_2026_03_15, OMNISEND_API_BASE_URL, "Authorization", "Omnisend-API-Key test-key", "2026-03-15"),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_api_key_is_redacted_and_sent_as_header_auth(
        self,
        MockSession,
        api_version: str,
        base_url: str,
        auth_header: str,
        auth_value: str,
        version_header: str | None,
    ) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_page([{"id": "1"}], next_url=None)])

        manager = _make_manager()
        _rows(_source("contacts", manager, api_version))

        # The client's session is built with the sent credential in redact_values so it's masked in
        # logs and raised errors.
        assert auth_value in MockSession.call_args.kwargs["redact_values"]

        # The key rides in a header via framework api_key auth (not a hand-built header).
        auth = snaps[0]["auth"]
        assert auth.name == auth_header
        assert auth.location == "header"
        assert auth.api_key == auth_value
        assert snaps[0]["url"] == f"{base_url}/contacts"
        assert session.headers.get("Omnisend-Version") == version_header


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_ok"),
        [(200, True), (401, False), (403, False), (500, False)],
    )
    @mock.patch(OMNISEND_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code: int, expected_ok: bool) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        ok, code = validate_credentials("test-key", OMNISEND_V3)
        assert ok is expected_ok
        assert code == status_code

    @mock.patch(OMNISEND_SESSION_PATCH)
    def test_network_error(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("network down")
        ok, code = validate_credentials("test-key", OMNISEND_V3)
        assert ok is False
        assert code is None

    @pytest.mark.parametrize(
        ("api_version", "expected_url", "expected_headers"),
        [
            (OMNISEND_V3, f"{OMNISEND_BASE_URL}/contacts?limit=1", {"X-API-KEY": "test-key"}),
            (
                OMNISEND_2026_03_15,
                f"{OMNISEND_API_BASE_URL}/contacts?limit=1",
                {"Authorization": "Omnisend-API-Key test-key", "Omnisend-Version": "2026-03-15"},
            ),
        ],
    )
    @mock.patch(OMNISEND_SESSION_PATCH)
    def test_probe_uses_the_versioned_wire(
        self, mock_session, api_version: str, expected_url: str, expected_headers: dict[str, str]
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("test-key", api_version)

        call = mock_session.return_value.get.call_args
        assert call.args[0] == expected_url
        assert expected_headers.items() <= call.kwargs["headers"].items()


class TestSourceResponse:
    @pytest.mark.parametrize(
        ("api_version", "endpoint", "primary_key", "expects_partition"),
        [
            (OMNISEND_V3, "contacts", "contactID", True),
            (OMNISEND_V3, "campaigns", "campaignID", True),
            (OMNISEND_V3, "carts", "cartID", True),
            (OMNISEND_V3, "orders", "orderID", True),
            (OMNISEND_V3, "products", "productID", True),
            (OMNISEND_V3, "categories", "categoryID", False),
            (OMNISEND_2026_03_15, "contacts", "id", True),
            (OMNISEND_2026_03_15, "campaigns", "id", True),
            (OMNISEND_2026_03_15, "products", "id", True),
            (OMNISEND_2026_03_15, "categories", "categoryID", False),
        ],
    )
    def test_source_response_shape(
        self, api_version: str, endpoint: str, primary_key: str, expects_partition: bool
    ) -> None:
        response = _source(endpoint, _make_manager(), api_version)

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

    @pytest.mark.parametrize("endpoint", ["carts", "orders"])
    def test_endpoints_without_a_2026_list_endpoint_raise(self, endpoint: str) -> None:
        with pytest.raises(ValueError, match=UNSUPPORTED_ENDPOINT_ERROR):
            _source(endpoint, _make_manager(), OMNISEND_2026_03_15)

    def test_every_endpoint_partition_key_is_stable(self) -> None:
        # Partition keys must be creation-time fields, never mutable ones.
        for config in OMNISEND_ENDPOINTS.values():
            if config.partition_key is not None:
                assert config.partition_key == "createdAt"
