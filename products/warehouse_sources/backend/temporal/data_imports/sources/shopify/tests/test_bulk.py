import re
import json
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import graphql
from requests.exceptions import ChunkedEncodingError

from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.bulk import (
    ShopifyBulkOperationError,
    iter_bulk_batches,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.constants import (
    ORDERS,
    SHOPIFY_API_VERSION_2025_10,
    SHOPIFY_API_VERSION_2026_07,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.queries.orders import (
    ORDERS_BULK_CONNECTIONS,
    build_orders_bulk_query,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify import (
    PHASE_ALL,
    PHASE_BULK,
    ShopifyResumeConfig,
    shopify_source,
)

_SHOPIFY = "products.warehouse_sources.backend.temporal.data_imports.sources.shopify"
_FILE_URL = "https://storage.example.com/bulk/result.jsonl"
_OPERATION_ID = "gid://shopify/BulkOperation/1"

_LINES: list[dict[str, Any]] = [
    {"id": "order-1", "name": "#1"},
    {"id": "line-1", "__typename": "LineItem", "__parentId": "order-1", "quantity": 2},
    {"id": "meta-1", "__typename": "Metafield", "__parentId": "order-1", "key": "gift"},
    {"id": "order-2", "name": "#2"},
    {"id": "order-3", "name": "#3"},
    {"id": "line-3", "__typename": "LineItem", "__parentId": "order-3", "quantity": 1},
]
_ORDERS = [
    {
        "id": "order-1",
        "name": "#1",
        "lineItems": {"nodes": [{"id": "line-1", "quantity": 2}]},
        "metafields": {"nodes": [{"id": "meta-1", "key": "gift"}]},
    },
    {"id": "order-2", "name": "#2", "lineItems": {"nodes": []}, "metafields": {"nodes": []}},
    {
        "id": "order-3",
        "name": "#3",
        "lineItems": {"nodes": [{"id": "line-3", "quantity": 1}]},
        "metafields": {"nodes": []},
    },
]


def _jsonl(lines: list[dict[str, Any]]) -> bytes:
    return "".join(json.dumps(line) + "\n" for line in lines).encode()


class _FileServer:
    def __init__(self, content: bytes, honors_range: bool = True, fail_first_request_after: int | None = None):
        self.content = content
        self.honors_range = honors_range
        self.fail_first_request_after = fail_first_request_after
        self.requested_offsets: list[int] = []

    def session(self, **kwargs: Any) -> MagicMock:
        session = MagicMock()
        session.get.side_effect = self._get
        return session

    def _get(self, url: str, stream: bool = False, headers: dict[str, str] | None = None) -> MagicMock:
        range_header = (headers or {}).get("Range")
        offset = int(range_header.removeprefix("bytes=").removesuffix("-")) if range_header else 0
        fails_after = self.fail_first_request_after if not self.requested_offsets else None
        self.requested_offsets.append(offset)

        response = MagicMock()
        response.__enter__.return_value = response
        if self.honors_range and offset >= len(self.content) and offset > 0:
            response.status_code = 416
            return response
        ranged = self.honors_range and offset > 0
        response.status_code = 206 if ranged else 200
        body = self.content[offset:] if ranged else self.content

        def iter_content(chunk_size: int) -> Any:
            # Small chunks, so that lines and rows cross chunk borders.
            for start in range(0, len(body), 7):
                if fails_after is not None and start >= fails_after:
                    raise ChunkedEncodingError("Connection broken")
                yield body[start : start + 7]

        response.iter_content.side_effect = iter_content
        return response


def _read(server: _FileServer, offset: int = 0, batch_size: int = 1) -> list[Any]:
    with patch(f"{_SHOPIFY}.bulk.make_tracked_session", side_effect=server.session):
        return list(iter_bulk_batches(_FILE_URL, offset, ORDERS_BULK_CONNECTIONS, batch_size=batch_size))


@pytest.mark.parametrize("honors_range", [True, False])
def test_bulk_file_rows_match_the_paged_shape_and_each_offset_resumes_after_its_batch(honors_range: bool) -> None:
    content = _jsonl(_LINES)

    batches = _read(_FileServer(content, honors_range))

    assert [batch.rows for batch in batches] == [[order] for order in _ORDERS]
    for index, batch in enumerate(batches):
        resumed = _read(_FileServer(content, honors_range), offset=batch.next_offset)
        assert [row for resumed_batch in resumed for row in resumed_batch.rows] == _ORDERS[index + 1 :]


def test_dropped_download_continues_from_the_last_batch_without_repeating_rows() -> None:
    content = _jsonl(_LINES)
    second_order_start = content.index(b'{"id": "order-2"')
    # The drop is inside the third order, so only the first order is handed on before it.
    server = _FileServer(content, fail_first_request_after=content.index(b'{"id": "order-3"') + 14)

    batches = _read(server)

    assert [row for batch in batches for row in batch.rows] == _ORDERS
    assert server.requested_offsets == [0, second_order_start]


@pytest.mark.parametrize(
    "nested_row",
    [
        {"id": "line-9", "__typename": "LineItem", "__parentId": "order-other"},
        {"id": "line-9", "__typename": "ShippingLine", "__parentId": "order-1"},
    ],
)
def test_nested_row_that_cannot_be_placed_stops_the_read(nested_row: dict[str, Any]) -> None:
    with pytest.raises(ShopifyBulkOperationError):
        _read(_FileServer(_jsonl([{"id": "order-1"}, nested_row])))


def test_orders_bulk_query_stays_inside_the_bulk_operation_limits() -> None:
    query = build_orders_bulk_query({"read_payment_terms"}, "created_at:>='2025-01-01T00:00:00+00:00'")

    connections: list[graphql.FieldNode] = []

    class _FindConnections(graphql.Visitor):
        def enter_field(self, node: graphql.FieldNode, *_: Any) -> None:
            selections = node.selection_set.selections if node.selection_set else ()
            if any(isinstance(field, graphql.FieldNode) and field.name.value == "edges" for field in selections):
                connections.append(node)

    graphql.visit(graphql.parse(query), _FindConnections())

    assert sorted(node.name.value for node in connections) == ["lineItems", "metafields", "orders"]
    orders = next(node for node in connections if node.name.value == "orders")
    assert {argument.name.value for argument in orders.arguments} == {"sortKey", "query"}


@pytest.fixture
def _no_waiting():
    with (
        patch(f"{_SHOPIFY}.shopify._get_shopify_access_token", return_value="test-token"),
        patch(f"{_SHOPIFY}.shopify.interruptible_wait"),
    ):
        yield


def _graphql_response(data: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"data": data}
    return response


def _operation(status: str, url: str | None = None, error_code: str | None = None) -> MagicMock:
    return _graphql_response(
        {
            "bulkOperation": {
                "id": _OPERATION_ID,
                "status": status,
                "errorCode": error_code,
                "objectCount": "6",
                "url": url,
            }
        }
    )


_STARTED = _graphql_response(
    {"bulkOperationRunQuery": {"bulkOperation": {"id": _OPERATION_ID, "status": "CREATED"}, "userErrors": []}}
)
_REJECTED = _graphql_response(
    {"bulkOperationRunQuery": {"bulkOperation": None, "userErrors": [{"field": ["query"], "message": "Invalid"}]}}
)
_PAGE = _graphql_response({ORDERS: {"nodes": [{"id": "paged-1"}], "pageInfo": {"hasNextPage": False}}})


def _run_orders(
    responses: list[MagicMock],
    manager: MagicMock,
    server: _FileServer | None = None,
    api_version: str = SHOPIFY_API_VERSION_2026_07,
    flag_enabled: bool = True,
) -> tuple[list[Any], list[str]]:
    server = server or _FileServer(_jsonl(_LINES))
    with (
        patch(f"{_SHOPIFY}.shopify.requests.Session") as session_cls,
        patch(f"{_SHOPIFY}.bulk.make_tracked_session", side_effect=server.session),
    ):
        session_cls.return_value.post.side_effect = responses
        source = shopify_source(
            shopify_store_id="store",
            shopify_client_id="id",
            shopify_client_secret="secret",
            graphql_object_name=ORDERS,
            db_incremental_field_last_value=None,
            db_incremental_field_earliest_value=None,
            logger=MagicMock(),
            resumable_source_manager=manager,
            api_version=api_version,
            use_bulk_export=lambda: flag_enabled,
        )
        batches = list(source.items())
        sent = [call.kwargs["json"]["query"] for call in session_cls.return_value.post.call_args_list]
    return batches, [re.findall(r"(?:query|mutation) (\w+)", query)[0] for query in sent]


def _manager(resume_state: ShopifyResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


@pytest.mark.usefixtures("_no_waiting")
class TestShopifyBulkExport:
    def test_first_read_runs_one_bulk_operation_and_stores_its_id_before_the_wait(self) -> None:
        manager = _manager()

        batches, operations = _run_orders(
            [_STARTED, _operation("RUNNING"), _operation("COMPLETED", _FILE_URL)], manager
        )

        assert batches == [_ORDERS]
        assert operations == ["StartBulkQuery", "BulkOperation", "BulkOperation"]
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved[0] == ShopifyResumeConfig(phase=PHASE_BULK, cursor="", bulk_operation_id=_OPERATION_ID)
        assert saved[-1] == ShopifyResumeConfig(
            phase=PHASE_BULK, cursor="", bulk_operation_id=_OPERATION_ID, bulk_offset=len(_jsonl(_LINES))
        )

    def test_resume_polls_the_stored_operation_and_reads_from_the_stored_offset(self) -> None:
        content = _jsonl(_LINES)
        offset = content.index(b'{"id": "order-3"')
        server = _FileServer(content)
        resume_state = ShopifyResumeConfig(
            phase=PHASE_BULK, cursor="", bulk_operation_id=_OPERATION_ID, bulk_offset=offset
        )

        batches, operations = _run_orders([_operation("COMPLETED", _FILE_URL)], _manager(resume_state), server)

        assert batches == [_ORDERS[2:]]
        assert operations == ["BulkOperation"]
        assert server.requested_offsets == [offset]

    def test_bulk_read_in_progress_continues_after_the_flag_turns_off(self) -> None:
        resume_state = ShopifyResumeConfig(phase=PHASE_BULK, cursor="", bulk_operation_id=_OPERATION_ID)

        batches, operations = _run_orders(
            [_operation("COMPLETED", _FILE_URL)], _manager(resume_state), flag_enabled=False
        )

        assert batches == [_ORDERS]
        assert operations == ["BulkOperation"]

    @pytest.mark.parametrize(
        "responses, manager, api_version, flag_enabled",
        [
            ([_REJECTED, _PAGE], _manager(), SHOPIFY_API_VERSION_2026_07, True),
            ([_PAGE], _manager(ShopifyResumeConfig(phase=PHASE_ALL, cursor="c")), SHOPIFY_API_VERSION_2026_07, True),
            ([_PAGE], _manager(), SHOPIFY_API_VERSION_2025_10, True),
            ([_PAGE], _manager(), SHOPIFY_API_VERSION_2026_07, False),
        ],
        ids=["start_rejected", "paged_read_in_progress", "version_without_bulk_polling", "flag_off"],
    )
    def test_reads_pages_when_the_bulk_export_cannot_be_used(
        self, responses: list[MagicMock], manager: MagicMock, api_version: str, flag_enabled: bool
    ) -> None:
        batches, operations = _run_orders(responses, manager, api_version=api_version, flag_enabled=flag_enabled)

        assert batches == [[{"id": "paged-1"}]]
        assert operations[-1] == "PaginatedOrders"

    def test_failed_operation_clears_the_stored_id_so_a_retry_starts_a_new_one(self) -> None:
        manager = _manager()

        with pytest.raises(ShopifyBulkOperationError):
            _run_orders([_STARTED, _operation("FAILED", error_code="TIMEOUT")], manager)

        manager.clear_state.assert_called_once()
