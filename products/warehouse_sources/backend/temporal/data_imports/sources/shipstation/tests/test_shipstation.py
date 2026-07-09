from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.settings import (
    ENDPOINTS,
    SHIPSTATION_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.shipstation import (
    PAGE_SIZE,
    ShipStationResumeConfig,
    _build_params,
    _extract_items,
    _format_date_filter,
    get_rows,
    shipstation_source,
    validate_credentials,
)


def _make_manager(resume_state: ShipStationResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(body: Any) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = 200
    resp.ok = True
    return resp


class TestFormatDateFilter:
    @pytest.mark.parametrize(
        "value, expected",
        [
            # Naive datetimes are assumed to already be Pacific (from API rows).
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02 03:04:05"),
            # Aware datetimes are converted to Pacific (UTC-8 in January).
            (datetime(2024, 1, 2, 11, 4, 5, tzinfo=UTC), "2024-01-02 03:04:05"),
            (date(2024, 1, 2), "2024-01-02 00:00:00"),
            ("2024-01-02T03:04:05.0000000", "2024-01-02 03:04:05"),
            ("2024-01-02 03:04:05", "2024-01-02 03:04:05"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_date_filter(value) == expected


class TestBuildParams:
    @pytest.mark.parametrize(
        "incremental_field, expected_filter_key, expected_sort_by",
        [
            ("modifyDate", "modifyDateStart", "ModifyDate"),
            ("createDate", "createDateStart", "CreateDate"),
        ],
    )
    def test_incremental_orders_filters_and_sorts_on_cursor(
        self, incremental_field, expected_filter_key, expected_sort_by
    ):
        params = _build_params(
            SHIPSTATION_ENDPOINTS["orders"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5),
            incremental_field=incremental_field,
            page=1,
        )

        assert params[expected_filter_key] == "2024-01-02 03:04:05"
        assert params["sortBy"] == expected_sort_by
        assert params["sortDir"] == "ASC"
        assert params["pageSize"] == PAGE_SIZE
        assert params["page"] == 1

    def test_full_refresh_orders_still_sorts_for_stable_pages(self):
        params = _build_params(
            SHIPSTATION_ENDPOINTS["orders"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
            page=2,
        )

        assert "modifyDateStart" not in params
        assert "createDateStart" not in params
        assert params["sortBy"] == "ModifyDate"
        assert params["page"] == 2

    def test_fulfillments_have_filter_but_no_sort(self):
        params = _build_params(
            SHIPSTATION_ENDPOINTS["fulfillments"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5),
            incremental_field="createDate",
            page=1,
        )

        assert params["createDateStart"] == "2024-01-02 03:04:05"
        assert "sortBy" not in params

    @pytest.mark.parametrize("endpoint", ["stores", "warehouses"])
    def test_unpaginated_endpoints_have_no_params(self, endpoint):
        params = _build_params(
            SHIPSTATION_ENDPOINTS[endpoint],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
            page=1,
        )

        assert params == {}


class TestExtractItems:
    def test_wrapped_response(self):
        assert _extract_items({"orders": [{"orderId": 1}], "pages": 2}, "orders") == [{"orderId": 1}]

    def test_bare_array_response(self):
        assert _extract_items([{"storeId": 1}], None) == [{"storeId": 1}]

    @pytest.mark.parametrize(
        "data, data_key",
        [
            ({}, "orders"),
            ({"orders": None}, "orders"),
            ({"orders": "nope"}, "orders"),
            ({"unexpected": "dict"}, None),
        ],
    )
    def test_missing_or_malformed_returns_empty(self, data, data_key):
        assert _extract_items(data, data_key) == []


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.shipstation.make_tracked_session"
    )
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("key", "secret") is expected

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.shipstation.make_tracked_session"
    )
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key", "secret") is False


class TestGetRows:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.shipstation.make_tracked_session"
    )
    def test_paginates_using_pages_total(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"orders": [{"orderId": 1}], "page": 1, "pages": 2}),
            _response({"orders": [{"orderId": 2}], "page": 2, "pages": 2}),
        ]

        manager = _make_manager()
        batches = list(get_rows("key", "secret", "orders", mock.MagicMock(), manager))

        assert [item["orderId"] for batch in batches for item in batch] == [1, 2]
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].page == 2
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert parse_qs(urlparse(second_url).query)["page"] == ["2"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.shipstation.make_tracked_session"
    )
    def test_resumes_from_saved_page(self, mock_session):
        mock_session.return_value.get.return_value = _response({"orders": [{"orderId": 9}], "page": 5, "pages": 5})

        manager = _make_manager(ShipStationResumeConfig(page=5))
        list(get_rows("key", "secret", "orders", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["page"] == ["5"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.shipstation.make_tracked_session"
    )
    def test_bare_array_endpoint_fetches_once(self, mock_session):
        mock_session.return_value.get.return_value = _response([{"storeId": 1}])

        manager = _make_manager()
        batches = list(get_rows("key", "secret", "stores", mock.MagicMock(), manager))

        assert batches == [[{"storeId": 1}]]
        assert mock_session.return_value.get.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.shipstation.make_tracked_session"
    )
    def test_incremental_request_includes_filter(self, mock_session):
        mock_session.return_value.get.return_value = _response({"orders": [], "pages": 0})

        manager = _make_manager()
        list(
            get_rows(
                "key",
                "secret",
                "orders",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value="2024-01-02T03:04:05.0000000",
                incremental_field="modifyDate",
            )
        )

        url = mock_session.return_value.get.call_args.args[0]
        query = parse_qs(urlparse(url).query)
        assert query["modifyDateStart"] == ["2024-01-02 03:04:05"]
        assert query["sortBy"] == ["ModifyDate"]
        assert query["sortDir"] == ["ASC"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.shipstation.make_tracked_session"
    )
    def test_empty_response_stops_without_saving_state(self, mock_session):
        mock_session.return_value.get.return_value = _response({"orders": [], "pages": 0})

        manager = _make_manager()
        batches = list(get_rows("key", "secret", "orders", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.shipstation.make_tracked_session"
    )
    def test_missing_pages_field_falls_back_to_short_page_termination(self, mock_session):
        mock_session.return_value.get.return_value = _response({"orders": [{"orderId": 1}]})

        manager = _make_manager()
        batches = list(get_rows("key", "secret", "orders", mock.MagicMock(), manager))

        assert len(batches) == 1
        assert mock_session.return_value.get.call_count == 1


class TestShipStationSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = SHIPSTATION_ENDPOINTS[endpoint]
        response = shipstation_source("key", "secret", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(SHIPSTATION_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "createDate"
