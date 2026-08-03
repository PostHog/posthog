import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    APIKeyAuth,
    HttpBasicAuth,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.settings import (
    ENDPOINTS,
    SHIPSTATION_ENDPOINTS,
    SHIPSTATION_V1,
    SHIPSTATION_V2,
    SHIPSTATION_V2_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.shipstation import (
    PAGE_SIZE,
    SHIPSTATION_DIALECTS,
    ShipStationResumeConfig,
    _build_auth,
    _build_params,
    _format_date_filter,
    shipstation_source,
    validate_credentials,
)

V1_DIALECT = SHIPSTATION_DIALECTS[SHIPSTATION_V1]
V2_DIALECT = SHIPSTATION_DIALECTS[SHIPSTATION_V2]

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the shipstation module.
SHIPSTATION_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.shipstation.shipstation.make_tracked_session"
)


def _response(body: Any) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: ShipStationResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's query params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages (the paginator bumps ``page``),
    so inspecting it after the run shows only the final state — snapshot a copy per prepared request.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return shipstation_source(
        "key",
        "secret",
        endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


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

    @pytest.mark.parametrize(
        "value, expected",
        [
            # v2 (ShipEngine) filters in ISO 8601 UTC, not Pacific.
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
            # Naive values from v2 rows are already UTC.
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00Z"),
            ("2024-01-02T03:04:05.657Z", "2024-01-02T03:04:05.657Z"),
        ],
    )
    def test_format_values_v2_uses_iso_utc(self, value, expected):
        assert _format_date_filter(value, V2_DIALECT) == expected


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
        )

        assert params[expected_filter_key] == "2024-01-02 03:04:05"
        assert params["sortBy"] == expected_sort_by
        assert params["sortDir"] == "ASC"
        assert params["pageSize"] == PAGE_SIZE

    def test_full_refresh_orders_still_sorts_for_stable_pages(self):
        params = _build_params(
            SHIPSTATION_ENDPOINTS["orders"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )

        assert "modifyDateStart" not in params
        assert "createDateStart" not in params
        assert params["sortBy"] == "ModifyDate"

    def test_v2_uses_snake_case_filter_and_sort_spellings(self):
        # v1 spellings (createDateStart / sortBy=CreateDate / ASC) leaking into a v2 request would
        # be rejected or silently ignored by the v2 API.
        params = _build_params(
            SHIPSTATION_V2_ENDPOINTS["shipments"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
            incremental_field="created_at",
            dialect=V2_DIALECT,
        )

        assert params["created_at_start"] == "2024-01-02T03:04:05Z"
        assert params["sort_by"] == "created_at"
        assert params["sort_dir"] == "asc"
        assert params["page_size"] == PAGE_SIZE

    def test_fulfillments_have_filter_but_no_sort(self):
        params = _build_params(
            SHIPSTATION_ENDPOINTS["fulfillments"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5),
            incremental_field="createDate",
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
        )

        assert params == {}


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
    @mock.patch(SHIPSTATION_SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        ok, _error = validate_credentials("key", "secret")
        assert ok is expected

    @mock.patch(SHIPSTATION_SESSION_PATCH)
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        ok, _error = validate_credentials("key", "secret")
        assert ok is False

    def test_v1_requires_secret_without_probing(self):
        # v1 authenticates with a key + secret pair; a missing secret must fail before any request.
        ok, error = validate_credentials("key", None, SHIPSTATION_V1)
        assert ok is False
        assert error is not None and "secret" in error.lower()

    @mock.patch(SHIPSTATION_SESSION_PATCH)
    def test_v2_probes_v2_host_with_api_key_only(self, mock_session):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        ok, _error = validate_credentials("key", None, SHIPSTATION_V2)

        assert ok is True
        assert mock_session.return_value.get.call_args.args[0] == "https://api.shipstation.com/v2/carriers"


class TestExtractionShapes:
    """The framework's data_selector replaces the old _extract_items helper; assert the same
    row-level result for the response shapes the real API returns."""

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_wrapped_response_extracts_data_key(self, MockSession):
        _wire(MockSession.return_value, [_response({"orders": [{"orderId": 1}], "page": 1, "pages": 1})])

        rows = _rows(_source("orders", _make_manager()))

        assert rows == [{"orderId": 1}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bare_array_response_yields_rows(self, MockSession):
        _wire(MockSession.return_value, [_response([{"storeId": 1}])])

        rows = _rows(_source("stores", _make_manager()))

        assert rows == [{"storeId": 1}]

    @pytest.mark.parametrize("body", [{}, {"orders": None}])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_or_null_data_key_yields_no_rows(self, MockSession, body):
        # ``pages`` absent + no/empty data ends pagination after one short/empty page.
        _wire(MockSession.return_value, [_response(body)])

        rows = _rows(_source("orders", _make_manager()))

        assert rows == []


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_using_pages_total(self, MockSession):
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"orders": [{"orderId": 1}], "page": 1, "pages": 2}),
                _response({"orders": [{"orderId": 2}], "page": 2, "pages": 2}),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("orders", manager))

        assert [row["orderId"] for row in rows] == [1, 2]
        assert params[0]["page"] == 1
        assert params[0]["pageSize"] == PAGE_SIZE
        assert params[1]["page"] == 2
        # Checkpoint saved once after the first page (points at page 2); the ``pages`` total ends it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == ShipStationResumeConfig(page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession):
        session = MockSession.return_value
        params = _wire(session, [_response({"orders": [{"orderId": 9}], "page": 5, "pages": 5})])

        manager = _make_manager(ShipStationResumeConfig(page=5))
        rows = _rows(_source("orders", manager))

        assert [row["orderId"] for row in rows] == [9]
        assert params[0]["page"] == 5
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bare_array_endpoint_fetches_once(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([{"storeId": 1}])])

        manager = _make_manager()
        rows = _rows(_source("stores", manager))

        assert rows == [{"storeId": 1}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_request_includes_filter(self, MockSession):
        session = MockSession.return_value
        params = _wire(session, [_response({"orders": [], "pages": 0})])

        _rows(
            _source(
                "orders",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value="2024-01-02T03:04:05.0000000",
                incremental_field="modifyDate",
            )
        )

        assert params[0]["modifyDateStart"] == "2024-01-02 03:04:05"
        assert params[0]["sortBy"] == "ModifyDate"
        assert params[0]["sortDir"] == "ASC"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_stops_without_saving_state(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"orders": [], "pages": 0})])

        manager = _make_manager()
        rows = _rows(_source("orders", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_pages_field_falls_back_to_short_page_termination(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"orders": [{"orderId": 1}]})])

        manager = _make_manager()
        rows = _rows(_source("orders", manager))

        assert [row["orderId"] for row in rows] == [1]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()


