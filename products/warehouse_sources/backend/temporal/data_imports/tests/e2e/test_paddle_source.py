from datetime import datetime

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pyarrow as pa
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.paddle import (
    PaddlePermissionError,
    PaddleResumeConfig,
    _format_paddle_datetime_query_value,
    get_rows,
    paddle_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.source import PaddleSource

# We patch requests.Session.request to ensure NO real HTTP calls are made.
MOCK_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.paddle.paddle.requests.Session.request"


def _get_mock_webhook_manager(enabled: bool = False) -> MagicMock:
    mock_manager = MagicMock()
    # async_to_sync in paddle_source needs an awaitable, not a MagicMock return value.
    mock_manager.webhook_enabled = AsyncMock(return_value=enabled)
    mock_manager.get_items.return_value = iter([])
    return mock_manager


class MockResponse:
    def __init__(self, json_data, status_code=200, headers=None):
        self.json_data = json_data
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self.json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            from requests import Response
            from requests.exceptions import HTTPError

            raise HTTPError(f"HTTP Error {self.status_code}", response=Response())


def _get_mock_resumable_manager() -> ResumableSourceManager[PaddleResumeConfig]:
    mock_manager = MagicMock(spec=ResumableSourceManager)
    mock_manager.can_resume.return_value = False
    mock_manager.load_state.return_value = None
    return mock_manager


@patch(MOCK_PATH)
def test_get_rows_pagination(mock_request):
    page1 = {
        "data": [{"id": "ctm_01h8xq9j5m2k3n4p5q6r7s8t9a"}],
        "meta": {"pagination": {"next": "https://api.paddle.com/customers?per_page=100&after=123"}},
    }
    page2 = {
        "data": [{"id": "ctm_01h8xq9j5m2k3n4p5q6r7s8t9b"}],
        "meta": {"pagination": {"next": None}},
    }

    mock_request.side_effect = [MockResponse(page1), MockResponse(page2)]

    logger = MagicMock()
    mock_manager = _get_mock_resumable_manager()

    items = list(
        get_rows(
            api_key="fake",
            endpoint="customers",
            db_incremental_field_last_value=None,
            logger=logger,
            resumable_source_manager=mock_manager,
            should_use_incremental_field=False,
        )
    )

    assert mock_request.call_count == 2
    assert len(items) == 1
    table: pa.Table = items[0]

    assert table.num_rows == 2
    assert table.column("id").to_pylist() == ["ctm_01h8xq9j5m2k3n4p5q6r7s8t9a", "ctm_01h8xq9j5m2k3n4p5q6r7s8t9b"]


@patch(MOCK_PATH)
def test_get_rows_incremental(mock_request):
    mock_request.return_value = MockResponse(
        {
            "data": [{"id": "txn_01h8xq9j5m2k3n4p5q6r7s8t9d", "billed_at": "2024-06-01T00:00:00Z"}],
            "meta": {"pagination": {"next": None}},
        }
    )

    logger = MagicMock()
    mock_manager = _get_mock_resumable_manager()

    list(
        get_rows(
            api_key="fake",
            endpoint="transactions",
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
            logger=logger,
            resumable_source_manager=mock_manager,
            should_use_incremental_field=True,
        )
    )

    mock_request.assert_called_once()
    actual_params = mock_request.call_args[1]["params"]

    assert actual_params["billed_at[GT]"] == "2024-01-01T00:00:00Z"
    assert actual_params["order_by"] == "billed_at[ASC]"


@patch(MOCK_PATH)
def test_get_rows_drops_null_billed_at_transactions(mock_request):
    # Paddle's billed_at[ASC] listing includes draft transactions (billed_at null), and the first
    # sync sends no billed_at[GT] filter. Drop them so they don't land in the fallback partition and
    # duplicate once billed — matching the incremental cursor and the webhook path.
    mock_request.return_value = MockResponse(
        {
            "data": [
                {"id": "txn_billed", "billed_at": "2024-01-01T00:00:00Z"},
                {"id": "txn_draft_null", "billed_at": None},
                {"id": "txn_draft_missing"},
            ],
            "meta": {"pagination": {"next": None}},
        }
    )
    logger = MagicMock()
    mock_manager = _get_mock_resumable_manager()

    items = list(
        get_rows(
            api_key="fake",
            endpoint="transactions",
            db_incremental_field_last_value=None,
            logger=logger,
            resumable_source_manager=mock_manager,
            should_use_incremental_field=False,
        )
    )

    ids = [row for table in items for row in table.column("id").to_pylist()]
    assert ids == ["txn_billed"]


@parameterized.expand(
    [
        ("utc_string", "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"),
        ("offset_string", "2024-01-01T02:00:00+02:00", "2024-01-01T00:00:00Z"),
        ("naive_datetime", datetime(2024, 1, 1, 0, 0, 0), "2024-01-01T00:00:00Z"),
    ]
)
def test_format_paddle_datetime_query_value(_, value, expected):
    assert _format_paddle_datetime_query_value(value) == expected


@patch(MOCK_PATH)
def test_validate_credentials_success(mock_request):
    mock_request.return_value = MockResponse({"data": []}, status_code=200)
    assert validate_credentials("fake_key") is True
    assert mock_request.call_count == len(ENDPOINTS)


@patch(MOCK_PATH)
def test_validate_credentials_missing_permissions(mock_request):
    mock_request.return_value = MockResponse({"error": "forbidden"}, status_code=403)
    with pytest.raises(PaddlePermissionError):
        validate_credentials("fake_key")


@parameterized.expand(
    [
        # Only the incremental endpoint (transactions/billed_at) is datetime-partitioned; the
        # others carry no partition key and fall back to md5-on-id in the pipeline.
        ("non_incremental", "products", None, None, None),
        ("incremental", "transactions", ["billed_at"], "datetime", "week"),
    ]
)
@patch(MOCK_PATH)
@patch(
    "products.warehouse_sources.backend.temporal.data_imports.sources.paddle.paddle.get_dlt_mapping_for_external_table"
)
def test_paddle_source(_name, endpoint, expected_keys, expected_mode, expected_format, mock_get_mapping, mock_request):
    mock_get_mapping.return_value = {"id": {"data_type": "text"}}
    logger = MagicMock()
    mock_manager = _get_mock_resumable_manager()

    response = paddle_source(
        api_key="fake",
        endpoint=endpoint,
        db_incremental_field_last_value=None,
        should_use_incremental_field=False,
        logger=logger,
        resumable_source_manager=mock_manager,
        webhook_source_manager=_get_mock_webhook_manager(),
    )

    assert response.name == endpoint
    assert response.primary_keys == ["id"]
    assert response.column_hints == {"id": "text"}
    assert response.partition_keys == expected_keys
    assert response.partition_mode == expected_mode
    assert response.partition_format == expected_format
    assert response.sort_mode == "asc"


@patch(MOCK_PATH)
@patch(
    "products.warehouse_sources.backend.temporal.data_imports.sources.paddle.paddle.get_dlt_mapping_for_external_table"
)
def test_paddle_source_reads_webhook_items_when_enabled(mock_get_mapping, mock_request):
    mock_get_mapping.return_value = {"id": {"data_type": "text"}}
    webhook_manager = _get_mock_webhook_manager(enabled=True)

    response = paddle_source(
        api_key="fake",
        endpoint="transactions",
        db_incremental_field_last_value=None,
        should_use_incremental_field=False,
        logger=MagicMock(),
        resumable_source_manager=_get_mock_resumable_manager(),
        webhook_source_manager=webhook_manager,
    )

    items = response.items()

    # No Paddle endpoint is webhook-only — the initial sync must always be able to backfill.
    webhook_manager.webhook_enabled.assert_awaited_once_with(webhook_only=False)
    webhook_manager.get_items.assert_called_once()
    assert items is webhook_manager.get_items.return_value
    # The webhook path must never hit the Paddle API.
    mock_request.assert_not_called()


@patch(MOCK_PATH)
@patch(
    "products.warehouse_sources.backend.temporal.data_imports.sources.paddle.paddle.get_dlt_mapping_for_external_table"
)
def test_paddle_source_pulls_from_api_when_webhook_disabled(mock_get_mapping, mock_request):
    mock_get_mapping.return_value = {"id": {"data_type": "text"}}
    mock_request.return_value = MockResponse(
        {"data": [{"id": "txn_1", "billed_at": "2024-01-01T00:00:00Z"}], "meta": {"pagination": {"next": None}}}
    )
    webhook_manager = _get_mock_webhook_manager(enabled=False)

    response = paddle_source(
        api_key="fake",
        endpoint="transactions",
        db_incremental_field_last_value=None,
        should_use_incremental_field=False,
        logger=MagicMock(),
        resumable_source_manager=_get_mock_resumable_manager(),
        webhook_source_manager=webhook_manager,
    )

    tables = list(response.items())

    webhook_manager.get_items.assert_not_called()
    assert len(tables) == 1
    assert tables[0].column("id").to_pylist() == ["txn_1"]


@patch(MOCK_PATH)
def test_validate_credentials_sandbox_hits_sandbox_host(mock_request):
    mock_request.return_value = MockResponse({"data": []}, status_code=200)

    assert validate_credentials("fake_key", environment="sandbox") is True

    for call in mock_request.call_args_list:
        # A sandbox key sent to the live API always 401s — the environment must reach
        # the URL builder.
        assert call[0][1].startswith("https://sandbox-api.paddle.com/")


@patch(MOCK_PATH)
def test_get_rows_resume(mock_request):
    mock_request.return_value = MockResponse(
        {"data": [{"id": "ctm_01h8xq9j5m2k3n4p5q6r7s8t9c"}], "meta": {"pagination": {"next": None}}}
    )

    logger = MagicMock()
    mock_manager = MagicMock(spec=ResumableSourceManager)
    mock_manager.can_resume.return_value = True
    mock_manager.load_state.return_value = PaddleResumeConfig(next_url="https://api.paddle.com/customers?after=2")

    items = list(
        get_rows(
            api_key="fake",
            endpoint="customers",
            db_incremental_field_last_value=None,
            logger=logger,
            resumable_source_manager=mock_manager,
            should_use_incremental_field=False,
        )
    )

    assert mock_request.call_count == 1
    assert mock_request.call_args[0][1] == "https://api.paddle.com/customers?after=2"
    assert len(items) == 1
    assert items[0].column("id").to_pylist() == ["ctm_01h8xq9j5m2k3n4p5q6r7s8t9c"]


@patch(MOCK_PATH)
def test_paddle_request_fails_fast(mock_request):
    mock_request.return_value = MockResponse({"error": "rate_limited"}, status_code=429)

    from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.paddle import (
        _get_paddle_session,
        paddle_request,
    )

    session = _get_paddle_session("fake")

    response = paddle_request(
        session,
        "GET",
        "https://api.paddle.com/test",
        params={"per_page": 200},
    )

    assert mock_request.call_count == 1
    assert response.status_code == 429


@patch(MOCK_PATH)
def test_get_rows_stops_on_repeated_cursor(mock_request):
    repeated_url = "https://api.paddle.com/products?after=pro_1&order_by=id%5BASC%5D&per_page=200"
    mock_request.side_effect = [
        MockResponse(
            {
                "data": [{"id": "pro_1"}],
                "meta": {"pagination": {"next": repeated_url}},
            }
        ),
        MockResponse(
            {
                "data": [{"id": "pro_2"}],
                "meta": {"pagination": {"next": repeated_url}},
            }
        ),
    ]

    items = list(
        get_rows(
            api_key="fake",
            endpoint="products",
            db_incremental_field_last_value=None,
            logger=MagicMock(),
            resumable_source_manager=_get_mock_resumable_manager(),
            should_use_incremental_field=False,
        )
    )

    assert mock_request.call_count == 2
    assert len(items) == 1
    assert items[0].column("id").to_pylist() == ["pro_1", "pro_2"]


@parameterized.expand(
    [
        ("transactions", True),
        ("customers", False),
        ("discounts", False),
        ("prices", False),
        ("products", False),
        ("subscriptions", False),
        ("adjustments", False),
    ]
)
def test_get_schemas_incremental_flag(endpoint, expected_incremental):
    source = PaddleSource()
    schemas = {schema.name: schema for schema in source.get_schemas(config=MagicMock(), team_id=1)}
    assert schemas[endpoint].supports_incremental is expected_incremental
    assert schemas[endpoint].supports_append is expected_incremental
