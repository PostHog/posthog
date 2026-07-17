from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.coingecko import coingecko
from products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.coingecko import (
    DEMO_BASE_URL,
    PAGE_SIZE,
    PLAN_DEMO,
    PLAN_PRO,
    PRO_BASE_URL,
    CoinGeckoResumeConfig,
    CoinGeckoRetryableError,
    _base_url,
    _build_url,
    _headers,
    _is_rate_limited,
    coingecko_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.settings import COINGECKO_ENDPOINTS


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_data: Any = None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)  # type: ignore[arg-type]


class _FakeSession:
    """Returns queued responses in order; records the URLs requested."""

    def __init__(self, responses: list[_FakeResponse]):
        self._responses = list(responses)
        self.requested_urls: list[str] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.requested_urls.append(url)
        return self._responses.pop(0)


def _manager(can_resume: bool = False, state: CoinGeckoResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


class TestBaseUrlAndHeaders:
    @parameterized.expand(
        [
            (PLAN_DEMO, DEMO_BASE_URL),
            (PLAN_PRO, PRO_BASE_URL),
            ("anything_else", DEMO_BASE_URL),
        ]
    )
    def test_base_url(self, plan: str, expected: str) -> None:
        assert _base_url(plan) == expected

    @parameterized.expand(
        [
            (PLAN_DEMO, "x-cg-demo-api-key"),
            (PLAN_PRO, "x-cg-pro-api-key"),
        ]
    )
    def test_headers_use_plan_specific_key_name(self, plan: str, header_name: str) -> None:
        headers = _headers(plan, "secret-key")
        assert headers[header_name] == "secret-key"
        assert headers["Accept"] == "application/json"

    def test_headers_omit_key_when_blank(self) -> None:
        headers = _headers(PLAN_DEMO, "")
        assert "x-cg-demo-api-key" not in headers

    def test_build_url_without_params(self) -> None:
        assert _build_url(DEMO_BASE_URL, "/coins/list", {}) == f"{DEMO_BASE_URL}/coins/list"

    def test_build_url_encodes_params(self) -> None:
        url = _build_url(DEMO_BASE_URL, "/coins/markets", {"vs_currency": "usd", "per_page": 250, "page": 1})
        assert url == f"{DEMO_BASE_URL}/coins/markets?vs_currency=usd&per_page=250&page=1"


class TestIsRateLimited:
    @parameterized.expand(
        [
            ("http_429", 429, None, True),
            ("ok_200", 200, [{"id": "btc"}], False),
            ("body_envelope_429", 200, {"status": {"error_code": 429}}, True),
            ("body_envelope_other_error", 200, {"status": {"error_code": 10002}}, False),
            ("non_json_body", 200, ValueError("not json"), False),
        ]
    )
    def test_is_rate_limited(self, _name: str, status: int, body: Any, expected: bool) -> None:
        assert _is_rate_limited(_FakeResponse(status_code=status, json_data=body)) is expected  # type: ignore[arg-type]


class TestFetch:
    @parameterized.expand([(429,), (500,), (503,)])
    def test_retryable_statuses_raise_retryable_error(self, status: int) -> None:
        session = _FakeSession([_FakeResponse(status_code=status, json_data=None)])
        with pytest.raises(CoinGeckoRetryableError):
            coingecko._fetch(session, "http://x", {}, mock.MagicMock())  # type: ignore[arg-type]

    def test_body_embedded_rate_limit_is_retryable(self) -> None:
        session = _FakeSession([_FakeResponse(status_code=200, json_data={"status": {"error_code": 429}})])
        with pytest.raises(CoinGeckoRetryableError):
            coingecko._fetch(session, "http://x", {}, mock.MagicMock())  # type: ignore[arg-type]

    def test_client_error_raises_http_error(self) -> None:
        session = _FakeSession([_FakeResponse(status_code=401, json_data=None, text="unauthorized")])
        with pytest.raises(requests.HTTPError):
            coingecko._fetch(session, "http://x", {}, mock.MagicMock())  # type: ignore[arg-type]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, True),
            ("unauthorized", 401, False),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.coingecko.make_tracked_session"
    )
    def test_status_mapping(self, _name: str, status: int, expected: bool, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _FakeResponse(status_code=status)
        assert validate_credentials(PLAN_DEMO, "key") is expected

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.coingecko.make_tracked_session"
    )
    def test_exception_returns_false(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials(PLAN_PRO, "key") is False

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.coingecko.make_tracked_session"
    )
    def test_pings_plan_host_with_key(self, mock_session: mock.MagicMock) -> None:
        get = mock_session.return_value.get
        get.return_value = _FakeResponse(status_code=200)
        validate_credentials(PLAN_PRO, "secret")
        url = get.call_args.args[0]
        assert url == f"{PRO_BASE_URL}/ping"
        assert get.call_args.kwargs["headers"]["x-cg-pro-api-key"] == "secret"
        # The key rides in a custom header the sampler can't predict, so it must be redacted by value.
        assert mock_session.call_args.kwargs["redact_values"] == ("secret",)