class TestVersionDispatch:
    @pytest.mark.parametrize(
        "dialect, expected_type, header_present",
        [
            (V1_DIALECT, HttpBasicAuth, False),
            (V2_DIALECT, APIKeyAuth, True),
        ],
    )
    def test_build_auth_scheme_per_version(self, dialect, expected_type, header_present):
        auth = _build_auth("key", "secret", dialect)

        assert isinstance(auth, expected_type)
        if header_present:
            # v2 sends the key in an API-Key header; a wrong scheme would 401 every request.
            assert auth.name == "API-Key"
            assert auth.api_key == "key"
        else:
            assert (auth.username, auth.password) == ("key", "secret")

    @pytest.mark.parametrize(
        "api_version, endpoint, body, expected_url, expected_page_size_param",
        [
            (
                SHIPSTATION_V1,
                "orders",
                {"orders": [{"orderId": 1}], "page": 1, "pages": 1},
                "https://ssapi.shipstation.com/orders",
                "pageSize",
            ),
            (
                SHIPSTATION_V2,
                "shipments",
                {"shipments": [{"shipment_id": "se-1"}], "page": 1, "pages": 1},
                "https://api.shipstation.com/v2/shipments",
                "page_size",
            ),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_request_targets_version_host_and_pagination(
        self, MockSession, api_version, endpoint, body, expected_url, expected_page_size_param
    ):
        # The bug this guards: a v2 pin syncing against v1's host/paths/params (every table 404s).
        session = MockSession.return_value
        session.headers = {}
        urls: list[str] = []
        params: list[dict[str, Any]] = []

        def _prepare(request: Any) -> mock.MagicMock:
            urls.append(request.url)
            params.append(dict(request.params or {}))
            # v2 enforces allowed_hosts, which parses prepared.url — give it the real URL string.
            return mock.MagicMock(url=request.url)

        session.prepare_request.side_effect = _prepare
        session.send.side_effect = [_response(body)]

        _rows(_source(endpoint, _make_manager(), api_version=api_version))

        assert urls[0] == expected_url
        assert expected_page_size_param in params[0]


class TestShipStationSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_response_metadata_per_endpoint(self, MockSession, endpoint):
        config = SHIPSTATION_ENDPOINTS[endpoint]
        response = _source(endpoint, _make_manager())

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
