import re
import json
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import graphql

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.shopify import (
    ShopifyAuthMethodConfig,
    ShopifySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.bulk import (
    SHOPIFY_BULK_FILE_SHAPE_ERROR,
    ShopifyBulkOperationError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.constants import (
    SHOPIFY_API_VERSION_2025_10,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.queries.orders import (
    ORDERS_BULK_CONNECTIONS,
    build_orders_bulk_query,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify import (
    PHASE_ALL,
    PHASE_BULK,
    ShopifyResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.source import (
    WAREHOUSE_SHOPIFY_BULK_EXPORT_FLAG,
    ShopifySource,
    _is_bulk_export_enabled,
)

_SHOPIFY = "products.warehouse_sources.backend.temporal.data_imports.sources.shopify"
_FILE_ORIGIN = "https://storage.example.com"
_FILE_URL = f"{_FILE_ORIGIN}/bulk/result.jsonl?signature=secret-signature"
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
_PAGED_ORDER = {"id": "paged-1"}


def _jsonl(lines: list[dict[str, Any]]) -> bytes:
    return "".join(json.dumps(line) + "\n" for line in lines).encode()


_FILE = _jsonl(_LINES)
_SECOND_ORDER_START = _FILE.index(b'{"id": "order-2"')
_THIRD_ORDER_START = _FILE.index(b'{"id": "order-3"')
_IN_PROGRESS = ShopifyResumeConfig(phase=PHASE_BULK, cursor="", bulk_operation_id=_OPERATION_ID)


def _operation(status: str, error_code: str | None = None) -> dict[str, Any] | None:
    completed = status == "COMPLETED"
    return {
        "id": _OPERATION_ID,
        "status": status,
        "errorCode": error_code,
        "objectCount": "6",
        "fileSize": str(len(_FILE)) if completed else None,
        "url": _FILE_URL if completed else None,
    }


class _Shopify:
    def __init__(
        self,
        operation_states: list[dict[str, Any] | None] | None = None,
        start_errors: list[dict[str, Any]] | None = None,
        file: bytes = _FILE,
        honors_range: bool = True,
        file_failures: list[ScriptedResponse | BaseException] | None = None,
    ):
        self.operation_states = (
            [_operation("RUNNING"), _operation("COMPLETED")] if operation_states is None else operation_states
        )
        self.start_errors = start_errors or []
        self.file = file
        self.honors_range = honors_range
        self.file_failures = list(file_failures or [])
        self.operations: list[str] = []
        self.started_with: dict[str, Any] = {}
        self.file_offsets: list[int] = []

    def __call__(self, request: RecordedRequest) -> ScriptedResponse:
        if request.origin == _FILE_ORIGIN:
            return self._file(request)
        if request.path == "/admin/oauth/access_token":
            return ScriptedResponse(json={"access_token": "tok"})
        if request.method == "GET":
            return ScriptedResponse(json={"access_scopes": []})
        body = request.json()
        operation = re.findall(r"(?:query|mutation) (\w+)", body["query"])[0]
        self.operations.append(operation)
        if operation == "StartBulkQuery":
            self.started_with = body
            started = None if self.start_errors else {"id": _OPERATION_ID, "status": "CREATED"}
            return ScriptedResponse(
                json={"data": {"bulkOperationRunQuery": {"bulkOperation": started, "userErrors": self.start_errors}}}
            )
        if operation == "BulkOperation":
            state = self.operation_states.pop(0) if len(self.operation_states) > 1 else self.operation_states[0]
            return ScriptedResponse(json={"data": {"bulkOperation": state}})
        return ScriptedResponse(
            json={"data": {"orders": {"nodes": [_PAGED_ORDER], "pageInfo": {"hasNextPage": False}}}}
        )

    def _file(self, request: RecordedRequest) -> ScriptedResponse:
        range_header = request.headers.get("range")
        offset = int(range_header.removeprefix("bytes=").removesuffix("-")) if range_header else 0
        self.file_offsets.append(offset)
        if self.file_failures:
            failure = self.file_failures.pop(0)
            if isinstance(failure, BaseException):
                raise failure
            return failure
        if not self.honors_range or offset == 0:
            return ScriptedResponse(body=self.file)
        if offset >= len(self.file):
            return ScriptedResponse(status=416)
        return ScriptedResponse(
            status=206,
            body=self.file[offset:],
            headers={"Content-Range": f"bytes {offset}-{len(self.file) - 1}/{len(self.file)}"},
        )


def _run(shopify: _Shopify, *, flag_enabled: bool = True, incremental: bool = True, **inputs: Any) -> DriveResult:
    config = ShopifySourceConfig(
        shopify_store_id="my-store",
        auth_method=ShopifyAuthMethodConfig(
            selection="client_credentials", shopify_client_id="cid", shopify_client_secret="secret"
        ),
    )
    with patch(f"{_SHOPIFY}.source._is_bulk_export_enabled", return_value=flag_enabled):
        return SourceDriver(ShopifySource(), config).run(
            "orders", shopify, should_use_incremental_field=incremental, **inputs
        )


def test_first_read_runs_one_grouped_bulk_operation_bounded_by_its_start_time() -> None:
    shopify = _Shopify()

    result = _run(shopify)

    assert result.raised is None
    assert result.rows == _ORDERS
    assert shopify.operations == ["StartBulkQuery", "BulkOperation", "BulkOperation"]
    assert "groupObjects: true" in shopify.started_with["query"]
    assert re.search(r"updated_at:<='20\d\d-", shopify.started_with["variables"]["query"])
    # The id is stored before any row exists, so a retry polls this operation.
    assert result.committed_states[0] == _IN_PROGRESS
    assert result.final_state == ShopifyResumeConfig(
        phase=PHASE_BULK, cursor="", bulk_operation_id=_OPERATION_ID, bulk_offset=len(_FILE)
    )


@pytest.mark.parametrize("honors_range", [True, False])
def test_each_stored_offset_resumes_with_the_rows_after_its_batch(honors_range: bool) -> None:
    with patch(f"{_SHOPIFY}.bulk.BULK_BATCH_SIZE", 1):
        first = _run(_Shopify(honors_range=honors_range))
        offsets = [state.bulk_offset for state in first.committed_states if state.bulk_offset]

        assert first.items == [[order] for order in _ORDERS]
        assert offsets == [_SECOND_ORDER_START, _THIRD_ORDER_START, len(_FILE)]
        for index, offset in enumerate(offsets):
            shopify = _Shopify([_operation("COMPLETED")], honors_range=honors_range)
            resumed = _run(shopify, resume_state=ShopifyResumeConfig(PHASE_BULK, "", _OPERATION_ID, offset))

            assert resumed.rows == _ORDERS[index + 1 :]
            assert shopify.operations == ["BulkOperation"]
            assert shopify.file_offsets == [offset]


@pytest.mark.parametrize(
    "file_failure",
    [
        ConnectionResetError("connection reset"),
        # The host closes the connection with no error, first between two orders and then inside a line.
        ScriptedResponse(body=_FILE[:_THIRD_ORDER_START]),
        ScriptedResponse(body=_FILE[: _THIRD_ORDER_START + 9]),
    ],
    ids=["connection_error", "silent_end_between_rows", "silent_end_inside_a_row"],
)
def test_interrupted_download_continues_from_the_last_batch_without_losing_or_repeating_rows(
    file_failure: ScriptedResponse | BaseException,
) -> None:
    shopify = _Shopify(file_failures=[file_failure])

    with patch(f"{_SHOPIFY}.bulk.BULK_BATCH_SIZE", 1):
        result = _run(shopify)

    assert result.raised is None
    assert result.rows == _ORDERS
    assert shopify.file_offsets[0] == 0
    assert shopify.file_offsets[-1] in (0, _SECOND_ORDER_START)


@pytest.mark.parametrize(
    "nested_row",
    [
        {"id": "line-9", "__typename": "LineItem", "__parentId": "order-other"},
        {"id": "line-9", "__typename": "ShippingLine", "__parentId": "order-1"},
    ],
)
def test_nested_row_that_cannot_be_placed_stops_the_read(nested_row: dict[str, Any]) -> None:
    file = _jsonl([{"id": "order-1"}, nested_row])
    completed = {**(_operation("COMPLETED") or {}), "fileSize": str(len(file))}

    result = _run(_Shopify([completed], file=file))

    assert isinstance(result.raised, ShopifyBulkOperationError)
    assert SHOPIFY_BULK_FILE_SHAPE_ERROR in str(result.raised)
    assert result.rows == []


@pytest.mark.parametrize(
    "file_failures",
    # The transport retries a dropped connection on its own, so the list is long enough to outlast both.
    [[ScriptedResponse(status=404)], [ConnectionResetError("connection reset")] * 200],
    ids=["http_error", "reconnects_run_out"],
)
def test_file_download_failure_names_neither_the_signed_url_nor_a_store_error(
    file_failures: list[ScriptedResponse | BaseException],
) -> None:
    result = _run(_Shopify(file_failures=file_failures))

    assert isinstance(result.raised, ShopifyBulkOperationError)
    assert "secret-signature" not in str(result.raised)
    assert "Client Error" not in str(result.raised)


def test_bulk_requests_stay_out_of_http_sample_capture() -> None:
    result = _run(_Shopify())

    # The status of a finished operation and the file request both carry the signed URL.
    captured = [
        (bool("X-Shopify-Access-Token" in options.get("headers", {})), options.get("capture", True))
        for options in result.session_options
        if "X-Shopify-Access-Token" in options.get("headers", {}) or _FILE_URL in options.get("redact_values", ())
    ]
    assert captured == [(True, True), (True, False), (True, False), (False, False)]


def test_bulk_read_in_progress_continues_after_the_flag_turns_off() -> None:
    shopify = _Shopify([_operation("COMPLETED")])

    result = _run(shopify, flag_enabled=False, resume_state=_IN_PROGRESS)

    assert result.rows == _ORDERS
    assert shopify.operations == ["BulkOperation"]


@pytest.mark.parametrize(
    "shopify, kwargs",
    [
        (_Shopify(start_errors=[{"field": ["query"], "message": "Invalid"}]), {}),
        (_Shopify([_operation("FAILED", error_code="TIMEOUT")]), {}),
        (_Shopify([None]), {"resume_state": _IN_PROGRESS}),
        (_Shopify(), {"resume_state": ShopifyResumeConfig(phase=PHASE_ALL, cursor="c")}),
        (_Shopify(), {"api_version": SHOPIFY_API_VERSION_2025_10}),
        (_Shopify(), {"flag_enabled": False}),
        (_Shopify(), {"incremental": False}),
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
def test_reads_pages_when_the_bulk_export_cannot_be_used(shopify: _Shopify, kwargs: dict[str, Any]) -> None:
    result = _run(shopify, **kwargs)

    assert result.raised is None
    assert result.rows == [_PAGED_ORDER]
    assert shopify.operations[-1] == "PaginatedOrders"
    assert shopify.file_offsets == []


def test_paged_read_after_a_failed_operation_sends_a_new_token() -> None:
    class _RotatingTokens(_Shopify):
        minted = 0

        def __call__(self, request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/admin/oauth/access_token":
                self.minted += 1
                return ScriptedResponse(json={"access_token": f"tok-{self.minted}"})
            return super().__call__(request)

    shopify = _RotatingTokens([_operation("FAILED", error_code="TIMEOUT")])

    result = _run(shopify)

    assert result.rows == [_PAGED_ORDER]
    paged = [request for request in result.requests if b"PaginatedOrders" in (request.body or b"")]
    # The wait outlives a minted token, so the paged read cannot reuse the one it started with.
    assert [request.headers["x-shopify-access-token"] for request in paged] == [f"tok-{shopify.minted}"]
    assert shopify.minted > 1


def test_operation_that_ends_after_rows_were_written_clears_its_state_and_fails() -> None:
    resume_state = ShopifyResumeConfig(PHASE_BULK, "", _OPERATION_ID, _THIRD_ORDER_START)

    result = _run(_Shopify([_operation("EXPIRED")]), resume_state=resume_state)

    assert isinstance(result.raised, ShopifyBulkOperationError)
    assert result.final_state is None


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


@pytest.mark.parametrize("schema_exists, expected", [(False, False), (True, True)])
def test_bulk_export_flag_is_asked_for_the_schema_of_the_run(schema_exists: bool, expected: bool) -> None:
    schema = MagicMock() if schema_exists else None
    with (
        patch(f"{_SHOPIFY}.source.ExternalDataSchema.objects") as objects,
        patch(f"{_SHOPIFY}.source.is_schema_flag_enabled", return_value=True) as is_enabled,
    ):
        objects.filter.return_value.select_related.return_value.first.return_value = schema

        assert _is_bulk_export_enabled(7, "schema-id") is expected

    objects.filter.assert_called_once_with(team_id=7, id="schema-id")
    if schema_exists:
        is_enabled.assert_called_once_with(schema, WAREHOUSE_SHOPIFY_BULK_EXPORT_FLAG)
