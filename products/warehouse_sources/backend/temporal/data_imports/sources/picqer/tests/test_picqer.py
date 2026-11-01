from datetime import date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.picqer import PicqerSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.picqer.picqer import (
    PicqerResumeConfig,
    _build_params,
    normalize_account,
    to_picqer_datetime,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.picqer.settings import PAGE_SIZE, PICQER_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.picqer.source import PicqerSource


class TestNormalizeAccount:
    @pytest.mark.parametrize(
        "value",
        [
            "acme/../evil",
            "acme.evil.com",
            "acme@evil.com",
            "",
            "ac me",
            "acme-",
        ],
    )
    def test_invalid_accounts_raise(self, value: str) -> None:
        # The account is the host the stored API key is sent to; a loosened regex would let an org
        # member retarget the credential at a server they control.
        with pytest.raises(ValueError):
            normalize_account(value)


class TestToPicqerDatetime:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2020, 1, 2, 3, 4, 5), "2020-01-02 03:04:05"),
            (date(2020, 1, 2), "2020-01-02 00:00:00"),
            ("2020-01-02T03:04:05", "2020-01-02 03:04:05"),
            ("2020-01-02 03:04:05", "2020-01-02 03:04:05"),
        ],
    )
    def test_format(self, value: Any, expected: str) -> None:
        # Picqer's `updated_after` filter expects `YYYY-MM-DD HH:MM:SS`; a broken format silently
        # returns wrong/empty incremental pages.
        assert to_picqer_datetime(value) == expected


class TestBuildParams:
    def test_full_refresh_endpoint_never_filters(self) -> None:
        # orders exposes only a creation-date filter (`sincedate`), so it syncs full refresh; a
        # cursor must never leak into the request and silently drop updated rows.
        params = _build_params(
            PICQER_ENDPOINTS["orders"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2020, 1, 2, 3, 4, 5),
        )
        assert params == {}


def _page(n: int) -> ScriptedResponse:
    # Picqer list endpoints return a bare JSON array (no envelope).
    return ScriptedResponse(json=[{"idorder": i} for i in range(n)])


def _driver() -> SourceDriver:
    return SourceDriver(PicqerSource(), PicqerSourceConfig(account_name="acme", api_key="key"))


class TestPagination:
    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run("orders", [_page(2)], resume_state=PicqerResumeConfig(offset=PAGE_SIZE))

        assert result.raised is None
        assert len(result.rows) == 2
        assert result.params("offset") == [str(PAGE_SIZE)]

    @pytest.mark.parametrize(
        "endpoint,incremental_field,filter_param",
        [
            ("purchaseorders", "updated", "updated_after"),
            ("stockhistory", "changed_at", "sincedate"),
        ],
    )
    def test_incremental_filter_present_on_every_page(
        self, endpoint: str, incremental_field: str, filter_param: str
    ) -> None:
        result = _driver().run(
            endpoint,
            [_page(PAGE_SIZE), _page(1)],
            incremental_field=incremental_field,
            db_incremental_field_last_value=datetime(2020, 1, 2, 3, 4, 5),
        )

        # The filter must stay on every paginated request so pagination walks only the filtered set.
        assert result.raised is None
        assert result.params(filter_param) == ["2020-01-02 03:04:05"] * 2
        assert result.params("offset") == ["0", str(PAGE_SIZE)]

    @pytest.mark.parametrize(
        "endpoint,primary_key",
        [
            ("return_reasons", "idreturn_reason"),
            ("return_statuses", "idreturn_status"),
        ],
    )
    def test_unpaginated_endpoint_stops_after_one_full_page(self, endpoint: str, primary_key: str) -> None:
        # These lookups are not documented as paginated; an offset loop would refetch the same full
        # page forever if the endpoint ignores `offset`.
        rows = [{primary_key: i, "name": f"Row {i}"} for i in range(PAGE_SIZE)]
        result = _driver().run(endpoint, route({f"/{endpoint}": [ScriptedResponse(json=rows)]}))

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE
        assert result.paths == [f"/api/v1/{endpoint}"]
        assert result.params("offset") == [None]


