import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.coinmarketcap import (
    API_KEY_HEADER,
    CoinMarketCapPaginator,
    CoinMarketCapResumeConfig,
    coinmarketcap_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.settings import (
    COINMARKETCAP_ENDPOINTS,
    ENDPOINTS,
    PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


def _full_page() -> list[dict[str, Any]]:
    return [{"id": i} for i in range(PAGE_SIZE)]


class TestCoinMarketCapPaginator:
    def test_initial_state_is_one_based(self) -> None:
        paginator = CoinMarketCapPaginator()
        # CoinMarketCap's `start` is 1-based; start=0 is rejected with a 400.
        assert paginator.offset == 1
        assert paginator.limit == PAGE_SIZE
        assert paginator.has_next_page is True

    def test_init_request_emits_start_and_limit(self) -> None:
        paginator = CoinMarketCapPaginator()
        request = Request(method="GET", url="https://pro-api.coinmarketcap.com/v1/cryptocurrency/map")
        paginator.init_request(request)
        assert request.params["start"] == 1
        assert request.params["limit"] == PAGE_SIZE

    def test_advances_start_by_limit_on_full_page(self) -> None:
        paginator = CoinMarketCapPaginator()
        paginator.update_state(MagicMock(), _full_page())
        assert paginator.offset == 1 + PAGE_SIZE
        assert paginator.has_next_page is True

    def test_stops_on_short_page(self) -> None:
        paginator = CoinMarketCapPaginator()
        paginator.update_state(MagicMock(), [{"id": 1}])
        assert paginator.has_next_page is False

    def test_stops_on_empty_page(self) -> None:
        # An out-of-range `start` returns an empty `data` list with HTTP 200.
        paginator = CoinMarketCapPaginator()
        paginator.update_state(MagicMock(), [])
        assert paginator.has_next_page is False

    def test_get_resume_state_when_next_page(self) -> None:
        paginator = CoinMarketCapPaginator()
        paginator.update_state(MagicMock(), _full_page())
        assert paginator.get_resume_state() == {"start": 1 + PAGE_SIZE}

    def test_get_resume_state_none_on_terminal_page(self) -> None:
        paginator = CoinMarketCapPaginator()
        paginator.update_state(MagicMock(), [])
        assert paginator.get_resume_state() is None

    def test_set_resume_state_round_trip(self) -> None:
        paginator = CoinMarketCapPaginator()
        paginator.set_resume_state({"start": 5001})
        assert paginator.offset == 5001
        assert paginator.has_next_page is True

        request = Request(method="GET", url="https://pro-api.coinmarketcap.com/v1/cryptocurrency/map")
        paginator.init_request(request)
        assert request.params["start"] == 5001

    def test_set_resume_state_ignores_missing_start(self) -> None:
        paginator = CoinMarketCapPaginator()
        paginator.set_resume_state({})
        assert paginator.offset == 1


class TestGetResource:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_resource_shape(self, endpoint: str) -> None:
        resource = get_resource(endpoint)
        config = COINMARKETCAP_ENDPOINTS[endpoint]

        assert resource["name"] == endpoint
        assert resource["table_name"] == endpoint
        assert resource["write_disposition"] == "replace"
        assert resource["table_format"] == "delta"

        endpoint_def = cast(dict[str, Any], resource["endpoint"])
        assert endpoint_def["path"] == config.path
        assert endpoint_def["path"].startswith("/v1/")
        assert endpoint_def["data_selector"] == "data"

    @pytest.mark.parametrize("endpoint", ["cryptocurrency_map", "listings_latest", "fiat_map", "exchange_map"])
    def test_paginated_endpoints_pass_a_stable_sort(self, endpoint: str) -> None:
        # A stable `sort` keeps offset pagination from skipping/duplicating rows mid-sync.
        endpoint_def = cast(dict[str, Any], get_resource(endpoint)["endpoint"])
        assert "sort" in endpoint_def["params"]


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestCoinMarketCapSourceResumeBehavior:
    """End-to-end resume behaviour of ``coinmarketcap_source`` via ``rest_api_resource``."""

    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response]
    ) -> tuple[MagicMock, list[dict[str, Any]]]:
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.coinmarketcap.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            source = coinmarketcap_source(
                api_key="test-key",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )
            list(cast(Iterable[Any], source.items()))
            return mock_session, sent_params

    def _page_body(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        return {"data": items, "status": {"error_code": 0, "error_message": None}}

    @pytest.mark.parametrize("endpoint", ["cryptocurrency_map", "listings_latest", "fiat_map"])
    def test_fresh_run_saves_start_after_each_non_terminal_page(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(self._page_body(_full_page())),
            _make_http_response(self._page_body([{"id": "x"}])),
        ]
        _, sent_params = self._drive(endpoint, manager, responses)

        # First request starts at 1; the second carries the advanced start.
        assert [p.get("start") for p in sent_params] == [1, 1 + PAGE_SIZE]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [CoinMarketCapResumeConfig(start=1 + PAGE_SIZE)]

    def test_resume_seeds_paginator_with_saved_start(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = CoinMarketCapResumeConfig(start=1 + PAGE_SIZE)

        responses = [
            _make_http_response(self._page_body([{"id": "resumed"}])),
        ]
        _, sent_params = self._drive("cryptocurrency_map", manager, responses)

        assert [p.get("start") for p in sent_params] == [1 + PAGE_SIZE]
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(self._page_body([{"id": "only"}])),
        ]
        self._drive("cryptocurrency_map", manager, responses)

        manager.save_state.assert_not_called()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(self._page_body([{"id": "a"}])),
        ]
        self._drive("cryptocurrency_map", manager, responses)

        manager.load_state.assert_not_called()


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
            (401, False),
            (429, False),
            (500, False),
        ],
    )
    def test_status_code_mapping(self, status_code: int, expected_valid: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.coinmarketcap.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            response = MagicMock()
            response.status_code = status_code
            mock_session.get.return_value = response

            valid, error = validate_credentials("test-key")
            assert valid is expected_valid
            if expected_valid:
                assert error is None
            else:
                assert error is not None

    def test_sends_key_in_header(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.coinmarketcap.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            response = MagicMock()
            response.status_code = 200
            mock_session.get.return_value = response

            validate_credentials("test-key")

            headers = mock_session.get.call_args.kwargs["headers"]
            assert headers[API_KEY_HEADER] == "test-key"
            assert mock_session.get.call_args.kwargs["allow_redirects"] is False

    def test_network_error_returns_message(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.coinmarketcap.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.get.side_effect = Exception("boom")
            valid, error = validate_credentials("test-key")
            assert valid is False
            assert error == "boom"
