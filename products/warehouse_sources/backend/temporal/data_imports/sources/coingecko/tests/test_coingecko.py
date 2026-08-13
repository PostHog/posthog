import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.coingecko import (
    DEMO_BASE_URL,
    PAGE_SIZE,
    PLAN_DEMO,
    PLAN_PRO,
    PRO_BASE_URL,
    CoinGeckoResumeConfig,
    coingecko_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.settings import COINGECKO_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the coingecko module.
COINGECKO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.coingecko.make_tracked_session"
)
# Neuter tenacity's backoff so retry tests don't actually sleep.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(body: Any, *, status: int = 200, compact: bool = False) -> Response:
    resp = Response()
    resp.status_code = status
    separators = (",", ":") if compact else None
    resp._content = json.dumps(body, separators=separators).encode()
    resp.url = "https://api.coingecko.com/api/v3/x"
    return resp


def _rate_limit_body(*, compact: bool) -> Response:
    # CoinGecko's keyless/demo tier reports rate limiting inside a 200 body.
    return _response({"status": {"error_code": 429, "error_message": "rate limited"}}, compact=compact)


def _manager(resume_state: CoinGeckoResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's URL/params/auth AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy per request.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        auth = request.auth
        snapshots.append(
            {
                "url": request.url,
                "params": dict(request.params or {}),
                "auth_name": getattr(auth, "name", None),
                "auth_key": getattr(auth, "api_key", None),
            }
        )
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(plan: str, api_key: str, endpoint: str, manager: mock.MagicMock):
    return coingecko_source(
        plan=plan,
        api_key=api_key,
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestReferenceEndpoints:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_request_yields_rows(self, MockSession) -> None:
        session = MockSession.return_value
        rows = [{"id": "bitcoin", "symbol": "btc", "name": "Bitcoin"}]
        _wire(session, [_response(rows)])

        assert _rows(_source(PLAN_DEMO, "key", "coins_list", _manager())) == rows
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_body_yields_nothing_and_no_extra_request(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        assert _rows(_source(PLAN_DEMO, "key", "coins_list", _manager())) == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_fails_loud(self, MockSession) -> None:
        session = MockSession.return_value
        # A 200 that isn't a bare array is an unexpected/changed shape — fail loud, not a garbage row.
        _wire(session, [_response({"unexpected": "object"})])

        with pytest.raises(ValueError, match="list response body"):
            _rows(_source(PLAN_DEMO, "key", "coins_list", _manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_reference_endpoint_never_checkpoints(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "eth"}])])

        manager = _manager()
        _rows(_source(PLAN_DEMO, "key", "asset_platforms", manager))
        manager.save_state.assert_not_called()


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_walks_until_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"id": f"c{i}"} for i in range(PAGE_SIZE)]
        short_page = [{"id": "last"}]
        snaps = _wire(session, [_response(full_page), _response(short_page)])

        manager = _manager()
        rows = _rows(_source(PLAN_DEMO, "key", "coins_markets", manager))

        assert rows == [*full_page, *short_page]
        # Page number progresses 1 -> 2; the short page ends it without a third request.
        assert session.send.call_count == 2
        assert snaps[0]["params"]["page"] == 1
        assert snaps[0]["params"]["per_page"] == PAGE_SIZE
        assert snaps[1]["params"]["page"] == 2
        # Checkpoint saved once after the first full page, pointing at the next page.
        manager.save_state.assert_called_once_with(CoinGeckoResumeConfig(page=2))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_terminates_on_empty_page(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"id": f"c{i}"} for i in range(PAGE_SIZE)]
        _wire(session, [_response(full_page), _response([])])

        manager = _manager()
        rows = _rows(_source(PLAN_DEMO, "key", "coins_markets", manager))

        assert rows == full_page
        assert session.send.call_count == 2
        manager.save_state.assert_called_once_with(CoinGeckoResumeConfig(page=2))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_makes_one_request_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "a"}, {"id": "b"}])])

        manager = _manager()
        rows = _rows(_source(PLAN_DEMO, "key", "coins_markets", manager))

        assert [r["id"] for r in rows] == ["a", "b"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response([{"id": "x"}])])

        manager = _manager(CoinGeckoResumeConfig(page=3))
        _rows(_source(PLAN_DEMO, "key", "coins_markets", manager))

        assert snaps[0]["params"]["page"] == 3

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sends_static_extra_params(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response([{"id": "btc"}])])

        _rows(_source(PLAN_DEMO, "key", "coins_markets", _manager()))
        assert snaps[0]["params"]["vs_currency"] == "usd"


