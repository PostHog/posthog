from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from unittest.mock import patch

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.buildium.buildium import BuildiumResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.buildium.settings import (
    AUTH_ERROR,
    CUSTOM_FIELD_ENTITY_TYPES,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buildium.source import BuildiumSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.buildium import (
    BuildiumSourceConfig,
)

CONFIG = BuildiumSourceConfig(client_id="example-client", client_secret="example-secret")


def driver() -> SourceDriver:
    return SourceDriver(BuildiumSource(), CONFIG)


@pytest.mark.parametrize(
    ("pages", "total", "expected_offsets", "expected_ids"),
    [
        ([[{"Id": 1}, {"Id": 2}], [{"Id": 3}]], 3, ["0", "2"], [1, 2, 3]),
        ([[{"Id": 1}, {"Id": 2}]], 2, ["0"], [1, 2]),
        ([[{"Id": 1}, {"Id": 2}], []], None, ["0", "2"], [1, 2]),
        ([[]], 0, ["0"], []),
    ],
)
def test_pagination(
    pages: list[list[dict[str, object]]],
    total: int | None,
    expected_offsets: list[str],
    expected_ids: list[int],
) -> None:
    script = [
        ScriptedResponse(json=page, headers={"X-Total-Count": str(total)} if total is not None else {})
        for page in pages
    ]
    with patch("products.warehouse_sources.backend.temporal.data_imports.sources.buildium.buildium.PAGE_SIZE", 2):
        result = driver().run("leases", script)

    assert result.raised is None
    assert [row["Id"] for row in result.rows] == expected_ids
    assert result.params("offset") == expected_offsets
    assert result.saved_states == ([BuildiumResumeConfig(offset=2)] if len(expected_offsets) > 1 else [])


@pytest.mark.parametrize("endpoint", ["leases", "applicants"])
@pytest.mark.parametrize(
    ("incremental", "watermark", "expected_filter"),
    [
        (True, None, None),
        (False, "2026-01-02T03:04:05Z", None),
        (True, "2026-01-02T03:04:05.999Z", "2026-01-02T03:04:05Z"),
        (True, datetime(2026, 1, 2, 3, 4, 5), "2026-01-02T03:04:05Z"),
        (True, datetime(2026, 1, 2, 5, 4, 5, tzinfo=timezone(timedelta(hours=2))), "2026-01-02T03:04:05Z"),
    ],
)
def test_incremental_filter_and_timestamp(
    endpoint: str, incremental: bool, watermark: datetime | str | None, expected_filter: str | None
) -> None:
    data: list[dict[str, Any]] = [
        {"Id": 1, "LastUpdatedDateTime": "2026-01-03T00:00:00Z"},
        {"Id": 2, "LastUpdatedDateTime": None},
    ]
    result = driver().run(
        endpoint,
        [ScriptedResponse(json=data)],
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
    )

    assert result.raised is None
    assert result.requests[0].param("lastupdatedfrom") == expected_filter
    assert result.requests[0].param("orderby") == "Id asc"
    assert result.response is not None
    assert result.response.sort_mode == "desc"
    assert result.rows == [
        {"Id": 1, "LastUpdatedDateTime": datetime(2026, 1, 3, tzinfo=UTC)},
        {"Id": 2, "LastUpdatedDateTime": None},
    ]


@pytest.mark.parametrize("original_filter", [None, "2026-01-01T00:00:00Z"])
def test_resume_keeps_filter_and_offset(original_filter: str | None) -> None:
    result = driver().run(
        "leases",
        [ScriptedResponse(json=[{"Id": 1001}])],
        resume_state=BuildiumResumeConfig(offset=1000, updated_from=original_filter),
        should_use_incremental_field=True,
        db_incremental_field_last_value="2026-01-05T00:00:00Z",
    )

    assert result.raised is None
    assert result.rows == [{"Id": 1001}]
    assert result.requests[0].param("offset") == "1000"
    assert result.requests[0].param("lastupdatedfrom") == original_filter


@pytest.mark.parametrize(("status", "message"), [(401, AUTH_ERROR), (403, PERMISSION_ERROR)])
def test_sync_error_mapping(status: int, message: str) -> None:
    result = driver().run("leases", [ScriptedResponse(status=status, json=[])])

    assert isinstance(result.raised, HTTPError)
    errors = BuildiumSource().get_non_retryable_errors()
    assert next(value for key, value in errors.items() if key in str(result.raised)) == message


def _gl_transaction(transaction_id: int, *account_ids: int) -> dict[str, Any]:
    return {
        "Id": transaction_id,
        "Journal": {"Lines": [{"GLAccount": {"Id": account_id}} for account_id in account_ids]},
    }


GL_TRANSACTION_PAGES: dict[tuple[tuple[str, ...], str], list[dict[str, Any]]] = {
    (("10", "30"), "0"): [_gl_transaction(1, 10), _gl_transaction(2, 30, 31)],
    (("10", "30"), "2"): [_gl_transaction(3, 31, 10)],
    # Transactions 2 and 3 also have a line in this batch, but the first batch already returned them.
    (("31",), "0"): [_gl_transaction(2, 30, 31), _gl_transaction(3, 31, 10)],
    (("31",), "2"): [_gl_transaction(4, 31), {"Id": 5, "Journal": None}],
}


@pytest.mark.parametrize(
    ("accounts", "resume_state", "watermark", "expected_batches", "expected_ids", "expected_saved"),
    [
        (
            [{"Id": 30, "SubAccounts": [{"Id": 31}]}, {"Id": 10, "SubAccounts": None}],
            None,
            None,
            [(("10", "30"), "0"), (("10", "30"), "2"), (("31",), "0"), (("31",), "2")],
            [1, 2, 3, 4, 5],
            [
                BuildiumResumeConfig(offset=2, gl_account_batch=0),
                BuildiumResumeConfig(offset=0, gl_account_batch=1),
                BuildiumResumeConfig(offset=2, gl_account_batch=1),
            ],
        ),
        (
            [{"Id": 30, "SubAccounts": [{"Id": 31}]}, {"Id": 10}],
            BuildiumResumeConfig(offset=2, updated_from="2026-01-01T00:00:00Z", gl_account_batch=1),
            "2026-02-01T00:00:00Z",
            [(("31",), "2")],
            [4, 5],
            [],
        ),
        (
            [{"Id": 10}, {"Id": 30}],
            None,
            "2026-02-01T00:00:00Z",
            [(("10", "30"), "0"), (("10", "30"), "2")],
            [1, 2, 3],
            [BuildiumResumeConfig(offset=2, updated_from="2026-02-01T00:00:00Z", gl_account_batch=0)],
        ),
        ([], None, None, [], [], []),
    ],
)
def test_general_ledger_transactions_batches_accounts(
    accounts: list[dict[str, Any]],
    resume_state: BuildiumResumeConfig | None,
    watermark: str | None,
    expected_batches: list[tuple[tuple[str, ...], str]],
    expected_ids: list[int],
    expected_saved: list[BuildiumResumeConfig],
) -> None:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/v1/glaccounts":
            return ScriptedResponse(json=accounts, headers={"X-Total-Count": str(len(accounts))})
        batch = request.query["glaccountids"]
        total = 3 if batch == ("10", "30") else 4
        page = GL_TRANSACTION_PAGES[(batch, request.param("offset") or "0")]
        return ScriptedResponse(json=page, headers={"X-Total-Count": str(total)})

    module = "products.warehouse_sources.backend.temporal.data_imports.sources.buildium.buildium"
    with patch(f"{module}.PAGE_SIZE", 2), patch(f"{module}.GL_ACCOUNT_BATCH_SIZE", 2):
        result = driver().run(
            "general_ledger_transactions",
            respond,
            resume_state=resume_state,
            should_use_incremental_field=watermark is not None,
            db_incremental_field_last_value=watermark,
        )

    assert result.raised is None
    assert [row["Id"] for row in result.rows] == expected_ids
    assert result.saved_states == expected_saved
    assert result.paths[0] == "/v1/glaccounts"
    transaction_requests = result.requests[1:]
    assert [(request.query["glaccountids"], request.param("offset")) for request in transaction_requests] == (
        expected_batches
    )
    expected_filter = resume_state.updated_from if resume_state else watermark
    for request in transaction_requests:
        assert request.path == "/v1/generalledger/transactions"
        assert request.param("startdate") == "1900-01-01"
        assert request.param("enddate") == "2099-12-31"
        assert request.param("orderby") == "Id asc"
        assert request.param("lastupdatedfrom") == (None if watermark is None else expected_filter)


def test_lease_transactions_fan_out_over_leases() -> None:
    script = route(
        {
            "/v1/leases": [ScriptedResponse(json=[{"Id": 7}, {"Id": 8}], headers={"X-Total-Count": "2"})],
            "/v1/leases/7/transactions": [
                ScriptedResponse(
                    json=[{"Id": 100, "LeaseId": 7, "TotalAmount": 1250.5}], headers={"X-Total-Count": "1"}
                )
            ],
            "/v1/leases/8/transactions": [
                ScriptedResponse(status=404, json={"UserMessage": "The lease could not be found.", "Errors": []})
            ],
        }
    )
    result = driver().run("lease_transactions", script)

    assert result.raised is None
    assert result.rows == [{"Id": 100, "LeaseId": 7, "TotalAmount": 1250.5, "_leases_Id": 7}]
    assert result.paths == ["/v1/leases", "/v1/leases/7/transactions", "/v1/leases/8/transactions"]
    assert result.params("orderby") == ["Id asc"] * 3


@pytest.mark.parametrize(
    ("endpoint", "row", "expected_row", "expected_orderby"),
    [
        (
            "bank_accounts",
            {"Id": 3, "AccountNumber": "XXXX1234", "AccountNumberUnmasked": "000011111234", "Balance": 10.0},
            {"Id": 3, "AccountNumber": "XXXX1234", "Balance": 10.0},
            "Id asc",
        ),
        (
            "lease_outstanding_balances",
            {"LeaseId": 7, "TotalBalance": 300.0, "Balances": [{"GLAccountId": 10, "TotalBalance": 300.0}]},
            {"LeaseId": 7, "TotalBalance": 300.0, "Balances": [{"GLAccountId": 10, "TotalBalance": 300.0}]},
            "LeaseId asc",
        ),
    ],
)
def test_top_level_row_shaping_and_order(
    endpoint: str, row: dict[str, Any], expected_row: dict[str, Any], expected_orderby: str
) -> None:
    result = driver().run(endpoint, [ScriptedResponse(json=[row], headers={"X-Total-Count": "1"})])

    assert result.raised is None
    assert result.rows == [expected_row]
    assert result.params("orderby") == [expected_orderby]


@pytest.mark.parametrize(
    ("endpoint", "path"), [("inventory_storages", "/v1/inventorystorages"), ("asset_categories", "/v1/assetcategories")]
)
def test_unpaginated_lists_read_one_response(endpoint: str, path: str) -> None:
    rows = [{"Id": index, "Name": f"Item {index}"} for index in range(3)]
    with patch("products.warehouse_sources.backend.temporal.data_imports.sources.buildium.buildium.PAGE_SIZE", 2):
        result = driver().run(endpoint, always(ScriptedResponse(json=rows)))

    assert result.raised is None
    assert result.rows == rows
    assert result.paths == [path]
    assert result.queries == [{}]
    assert result.saved_states == []


def test_custom_field_definitions_read_every_entity_type() -> None:
    definitions = {
        "Rentals": [{"Id": 1, "EntityTypeName": "Rentals", "Configuration": {"Type": "ShortText"}}],
        "Vendors": [{"Id": 2, "EntityTypeName": "Vendors"}, {"Id": 3, "EntityTypeName": "Vendors"}],
    }

    def respond(request: RecordedRequest) -> ScriptedResponse:
        entity_type = request.path.split("/")[4]
        return ScriptedResponse(json=definitions.get(entity_type, []))

    result = driver().run("custom_field_definitions", respond)

    assert result.raised is None
    assert [row["Id"] for row in result.rows] == [1, 2, 3]
    assert result.rows[0]["Configuration"] == {"Type": "ShortText"}
    assert result.paths == [
        f"/v1/customfields/entityType/{entity_type}/definitions" for entity_type in CUSTOM_FIELD_ENTITY_TYPES
    ]
    assert all(params == {} for params in result.queries)
