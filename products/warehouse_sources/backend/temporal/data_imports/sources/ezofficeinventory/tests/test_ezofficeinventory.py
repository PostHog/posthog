import json
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory import ezofficeinventory
from products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory.ezofficeinventory import (
    EZOfficeInventoryResumeConfig,
    _build_url,
    _extract_items,
    ezofficeinventory_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory.settings import (
    EZOFFICEINVENTORY_ENDPOINTS,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory.ezofficeinventory"


def _http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _manager(*, can_resume: bool = False, state: EZOfficeInventoryResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


class TestExtractItems:
    def test_simple_selector(self) -> None:
        config = EZOFFICEINVENTORY_ENDPOINTS["assets"]
        assert _extract_items({"assets": [{"identifier": 1}, {"identifier": 2}]}, config) == [
            {"identifier": 1},
            {"identifier": 2},
        ]

    @pytest.mark.parametrize(
        ("endpoint", "body", "expected"),
        [
            ("groups", {"groups": [{"group": {"id": 1}}, {"group": {"id": 2}}]}, [{"id": 1}, {"id": 2}]),
            ("vendors", {"vendors": [{"vendor": {"id": 9}}]}, [{"id": 9}]),
        ],
    )
    def test_unwraps_single_key_items(self, endpoint: str, body: dict[str, Any], expected: list[dict]) -> None:
        assert _extract_items(body, EZOFFICEINVENTORY_ENDPOINTS[endpoint]) == expected

    def test_unwrap_falls_back_when_inner_key_absent(self) -> None:
        # A row already shaped like the unwrapped object is passed through untouched.
        config = EZOFFICEINVENTORY_ENDPOINTS["groups"]
        assert _extract_items({"groups": [{"id": 5}]}, config) == [{"id": 5}]

    @pytest.mark.parametrize("body", [{}, {"assets": None}, {"assets": "not-a-list"}, {"other": [1]}])
    def test_missing_or_malformed_selector_returns_empty(self, body: dict[str, Any]) -> None:
        assert _extract_items(body, EZOFFICEINVENTORY_ENDPOINTS["assets"]) == []


class TestBuildUrl:
    def test_includes_page_and_extra_params(self) -> None:
        url = _build_url("acme", EZOFFICEINVENTORY_ENDPOINTS["checked_out_assets"], 3)
        assert url == "https://acme.ezofficeinventory.com/assets/filter.api?status=checked_out&page=3"

    def test_plain_endpoint_only_has_page(self) -> None:
        url = _build_url("acme", EZOFFICEINVENTORY_ENDPOINTS["assets"], 1)
        assert url == "https://acme.ezofficeinventory.com/assets.api?page=1"


class TestGetRows:
    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response]
    ) -> tuple[list[list[dict]], list[str]]:
        requested_urls: list[str] = []
        response_iter = iter(responses)

        def fake_get(url: str, **_kwargs: Any) -> Response:
            requested_urls.append(url)
            return next(response_iter)

        session = MagicMock()
        session.get.side_effect = fake_get

        with patch(f"{_MODULE}.make_tracked_session", return_value=session):
            batches = list(
                get_rows(
                    api_key="tok",
                    subdomain="acme",
                    endpoint=endpoint,
                    logger=MagicMock(),
                    resumable_source_manager=manager,
                )
            )
        return batches, requested_urls

    def test_sync_session_disables_redirects_and_urllib3_retries(self) -> None:
        manager = _manager()
        session = MagicMock()
        session.get.return_value = _http_response({"assets": []})
        with patch(f"{_MODULE}.make_tracked_session", return_value=session) as mocked:
            list(
                get_rows(
                    api_key="tok",
                    subdomain="acme",
                    endpoint="assets",
                    logger=MagicMock(),
                    resumable_source_manager=manager,
                )
            )
            assert mocked.call_args.kwargs["allow_redirects"] is False
            # urllib3 retries off so tenacity is the only retry layer (no compounded backoff).
            assert mocked.call_args.kwargs["retry"].total == 0

    def test_paginates_until_total_pages(self) -> None:
        manager = _manager()
        responses = [
            _http_response({"assets": [{"identifier": 1}], "total_pages": 2}),
            _http_response({"assets": [{"identifier": 2}], "total_pages": 2}),
        ]
        batches, urls = self._drive("assets", manager, responses)

        assert batches == [[{"identifier": 1}], [{"identifier": 2}]]
        assert urls == [
            "https://acme.ezofficeinventory.com/assets.api?page=1",
            "https://acme.ezofficeinventory.com/assets.api?page=2",
        ]
        # State is saved once (after page 1), pointing at page 2 — never after the terminal page.
        manager.save_state.assert_called_once_with(EZOfficeInventoryResumeConfig(next_page=2))

    def test_stops_on_empty_page_when_total_pages_absent(self) -> None:
        manager = _manager()
        responses = [
            _http_response({"assets": [{"identifier": 1}]}),
            _http_response({"assets": []}),
        ]
        batches, urls = self._drive("assets", manager, responses)

        assert batches == [[{"identifier": 1}]]
        assert len(urls) == 2
        manager.save_state.assert_called_once_with(EZOfficeInventoryResumeConfig(next_page=2))

    def test_first_page_empty_yields_nothing(self) -> None:
        manager = _manager()
        batches, urls = self._drive("assets", manager, [_http_response({"assets": []})])

        assert batches == []
        assert urls == ["https://acme.ezofficeinventory.com/assets.api?page=1"]
        manager.save_state.assert_not_called()

    def test_resumes_from_saved_page(self) -> None:
        manager = _manager(can_resume=True, state=EZOfficeInventoryResumeConfig(next_page=3))
        responses = [_http_response({"assets": [{"identifier": 30}], "total_pages": 3})]
        batches, urls = self._drive("assets", manager, responses)

        assert batches == [[{"identifier": 30}]]
        # Picks up at page 3 (the saved cursor), not page 1.
        assert urls == ["https://acme.ezofficeinventory.com/assets.api?page=3"]
        manager.save_state.assert_not_called()


class TestValidateCredentials:
    @pytest.mark.parametrize("bad_subdomain", ["", "has space", "bad/slash", "a.b", "http://x"])
    def test_rejects_unsafe_subdomain_without_network(self, bad_subdomain: str) -> None:
        with patch(f"{_MODULE}.make_tracked_session") as mocked:
            assert validate_credentials("tok", bad_subdomain) == (False, None)
            mocked.assert_not_called()

    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [(200, True), (401, False), (403, False), (500, False)],
    )
    def test_maps_status_code(self, status_code: int, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = _http_response({}, status_code=status_code)
        with patch(f"{_MODULE}.make_tracked_session", return_value=session):
            is_valid, _ = validate_credentials("tok", "acme")
            assert is_valid is expected

    def test_rate_limit_returns_specific_message(self) -> None:
        session = MagicMock()
        session.get.return_value = _http_response({}, status_code=429)
        with patch(f"{_MODULE}.make_tracked_session", return_value=session):
            is_valid, error = validate_credentials("tok", "acme")
            assert is_valid is False
            assert error is not None
            assert "rate limit" in error.lower()

    def test_validation_session_disables_redirects_and_urllib3_retries(self) -> None:
        session = MagicMock()
        session.get.return_value = _http_response({}, status_code=200)
        with patch(f"{_MODULE}.make_tracked_session", return_value=session) as mocked:
            validate_credentials("tok", "acme")
            assert mocked.call_args.kwargs["allow_redirects"] is False
            # Single-shot validation handles status codes itself; urllib3 retries stay off.
            assert mocked.call_args.kwargs["retry"].total == 0

    def test_network_error_is_false(self) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        with patch(f"{_MODULE}.make_tracked_session", return_value=session):
            assert validate_credentials("tok", "acme") == (False, None)


class TestSourceResponse:
    def test_partitioned_endpoint_sets_datetime_partitioning(self) -> None:
        response = ezofficeinventory_source(
            api_key="tok",
            subdomain="acme",
            endpoint="assets",
            logger=MagicMock(),
            resumable_source_manager=_manager(),
        )
        assert response.name == "assets"
        assert response.primary_keys == ["identifier"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
        assert response.partition_format == "month"

    def test_unpartitioned_endpoint_has_no_partitioning(self) -> None:
        response = ezofficeinventory_source(
            api_key="tok",
            subdomain="acme",
            endpoint="labels",
            logger=MagicMock(),
            resumable_source_manager=_manager(),
        )
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestRetryableFetch:
    @pytest.mark.parametrize("status_code", [429, 500, 503])
    def test_retryable_status_raises_then_succeeds(self, status_code: int) -> None:
        # The first response is retryable; tenacity retries and the second succeeds.
        session = MagicMock()
        session.get.side_effect = [
            _http_response({}, status_code=status_code),
            _http_response({"assets": [{"identifier": 1}], "total_pages": 1}),
        ]
        # Skip tenacity's real backoff sleep so the test stays fast.
        with (
            patch.object(ezofficeinventory._fetch_page.retry, "sleep"),  # type: ignore[attr-defined]
            patch(f"{_MODULE}.make_tracked_session", return_value=session),
        ):
            batches = list(
                get_rows(
                    api_key="tok",
                    subdomain="acme",
                    endpoint="assets",
                    logger=MagicMock(),
                    resumable_source_manager=_manager(),
                )
            )
        assert batches == [[{"identifier": 1}]]
        assert session.get.call_count == 2