class TestGetRows:
    def _run(self, endpoint: str, responses: list[_FakeResponse], manager: mock.MagicMock) -> list[list[dict]]:
        session = _FakeSession(responses)
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.coingecko.make_tracked_session",
            return_value=session,
        ):
            return list(get_rows(PLAN_DEMO, "key", endpoint, mock.MagicMock(), manager))

    def test_single_request_endpoint_yields_once(self) -> None:
        manager = _manager()
        rows = [{"id": "bitcoin", "symbol": "btc", "name": "Bitcoin"}]
        batches = self._run("coins_list", [_FakeResponse(json_data=rows)], manager)
        assert batches == [rows]
        manager.save_state.assert_not_called()

    def test_single_request_empty_yields_nothing(self) -> None:
        batches = self._run("coins_list", [_FakeResponse(json_data=[])], _manager())
        assert batches == []

    def test_paginated_walks_until_short_page(self) -> None:
        manager = _manager()
        full_page = [{"id": f"c{i}"} for i in range(PAGE_SIZE)]
        short_page = [{"id": "last"}]
        batches = self._run(
            "coins_markets", [_FakeResponse(json_data=full_page), _FakeResponse(json_data=short_page)], manager
        )
        assert batches == [full_page, short_page]
        # State saved once after the first full page so a crash resumes at page 2.
        manager.save_state.assert_called_once_with(CoinGeckoResumeConfig(page=2))

    def test_paginated_terminates_on_empty_page(self) -> None:
        manager = _manager()
        full_page = [{"id": f"c{i}"} for i in range(PAGE_SIZE)]
        batches = self._run("coins_markets", [_FakeResponse(json_data=full_page), _FakeResponse(json_data=[])], manager)
        assert batches == [full_page]
        manager.save_state.assert_called_once_with(CoinGeckoResumeConfig(page=2))

    def test_paginated_resumes_from_saved_page(self) -> None:
        manager = _manager(can_resume=True, state=CoinGeckoResumeConfig(page=3))
        short_page = [{"id": "x"}]
        session = _FakeSession([_FakeResponse(json_data=short_page)])
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.coingecko.make_tracked_session",
            return_value=session,
        ):
            batches = list(get_rows(PLAN_DEMO, "key", "coins_markets", mock.MagicMock(), manager))
        assert batches == [short_page]
        assert "page=3" in session.requested_urls[0]

    def test_paginated_sends_extra_params(self) -> None:
        manager = _manager()
        session = _FakeSession([_FakeResponse(json_data=[{"id": "btc"}])])
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.coingecko.make_tracked_session",
            return_value=session,
        ):
            list(get_rows(PLAN_DEMO, "key", "coins_markets", mock.MagicMock(), manager))
        assert "vs_currency=usd" in session.requested_urls[0]

    def test_redacts_api_key_in_samples(self) -> None:
        manager = _manager()
        session = _FakeSession([_FakeResponse(json_data=[{"id": "btc"}])])
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.coingecko.make_tracked_session",
            return_value=session,
        ) as mock_session:
            list(get_rows(PLAN_DEMO, "secret", "coins_markets", mock.MagicMock(), manager))
        # The key rides in a custom header the sampler can't predict, so it must be redacted by value.
        assert mock_session.call_args.kwargs["redact_values"] == ("secret",)


class TestCoinGeckoSource:
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
        response = coingecko_source(PLAN_DEMO, "key", endpoint, mock.MagicMock(), mock.MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == expected_keys

    def test_every_settings_endpoint_builds_a_source_response(self) -> None:
        for endpoint in COINGECKO_ENDPOINTS:
            response = coingecko_source(PLAN_DEMO, "key", endpoint, mock.MagicMock(), mock.MagicMock())
            assert response.name == endpoint
            assert response.primary_keys == COINGECKO_ENDPOINTS[endpoint].primary_keys
