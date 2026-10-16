from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.xero import XeroSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.xero.settings import PAGE_SIZE
from products.warehouse_sources.backend.temporal.data_imports.sources.xero.source import XeroSource
from products.warehouse_sources.backend.temporal.data_imports.sources.xero.xero import (
    XeroResumeConfig,
    convert_ms_json_dates,
)

TENANT_ID = "tenant-abc"


def _run(schema: str, script: list[ScriptedResponse], **inputs: Any) -> DriveResult:
    driver = SourceDriver(XeroSource(), XeroSourceConfig(xero_integration_id=7, tenant_id=TENANT_ID))
    with patch.object(XeroSource, "_build_auth", return_value=BearerTokenAuth("at_1")):
        return driver.run(schema, script, **inputs)


def _invoices_page(ids: list[str], page: int, page_count: int) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "Invoices": [{"InvoiceID": i, "UpdatedDateUTC": "/Date(1714557600000+0000)/"} for i in ids],
            "pagination": {"page": page, "pageSize": PAGE_SIZE, "pageCount": page_count, "itemCount": 3},
        }
    )


class TestXeroTransport:
    def test_full_refresh_walks_pages_until_page_count_and_stages_the_next_page(self) -> None:
        result = _run(
            "invoices",
            [_invoices_page(["a", "b"], 1, 2), _invoices_page(["c"], 2, 2)],
            should_use_incremental_field=False,
        )

        assert result.raised is None
        assert result.paths == ["/api.xro/2.0/Invoices"] * 2
        assert result.params("page") == ["1", "2"]
        assert result.params("pageSize") == [str(PAGE_SIZE)] * 2
        assert result.params("order") == ["UpdatedDateUTC ASC"] * 2
        assert result.params("includeArchived") == ["true"] * 2
        assert {request.headers["xero-tenant-id"] for request in result.requests} == {TENANT_ID}
        assert result.requests[0].headers["authorization"] == "Bearer at_1"
        assert result.saved_states == [XeroResumeConfig(page=2)]
        assert [row["InvoiceID"] for row in result.rows] == ["a", "b", "c"]

    def test_full_refresh_resumes_from_the_saved_page(self) -> None:
        result = _run(
            "invoices",
            [_invoices_page(["c"], 2, 2)],
            should_use_incremental_field=False,
            resume_state=XeroResumeConfig(page=2),
        )

        assert result.raised is None
        assert result.params("page") == ["2"]

    @pytest.mark.parametrize(
        ("incremental", "last_value", "expected_header"),
        [
            (True, datetime(2024, 5, 1, 10, 0, tzinfo=UTC), "2024-05-01T10:00:00"),
            (True, "2024-05-01T12:00:00+02:00", "2024-05-01T10:00:00"),
            (True, None, None),
            (False, datetime(2024, 5, 1, 10, 0, tzinfo=UTC), None),
        ],
    )
    def test_incremental_runs_send_the_watermark_as_if_modified_since(
        self, incremental: bool, last_value: Any, expected_header: str | None
    ) -> None:
        result = _run(
            "invoices",
            [_invoices_page(["a"], 1, 1)],
            incremental_field="UpdatedDateUTC",
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.requests[0].headers.get("if-modified-since") == expected_header

    def test_incremental_walk_moves_if_modified_since_instead_of_paging(self) -> None:
        # A row updated mid-walk moves to the end of the sorted list, so page numbers would skip
        # the row that slides into the gap. The cursor walk restarts at page 1 from the last row.
        def page(updated_ms: list[int]) -> ScriptedResponse:
            rows = [{"InvoiceID": f"r{i}", "UpdatedDateUTC": f"/Date({ms}+0000)/"} for i, ms in enumerate(updated_ms)]
            return ScriptedResponse(json={"Invoices": rows})

        first = [1714557600000 + i * 1000 for i in range(PAGE_SIZE)]
        same_second = [first[-1] + 1000] * PAGE_SIZE
        result = _run(
            "invoices",
            [page(first), page(same_second), page(same_second), page([same_second[0] + 5000])],
            incremental_field="UpdatedDateUTC",
            db_incremental_field_last_value=datetime(2024, 5, 1, 9, 0, tzinfo=UTC),
        )

        assert result.raised is None
        assert [r.headers.get("if-modified-since") for r in result.requests] == [
            "2024-05-01T09:00:00",
            "2024-05-01T10:16:39",
            "2024-05-01T10:16:40",
            "2024-05-01T10:16:40",
        ]
        assert result.params("page") == ["1", "1", "1", "2"]
        assert result.saved_states == []

    @pytest.mark.parametrize(
        ("schema", "data_key", "expected_order"),
        [("accounts", "Accounts", "UpdatedDateUTC ASC"), ("organisation", "Organisations", None)],
    )
    def test_unpaged_endpoints_make_one_request_without_page_params(
        self, schema: str, data_key: str, expected_order: str | None
    ) -> None:
        result = _run(schema, [ScriptedResponse(json={data_key: [{"Name": "x"}]})], should_use_incremental_field=False)

        assert result.raised is None
        assert len(result.requests) == 1
        assert result.params("page") == [None]
        assert result.params("order") == [expected_order]
        assert result.rows == [{"Name": "x"}]


class TestConvertMsJsonDates:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("/Date(1714557600000+0000)/", datetime(2024, 5, 1, 10, 0, tzinfo=UTC)),
            ("/Date(1714557600000+1300)/", datetime(2024, 5, 1, 10, 0, tzinfo=UTC)),
            ("/Date(1714557600000)/", datetime(2024, 5, 1, 10, 0, tzinfo=UTC)),
            ("/Date(-86400000+0000)/", datetime(1969, 12, 31, tzinfo=UTC)),
            ("2024-05-01T10:00:00", "2024-05-01T10:00:00"),
            ("Paid /Date(1)/ late", "Paid /Date(1)/ late"),
            (None, None),
            ({"Date": "/Date(1714557600000+0000)/"}, {"Date": "/Date(1714557600000+0000)/"}),
        ],
    )
    def test_converts_only_whole_top_level_date_strings(self, value: Any, expected: Any) -> None:
        assert convert_ms_json_dates({"field": value, "InvoiceID": "a"}) == {"field": expected, "InvoiceID": "a"}
