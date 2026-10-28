from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.airtable.airtable import (
    _format_created_time,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.airtable.source import AirtableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.airtable import (
    AirtableSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(AirtableSource(), AirtableSourceConfig(personal_access_token="pat"))


class TestFormatCreatedTime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05.000Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05.000Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00.000Z"),
            ("2024-01-02T03:04:05.000Z", "2024-01-02T03:04:05.000Z"),
        ],
    )
    def test_format_values(self, value: Any, expected: str) -> None:
        assert _format_created_time(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("pat") is expected

        assert network.requests_log[0].path == "/v0/meta/bases"
        assert network.requests_log[0].headers["authorization"] == "Bearer pat"


class TestTables:
    def test_fans_out_over_bases_and_injects_base_id(self) -> None:
        result = _driver().run(
            "tables",
            [
                ScriptedResponse(json={"bases": [{"id": "app1"}, {"id": "app2"}]}),
                ScriptedResponse(json={"tables": [{"id": "tbl1", "name": "Tasks"}]}),
                ScriptedResponse(json={"tables": [{"id": "tbl2", "name": "Leads"}]}),
            ],
        )

        assert result.raised is None
        assert [(t["id"], t["_base_id"]) for t in result.rows] == [("tbl1", "app1"), ("tbl2", "app2")]
        # No leaked include_from_parent scaffolding key.
        assert all("_bases_id" not in t for t in result.rows)
        assert result.paths[1:] == ["/v0/meta/bases/app1/tables", "/v0/meta/bases/app2/tables"]


class TestRecords:
    def test_fans_out_over_tables_and_paginates_records(self) -> None:
        result = _driver().run(
            "records",
            [
                ScriptedResponse(json={"bases": [{"id": "app1"}]}),
                ScriptedResponse(json={"tables": [{"id": "tbl1"}]}),
                ScriptedResponse(
                    json={"records": [{"id": "rec1", "createdTime": "2024-01-01T00:00:00.000Z"}], "offset": "off1"}
                ),
                ScriptedResponse(json={"records": [{"id": "rec2", "createdTime": "2024-01-02T00:00:00.000Z"}]}),
            ],
        )

        assert result.raised is None
        assert [(r["id"], r["_base_id"], r["_table_id"]) for r in result.rows] == [
            ("rec1", "app1", "tbl1"),
            ("rec2", "app1", "tbl1"),
        ]
        # No leaked include_from_parent scaffolding keys.
        assert all("_tables__base_id" not in r and "_tables_id" not in r for r in result.rows)
        assert result.paths[2] == "/v0/app1/tbl1"
        assert result.requests[2].param("pageSize") == "100"
        assert result.requests[3].param("offset") == "off1"

    def test_incremental_records_filter_on_created_time(self) -> None:
        result = _driver().run(
            "records",
            [
                ScriptedResponse(json={"bases": [{"id": "app1"}]}),
                ScriptedResponse(json={"tables": [{"id": "tbl1"}]}),
                ScriptedResponse(json={"records": []}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[2].param("filterByFormula") == 'IS_AFTER(CREATED_TIME(), "2024-01-02T00:00:00.000Z")'

    def test_full_refresh_sends_no_filter(self) -> None:
        result = _driver().run(
            "records",
            [
                ScriptedResponse(json={"bases": [{"id": "app1"}]}),
                ScriptedResponse(json={"tables": [{"id": "tbl1"}]}),
                ScriptedResponse(json={"records": []}),
            ],
        )

        assert result.raised is None
        assert result.requests[2].param("filterByFormula") is None

    def test_table_without_id_fails_loudly(self) -> None:
        result = _driver().run(
            "records",
            [
                ScriptedResponse(json={"bases": [{"id": "app1"}]}),
                ScriptedResponse(json={"tables": [{"name": "broken"}]}),
            ],
        )

        # A table row missing its id can't bind the {table_id} path param — fail loud, don't skip it.
        assert isinstance(result.raised, ValueError)
        assert "table_id" in str(result.raised)
