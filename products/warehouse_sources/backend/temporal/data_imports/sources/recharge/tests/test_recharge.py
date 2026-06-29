from datetime import UTC, date, datetime
from typing import Any

from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.recharge.recharge import (
    RechargeResumeConfig,
    _build_initial_params,
    _extract_items,
    _format_incremental_value,
    get_rows,
    recharge_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recharge.settings import RECHARGE_ENDPOINTS


def _mock_response(status_code: int = 200, json_body: dict[str, Any] | None = None, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.text = text
    response.json.return_value = json_body or {}
    return response


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00"),
            ("string_passthrough", "2026-03-04T00:00:00", "2026-03-04T00:00:00"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected

    def test_no_offset_suffix(self) -> None:
        # Recharge rejects timezone offsets in `*_min` filters.
        assert "+00:00" not in _format_incremental_value(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))


class TestBuildInitialParams:
    def test_incremental_on_updated_at_sets_min_and_sort(self) -> None:
        params = _build_initial_params(
            RECHARGE_ENDPOINTS["customers"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="updated_at",
        )
        assert params["updated_at_min"] == "2026-03-04T02:58:14"
        assert params["sort_by"] == "updated_at-asc"
        assert params["limit"] == 250

    def test_incremental_on_created_at_uses_created_field(self) -> None:
        params = _build_initial_params(
            RECHARGE_ENDPOINTS["orders"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            incremental_field="created_at",
        )
        assert params["created_at_min"] == "2026-01-01T00:00:00"
        assert params["sort_by"] == "created_at-asc"
        assert "updated_at_min" not in params

    def test_full_refresh_sorts_by_stable_id(self) -> None:
        params = _build_initial_params(
            RECHARGE_ENDPOINTS["customers"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params["sort_by"] == "id-asc"
        assert not any(k.endswith("_min") for k in params)

    @parameterized.expand(
        [
            ("default_endpoint_uses_max_page_size", "customers", 250),
            ("payment_methods_uses_smaller_page_size", "payment_methods", 50),
        ]
    )
    def test_page_size_is_per_endpoint(self, _name: str, endpoint: str, expected_limit: int) -> None:
        # `payment_methods` pages are too slow to generate within the read
        # timeout at the 250 max, so it requests smaller pages.
        params = _build_initial_params(
            RECHARGE_ENDPOINTS[endpoint],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params["limit"] == expected_limit

    @parameterized.expand(
        [
            # `collections` is full-refresh but still sortable -> keeps `id-asc`.
            ("collections", {"limit": 250, "sort_by": "id-asc"}),
            # `/products` on the 2021-11 API rejects `sort_by` outright -> limit only.
            ("products", {"limit": 250}),
        ]
    )
    def test_full_refresh_endpoint_ignores_incremental_inputs(self, endpoint: str, expected: dict) -> None:
        # Full-refresh endpoints must never emit a `*_min` filter even when the
        # user supplies incremental inputs; products additionally omits `sort_by`.
        params = _build_initial_params(
            RECHARGE_ENDPOINTS[endpoint],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            incremental_field="updated_at",
        )
        assert params == expected
        assert not any(k.endswith("_min") for k in params)


class TestExtractItems:
    @parameterized.expand(
        [
            ("resource_key_present", {"customers": [{"id": 1}], "next_cursor": "c"}, "customers", [{"id": 1}]),
            ("fallback_to_first_list", {"data": [{"id": 2}], "next_cursor": None}, "customers", [{"id": 2}]),
            ("empty_when_no_list", {"next_cursor": None}, "customers", []),
            ("ignores_cursor_keys", {"next_cursor": "x", "previous_cursor": "y"}, "orders", []),
        ]
    )
    def test_extract_items(self, _name: str, payload: dict, resource_key: str, expected: list) -> None:
        assert _extract_items(payload, resource_key) == expected


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("server_error", 500, False),
            ("forbidden", 403, False),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.recharge.recharge.make_tracked_session")
    def test_status_mapping(self, _name: str, status_code: int, expected_ok: bool, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = _mock_response(status_code=status_code)
        ok, error = validate_credentials("token")
        assert ok is expected_ok
        if not expected_ok:
            assert error is not None

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.recharge.recharge.make_tracked_session")
    def test_network_error_returns_false(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        ok, error = validate_credentials("token")
        assert ok is False
        assert error is not None

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.recharge.recharge.make_tracked_session")
    def test_token_is_redacted_from_captured_samples(self, mock_session: MagicMock) -> None:
        # The `X-Recharge-Access-Token` header isn't in the shared auth-header
        # denylist, so the token must be passed as a `redact_values` literal to
        # keep it out of captured HTTP samples.
        mock_session.return_value.get.return_value = _mock_response(status_code=200)
        validate_credentials("secret-token")
        assert mock_session.call_args.kwargs["redact_values"] == ("secret-token",)


class TestGetRows:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.recharge.recharge.make_tracked_session")
    def test_paginates_until_no_cursor_and_saves_state_after_yield(self, mock_session: MagicMock) -> None:
        pages = [
            _mock_response(json_body={"customers": [{"id": 1}], "next_cursor": "cursor-2"}),
            _mock_response(json_body={"customers": [{"id": 2}], "next_cursor": None}),
        ]
        mock_session.return_value.get.side_effect = pages

        manager = MagicMock()
        manager.can_resume.return_value = False

        batches = list(
            get_rows(
                api_key="token",
                endpoint="customers",
                logger=MagicMock(),
                resumable_source_manager=manager,
            )
        )

        assert batches == [[{"id": 1}], [{"id": 2}]]
        # State saved once — only when there's a next cursor to resume from.
        manager.save_state.assert_called_once()
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, RechargeResumeConfig)
        assert saved.endpoint == "customers"
        assert saved.cursor == "cursor-2"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.recharge.recharge.make_tracked_session")
    def test_token_is_redacted_from_captured_samples(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = _mock_response(
            json_body={"customers": [{"id": 1}], "next_cursor": None}
        )
        manager = MagicMock()
        manager.can_resume.return_value = False

        list(
            get_rows(api_key="secret-token", endpoint="customers", logger=MagicMock(), resumable_source_manager=manager)
        )

        assert mock_session.call_args.kwargs["redact_values"] == ("secret-token",)

    @parameterized.expand(
        [
            ("payment_methods_uses_smaller_limit", "payment_methods", 50),
            ("customers_use_default_limit", "customers", 250),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.recharge.recharge.make_tracked_session")
    def test_cursor_pages_use_per_endpoint_limit(
        self, _name: str, endpoint: str, expected_limit: int, mock_session: MagicMock
    ) -> None:
        # Both the first page and cursor pages must carry the per-endpoint limit;
        # for `payment_methods` that's 50 (to avoid the 60s read timeout), for
        # other endpoints it's the 250 max — otherwise the second page would time
        # out at the wrong size again.
        mock_session.return_value.get.side_effect = [
            _mock_response(json_body={endpoint: [{"id": 1}], "next_cursor": "cursor-2"}),
            _mock_response(json_body={endpoint: [{"id": 2}], "next_cursor": None}),
        ]
        manager = MagicMock()
        manager.can_resume.return_value = False

        list(get_rows(api_key="t", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=manager))

        first_url, second_url = (call.args[0] for call in mock_session.return_value.get.call_args_list)
        assert f"limit={expected_limit}" in first_url
        assert "cursor=cursor-2" in second_url
        assert f"limit={expected_limit}" in second_url

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.recharge.recharge.make_tracked_session")
    def test_products_request_omits_sort_by(self, mock_session: MagicMock) -> None:
        # Regression: the 2021-11 `/products` endpoint 422s on `sort_by`, so the
        # initial request must send only `limit` (no sort, no timestamp filter).
        mock_session.return_value.get.return_value = _mock_response(
            json_body={"products": [{"id": 1}], "next_cursor": None}
        )

        manager = MagicMock()
        manager.can_resume.return_value = False

        list(get_rows(api_key="t", endpoint="products", logger=MagicMock(), resumable_source_manager=manager))

        requested_url = mock_session.return_value.get.call_args.args[0]
        assert "products?limit=250" in requested_url
        assert "sort_by" not in requested_url
        assert "_min" not in requested_url

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.recharge.recharge.make_tracked_session")
    def test_resumes_from_saved_cursor_when_endpoint_matches(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = _mock_response(
            json_body={"customers": [{"id": 9}], "next_cursor": None}
        )

        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = RechargeResumeConfig(endpoint="customers", cursor="saved-cursor")

        list(get_rows(api_key="t", endpoint="customers", logger=MagicMock(), resumable_source_manager=manager))

        requested_url = mock_session.return_value.get.call_args.args[0]
        # When following a cursor we only send cursor + limit, no sort/filters.
        assert "cursor=saved-cursor" in requested_url
        assert "sort_by" not in requested_url

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.recharge.recharge.make_tracked_session")
    def test_ignores_resume_state_from_different_endpoint(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = _mock_response(
            json_body={"orders": [{"id": 1}], "next_cursor": None}
        )

        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = RechargeResumeConfig(endpoint="customers", cursor="saved-cursor")

        list(get_rows(api_key="t", endpoint="orders", logger=MagicMock(), resumable_source_manager=manager))

        requested_url = mock_session.return_value.get.call_args.args[0]
        assert "cursor=saved-cursor" not in requested_url
        assert "sort_by=id-asc" in requested_url


class TestRechargeSource:
    @parameterized.expand([(name,) for name in RECHARGE_ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = recharge_source(
            api_key="token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