class TestRateLimitAndErrors:
    @parameterized.expand([("compact", True), ("spaced", False)])
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_in_body_rate_limit_is_retried(self, _name: str, compact: bool, MockSession, _sleep) -> None:
        session = MockSession.return_value
        good = [{"id": "btc"}]
        # A 200 body carrying the rate-limit envelope must be retried, then the retry succeeds —
        # regardless of the server's JSON whitespace.
        _wire(session, [_rate_limit_body(compact=compact), _response(good)])

        rows = _rows(_source(PLAN_DEMO, "key", "coins_list", _manager()))
        assert rows == good
        assert session.send.call_count == 2

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_http_429_status_is_retried(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        good = [{"id": "btc"}]
        _wire(session, [_response({}, status=429), _response(good)])

        rows = _rows(_source(PLAN_DEMO, "key", "coins_list", _manager()))
        assert rows == good
        assert session.send.call_count == 2

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_http_500_status_is_retried(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        good = [{"id": "btc"}]
        _wire(session, [_response({}, status=500), _response(good)])

        rows = _rows(_source(PLAN_DEMO, "key", "coins_list", _manager()))
        assert rows == good
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_401_surfaces_as_http_error(self, MockSession) -> None:
        session = MockSession.return_value
        # 401 is a genuine, non-retryable auth error — it must surface (get_non_retryable_errors
        # matches on the "401 ... for url: <host>" message).
        resp = _response({"status": {"error_code": 10011, "error_message": "invalid key"}}, status=401)
        _wire(session, [resp])

        with pytest.raises(requests.HTTPError, match="401"):
            _rows(_source(PLAN_DEMO, "key", "coins_list", _manager()))
        assert session.send.call_count == 1


class TestHostHeaderAndRedaction:
    @parameterized.expand(
        [
            (PLAN_DEMO, DEMO_BASE_URL, "x-cg-demo-api-key"),
            (PLAN_PRO, PRO_BASE_URL, "x-cg-pro-api-key"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_plan_selects_host_and_key_header(self, plan: str, base_url: str, header_name: str, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response([{"id": "btc"}])])

        _rows(_source(plan, "secret", "coins_list", _manager()))
        assert snaps[0]["url"].startswith(base_url)
        # The key rides in the plan-specific header via framework auth (redacted by value).
        assert snaps[0]["auth_name"] == header_name
        assert snaps[0]["auth_key"] == "secret"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_api_key_registered_for_redaction(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "btc"}])])

        _rows(_source(PLAN_DEMO, "secret", "coins_list", _manager()))
        # RESTClient builds its tracked session with the auth secret in redact_values.
        assert MockSession.call_args.kwargs["redact_values"] == ("secret",)


class TestValidateCredentials:
    @parameterized.expand([("valid", 200, True), ("unauthorized", 401, False)])
    @mock.patch(COINGECKO_SESSION_PATCH)
    def test_status_mapping(self, _name: str, status: int, expected: bool, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials(PLAN_DEMO, "key") is expected

    @mock.patch(COINGECKO_SESSION_PATCH)
    def test_transient_error_returns_false(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials(PLAN_PRO, "key") is False

    @mock.patch(COINGECKO_SESSION_PATCH)
    def test_pings_plan_host_with_key_and_redaction(self, mock_session: mock.MagicMock) -> None:
        get = mock_session.return_value.get
        get.return_value = mock.MagicMock(status_code=200)
        validate_credentials(PLAN_PRO, "secret")

        assert get.call_args.args[0] == f"{PRO_BASE_URL}/ping"
        assert get.call_args.kwargs["headers"]["x-cg-pro-api-key"] == "secret"
        assert mock_session.call_args.kwargs["redact_values"] == ("secret",)


class TestSourceResponse:
    @parameterized.expand(
        [
            ("coins_list", ["id"]),
            ("coins_markets", ["id"]),
            ("coins_categories", ["id"]),
            ("coins_categories_list", ["category_id"]),
            ("exchanges", ["id"]),
            ("exchanges_list", ["id"]),
            ("asset_platforms", ["id"]),
        ]
    )
    def test_primary_keys_per_endpoint(self, endpoint: str, expected_keys: list[str]) -> None:
        response = _source(PLAN_DEMO, "key", endpoint, _manager())
        assert response.name == endpoint
        assert response.primary_keys == expected_keys

    def test_every_settings_endpoint_builds_a_source_response(self) -> None:
        for endpoint in COINGECKO_ENDPOINTS:
            response = _source(PLAN_DEMO, "key", endpoint, _manager())
            assert response.name == endpoint
            assert response.primary_keys == COINGECKO_ENDPOINTS[endpoint].primary_keys
