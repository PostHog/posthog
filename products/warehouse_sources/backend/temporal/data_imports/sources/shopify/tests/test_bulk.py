import re
import json
from typing import Any

import pytest
import time_machine
from unittest.mock import MagicMock, patch

import graphql
from requests.exceptions import ChunkedEncodingError

from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.bulk import (
    SHOPIFY_BULK_FILE_SHAPE_ERROR,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.source import (
    WAREHOUSE_SHOPIFY_BULK_EXPORT_FLAG,
    ShopifySource,
    _is_bulk_export_enabled,
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


_FILE = _jsonl(_LINES)
_SECOND_ORDER_START = _FILE.index(b'{"id": "order-2"')
_THIRD_ORDER_START = _FILE.index(b'{"id": "order-3"')


class _FileServer:
    def __init__(
        self,
        content: bytes = _FILE,
        honors_range: bool = True,
        first_request_raises_after: int | None = None,
        first_request_ends_after: int | None = None,
        status_code: int | None = None,
    ):
        self.content = content
        self.honors_range = honors_range
        self.first_request_raises_after = first_request_raises_after
        self.first_request_ends_after = first_request_ends_after
        self.status_code = status_code
        self.requested_offsets: list[int] = []

    def session(self, **kwargs: Any) -> MagicMock:
        session = MagicMock()
        session.get.side_effect = self._get
        return session

    def _get(self, url: str, stream: bool = False, headers: dict[str, str] | None = None) -> MagicMock:
        range_header = (headers or {}).get("Range")
        offset = int(range_header.removeprefix("bytes=").removesuffix("-")) if range_header else 0
        is_first_request = not self.requested_offsets
        self.requested_offsets.append(offset)

        response = MagicMock()
        response.__enter__.return_value = response
        if self.status_code is not None:
            response.status_code = self.status_code
            response.ok = False
            return response
        if self.honors_range and offset >= len(self.content) and offset > 0:
            response.status_code = 416
            response.ok = False
            return response
        ranged = self.honors_range and offset > 0
        response.status_code = 206 if ranged else 200
        response.ok = True
        response.headers = {"Content-Range": f"bytes {offset}-{len(self.content) - 1}/{len(self.content)}"}
        body = self.content[offset:] if ranged else self.content
        if is_first_request and self.first_request_ends_after is not None:
            body = body[: self.first_request_ends_after]
        raises_after = self.first_request_raises_after if is_first_request else None

        def iter_content(chunk_size: int) -> Any:
            # Small chunks, so that lines and rows cross chunk borders.
            for start in range(0, len(body), 7):
                if raises_after is not None and start >= raises_after:
                    raise ChunkedEncodingError("Connection broken")
                yield body[start : start + 7]

        response.iter_content.side_effect = iter_content
        return response


def _read(server: _FileServer, offset: int = 0, file_size: int | None = None) -> list[Any]:
    with (
        patch(f"{_SHOPIFY}.bulk.make_tracked_session", side_effect=server.session),
        patch(f"{_SHOPIFY}.bulk.interruptible_wait"),
    ):
        return list(iter_bulk_batches(_FILE_URL, offset, ORDERS_BULK_CONNECTIONS, file_size, batch_size=1))


def _rows(batches: list[Any]) -> list[Any]:
    return [row for batch in batches for row in batch.rows]


@pytest.mark.parametrize("honors_range", [True, False])
def test_bulk_file_rows_match_the_paged_shape_and_each_offset_resumes_after_its_batch(honors_range: bool) -> None:
    batches = _read(_FileServer(honors_range=honors_range), file_size=len(_FILE))

    assert [batch.rows for batch in batches] == [[order] for order in _ORDERS]
    for index, batch in enumerate(batches):
        resumed = _read(_FileServer(honors_range=honors_range), offset=batch.next_offset, file_size=len(_FILE))
        assert _rows(resumed) == _ORDERS[index + 1 :]


@pytest.mark.parametrize(
    "server",
    [
        # Both drops are inside the third order, so only the first order is handed on before them.
        _FileServer(first_request_raises_after=_THIRD_ORDER_START + 14),
        # The connection closes with no error exactly between two orders.
        _FileServer(first_request_ends_after=_THIRD_ORDER_START),
    ],
    ids=["connection_error", "silent_end_on_a_line_boundary"],
)
def test_interrupted_download_continues_from_the_last_batch_without_losing_or_repeating_rows(
    server: _FileServer,
) -> None:
    batches = _read(server, file_size=len(_FILE))

    assert _rows(batches) == _ORDERS
    assert server.requested_offsets == [0, _SECOND_ORDER_START]


@pytest.mark.parametrize(
    "nested_row",
    [
        {"id": "line-9", "__typename": "LineItem", "__parentId": "order-other"},
        {"id": "line-9", "__typename": "ShippingLine", "__parentId": "order-1"},
    ],
)
def test_nested_row_that_cannot_be_placed_stops_the_sync_without_retries(nested_row: dict[str, Any]) -> None:
    with pytest.raises(ShopifyBulkOperationError) as error:
        _read(_FileServer(_jsonl([{"id": "order-1"}, nested_row])))

    assert SHOPIFY_BULK_FILE_SHAPE_ERROR in ShopifySource().get_non_retryable_errors()
    assert SHOPIFY_BULK_FILE_SHAPE_ERROR in str(error.value)


def test_file_host_error_is_not_reported_as_a_store_error() -> None:
    with pytest.raises(ShopifyBulkOperationError) as error:
        _read(_FileServer(status_code=404))

    non_retryable = [pattern.lower() for pattern in ShopifySource().get_non_retryable_errors()]
    assert not [pattern for pattern in non_retryable if pattern in str(error.value).lower()]


def test_orders_bulk_query_stays_inside_the_bulk_operation_limits() -> None:
    query = build_orders_bulk_query({"read_payment_terms"}, "created_at:>='2025-01-01T00:00:00+00:00'")

    connections: list[graphql.FieldNode] = []

    class _FindConnections(graphql.Visitor):
        def enter_field(self, node: graphql.FieldNode, *_: Any) -> None:
            selections = node.selection_set.selections if node.selection_set else ()
            names = {field.name.value for field in selections if isinstance(field, graphql.FieldNode)}
            if names & {"edges", "nodes"}:
                connections.append(node)

    graphql.visit(graphql.parse(query), _FindConnections())

    assert sorted(node.name.value for node in connections) == ["lineItems", "metafields", "orders"]
    arguments = {node.name.value: {argument.name.value for argument in node.arguments} for node in connections}
    assert arguments == {"orders": {"sortKey", "query"}, "lineItems": set(), "metafields": set()}
    assert query.count("__typename") == len(ORDERS_BULK_CONNECTIONS)


@pytest.mark.parametrize("schema_exists, flag_value, expected", [(False, True, False), (True, True, True)])
def test_bulk_export_flag_is_asked_for_the_schema_of_the_run(
    schema_exists: bool, flag_value: bool, expected: bool
) -> None:
    schema = MagicMock() if schema_exists else None
    with (
        patch(f"{_SHOPIFY}.source.ExternalDataSchema.objects") as objects,
        patch(f"{_SHOPIFY}.source.is_schema_flag_enabled", return_value=flag_value) as is_enabled,
    ):
        objects.filter.return_value.select_related.return_value.first.return_value = schema

        assert _is_bulk_export_enabled(7, "schema-id") is expected

    objects.filter.assert_called_once_with(team_id=7, id="schema-id")
    if schema_exists:
        is_enabled.assert_called_once_with(schema, WAREHOUSE_SHOPIFY_BULK_EXPORT_FLAG)


@pytest.fixture
def _no_waiting():
    with (
        patch(f"{_SHOPIFY}.shopify._get_shopify_access_token", return_value="test-token"),
        patch(f"{_SHOPIFY}.shopify.interruptible_wait") as wait,
    ):
        yield wait


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
                "fileSize": None if url is None else str(len(_FILE)),
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
_GONE = _graphql_response({"bulkOperation": None})
_PAGE = _graphql_response({ORDERS: {"nodes": [{"id": "paged-1"}], "pageInfo": {"hasNextPage": False}}})
_COMPLETED = _operation("COMPLETED", _FILE_URL)
_IN_PROGRESS = ShopifyResumeConfig(phase=PHASE_BULK, cursor="", bulk_operation_id=_OPERATION_ID)


class _Run:
    def __init__(self, batches: list[Any], requests: list[dict[str, Any]]):
        self.batches = batches
        self.requests = requests
        self.operations = [re.findall(r"(?:query|mutation) (\w+)", request["query"])[0] for request in requests]


def _run_orders(
    responses: list[MagicMock],
    manager: MagicMock,
    server: _FileServer | None = None,
    api_version: str = SHOPIFY_API_VERSION_2026_07,
    flag_enabled: bool = True,
    incremental: bool = True,
) -> _Run:
    server = server or _FileServer()
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
            should_use_incremental_field=incremental,
            use_bulk_export=lambda: flag_enabled,
        )
        try:
            batches = list(source.items())
        finally:
            sent = [call.kwargs["json"] for call in session_cls.return_value.post.call_args_list]
    return _Run(batches, sent)


def _manager(resume_state: ShopifyResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


@pytest.mark.usefixtures("_no_waiting")
class TestShopifyBulkExport:
    @time_machine.travel("2026-03-01T12:00:00+00:00", tick=False)
    def test_first_read_runs_one_grouped_bulk_operation_bounded_by_its_start_time(self) -> None:
        manager = _manager()

        run = _run_orders([_STARTED, _operation("RUNNING"), _COMPLETED], manager)

        assert run.batches == [_ORDERS]
        assert run.operations == ["StartBulkQuery", "BulkOperation", "BulkOperation"]
        assert "groupObjects: true" in run.requests[0]["query"]
        assert "updated_at:<='2026-03-01T12:00:00+00:00'" in run.requests[0]["variables"]["query"]
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved[0] == _IN_PROGRESS
        assert saved[-1] == ShopifyResumeConfig(
            phase=PHASE_BULK, cursor="", bulk_operation_id=_OPERATION_ID, bulk_offset=len(_FILE)
        )

    def test_shutdown_during_the_wait_stops_at_a_safe_point_with_the_operation_id_stored(
        self, _no_waiting: MagicMock
    ) -> None:
        manager = _manager()
        manager.safe_point.side_effect = RuntimeError("worker is shutting down")
        _no_waiting.side_effect = lambda seconds, safe_point: safe_point()

        with pytest.raises(RuntimeError, match="worker is shutting down"):
            _run_orders([_STARTED, _operation("RUNNING")], manager)

        assert [call.args[0] for call in manager.save_state.call_args_list] == [_IN_PROGRESS]

    def test_resume_polls_the_stored_operation_and_reads_from_the_stored_offset(self) -> None:
        server = _FileServer()
        resume_state = ShopifyResumeConfig(
            phase=PHASE_BULK, cursor="", bulk_operation_id=_OPERATION_ID, bulk_offset=_THIRD_ORDER_START
        )

        run = _run_orders([_COMPLETED], _manager(resume_state), server)

        assert run.batches == [_ORDERS[2:]]
        assert run.operations == ["BulkOperation"]
        assert server.requested_offsets == [_THIRD_ORDER_START]

    def test_bulk_read_in_progress_continues_after_the_flag_turns_off(self) -> None:
        run = _run_orders([_COMPLETED], _manager(_IN_PROGRESS), flag_enabled=False)

        assert run.batches == [_ORDERS]
        assert run.operations == ["BulkOperation"]

    @pytest.mark.parametrize(
        "responses, manager, kwargs",
        [
            ([_REJECTED, _PAGE], _manager(), {}),
            ([_STARTED, _operation("FAILED", error_code="TIMEOUT"), _PAGE], _manager(), {}),
            ([_GONE, _PAGE], _manager(_IN_PROGRESS), {}),
            ([_PAGE], _manager(ShopifyResumeConfig(phase=PHASE_ALL, cursor="c")), {}),
            ([_PAGE], _manager(), {"api_version": SHOPIFY_API_VERSION_2025_10}),
            ([_PAGE], _manager(), {"flag_enabled": False}),
            ([_PAGE], _manager(), {"incremental": False}),
        ],
        ids=[
            "start_rejected",
            "operation_failed_before_any_row",
            "operation_gone_before_any_row",
            "paged_read_in_progress",
            "version_without_bulk_polling",
            "flag_off",
            "full_refresh",
        ],
    )
    def test_reads_pages_when_the_bulk_export_cannot_be_used(
        self, responses: list[MagicMock], manager: MagicMock, kwargs: dict[str, Any]
    ) -> None:
        run = _run_orders(responses, manager, **kwargs)

        assert run.batches == [[{"id": "paged-1"}]]
        assert run.operations[-1] == "PaginatedOrders"
        assert "cursor" not in run.requests[-1]["variables"] or run.requests[-1]["variables"]["cursor"] == "c"

    def test_operation_that_ends_after_rows_were_written_clears_its_state_and_fails(self) -> None:
        resume_state = ShopifyResumeConfig(
            phase=PHASE_BULK, cursor="", bulk_operation_id=_OPERATION_ID, bulk_offset=_THIRD_ORDER_START
        )
        manager = _manager(resume_state)

        with pytest.raises(ShopifyBulkOperationError):
            _run_orders([_operation("EXPIRED")], manager)

        manager.clear_state.assert_called_once()