def _stock_row(idproduct: int, idwarehouse: int | None) -> dict[str, Any]:
    stock: dict[str, Any] = {"stock": 5, "reserved": 1, "freestock": 4}
    if idwarehouse is not None:
        stock["idwarehouse"] = idwarehouse
    return {"idproduct": idproduct, "productcode": f"SKU-{idproduct}", "stock": stock}


def _warehouse_stock_script(warehouse_ids: list[int], stock_pages: dict[int, list[ScriptedResponse]]) -> Any:
    table: dict[str, list[ScriptedResponse]] = {
        "/warehouses": [ScriptedResponse(json=[{"idwarehouse": i, "name": f"Warehouse {i}"} for i in warehouse_ids])]
    }
    for idwarehouse, pages in stock_pages.items():
        table[f"/warehouses/{idwarehouse}/stock"] = pages
    return route(table)


class TestWarehouseStock:
    def test_fans_out_over_warehouses_and_flattens_stock(self) -> None:
        script = _warehouse_stock_script(
            [1, 2, 3],
            {
                1: [
                    ScriptedResponse(json=[_stock_row(i, 1) for i in range(PAGE_SIZE)]),
                    ScriptedResponse(json=[_stock_row(PAGE_SIZE, 1)]),
                ],
                # Deleted between the warehouse listing and the stock fetch.
                2: [ScriptedResponse(status=404, json={"error": "not found"})],
                # Nested object without its own idwarehouse: the parent id fills the key.
                3: [ScriptedResponse(json=[_stock_row(7, None)])],
            },
        )

        result = _driver().run("warehouse_stock", script)

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 2
        keys = {(row["idwarehouse"], row["idproduct"]) for row in result.rows}
        assert len(keys) == len(result.rows)
        assert (3, 7) in keys
        assert result.rows[-1] == {
            "idproduct": 7,
            "productcode": "SKU-7",
            "stock": 5,
            "reserved": 1,
            "freestock": 4,
            "idwarehouse": 3,
        }
        assert result.paths == [
            "/api/v1/warehouses",
            "/api/v1/warehouses/1/stock",
            "/api/v1/warehouses/1/stock",
            "/api/v1/warehouses/2/stock",
            "/api/v1/warehouses/3/stock",
        ]
        assert result.params("offset")[1:3] == ["0", str(PAGE_SIZE)]

    def test_resumes_mid_warehouse_and_skips_completed_ones(self) -> None:
        script = _warehouse_stock_script([1, 2], {2: [ScriptedResponse(json=[_stock_row(9, 2)])]})

        result = _driver().run(
            "warehouse_stock",
            script,
            resume_state=PicqerResumeConfig(
                fanout_state={
                    "completed": ["/warehouses/1/stock"],
                    "current": "/warehouses/2/stock",
                    "child_state": {"offset": PAGE_SIZE},
                }
            ),
        )

        assert result.raised is None
        assert [(row["idwarehouse"], row["idproduct"]) for row in result.rows] == [(2, 9)]
        assert result.paths == ["/api/v1/warehouses", "/api/v1/warehouses/2/stock"]
        assert result.params("offset") == ["0", str(PAGE_SIZE)]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status,expected_ok",
        [
            # 403 = valid key, insufficient scope — accepted at source-create (per-table scope
            # reported separately).
            (403, True),
        ],
    )
    def test_status_mapping(self, status: int, expected_ok: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            ok, code = validate_credentials("acme", "key")

        assert ok is expected_ok
        assert code == status
        assert {request.path for request in network.requests_log} == {"/api/v1/warehouses"}

    def test_bad_account_raises_before_probe(self) -> None:
        # A malformed account must fail loud (so the caller can surface a precise message) rather
        # than being swallowed as an unreachable probe.
        with pytest.raises(ValueError):
            validate_credentials("acme.evil.com", "key")
