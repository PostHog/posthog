from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.recreation import (
    RecreationSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recreation.recreation import (
    RecreationResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recreation.settings import (
    PAGE_LIMIT,
    RESERVATIONS_FORWARD_DAYS,
    RESERVATIONS_LOOKBACK_DAYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recreation.source import RecreationSource


def _ridb_response(records: list[dict[str, Any]], total_count: int, offset: int) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "RECDATA": records,
            "METADATA": {
                "RESULTS": {"CURRENT_COUNT": len(records), "TOTAL_COUNT": total_count},
                "SEARCH_PARAMETERS": {"QUERY": "", "LIMIT": PAGE_LIMIT, "OFFSET": offset},
            },
        }
    )


def _facility_rows(start: int, count: int) -> list[dict[str, Any]]:
    return [{"FacilityID": str(i), "FacilityName": f"Facility {i}"} for i in range(start, start + count)]


def _reservations_response(start: int, count: int) -> ScriptedResponse:
    rows = [{"HistoricalReservationID": str(i), "OrderDate": "2026-10-01"} for i in range(start, start + count)]
    return ScriptedResponse(json={"data": rows, "total_results": 120})


class TestRecreationSourceTransport:
    def _drive(self, endpoint: str, responses: list[ScriptedResponse | BaseException], **inputs: Any) -> DriveResult:
        config = RecreationSourceConfig(api_key="test-key")
        return SourceDriver(RecreationSource(), config).run(endpoint, responses, **inputs)

    def test_fresh_run_paginates_to_total_count_and_checkpoints(self) -> None:
        # 100 total records across two full pages: pagination must stop at TOTAL_COUNT
        # without paying a third, empty-page request.
        responses: list[ScriptedResponse | BaseException] = [
            _ridb_response(_facility_rows(0, PAGE_LIMIT), total_count=100, offset=0),
            _ridb_response(_facility_rows(PAGE_LIMIT, PAGE_LIMIT), total_count=100, offset=PAGE_LIMIT),
        ]
        result = self._drive("Facilities", responses)

        assert len(result.rows) == 100
        assert result.rows[0]["FacilityID"] == "0"
        assert result.params("offset") == ["0", str(PAGE_LIMIT)]
        assert result.params("limit") == [str(PAGE_LIMIT)] * 2

        # The api key must ride the header, never the query string.
        assert all("apikey" not in request.query for request in result.requests)
        assert all(request.headers["apikey"] == "test-key" for request in result.requests)

        # State is saved only after the non-terminal page, pointing at the next offset.
        assert result.saved_states == [RecreationResumeConfig(offset=PAGE_LIMIT)]

    def test_resume_seeds_paginator_with_saved_offset(self) -> None:
        responses: list[ScriptedResponse | BaseException] = [
            _ridb_response(_facility_rows(150, 10), total_count=160, offset=150)
        ]
        result = self._drive("Facilities", responses, resume_state=RecreationResumeConfig(offset=150))

        assert result.params("offset") == ["150"]

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        responses: list[ScriptedResponse | BaseException] = [
            _ridb_response(_facility_rows(0, 1), total_count=1, offset=0)
        ]
        result = self._drive("Facilities", responses)

        assert result.params("offset") == ["0"]

    @pytest.mark.parametrize(
        ("endpoint", "expected_path", "parent_rows", "expected_rows"),
        [
            (
                "CampsiteAttributes",
                "/api/v1/campsites",
                [
                    {
                        "CampsiteID": "10",
                        "ATTRIBUTES": [
                            {"AttributeName": "Max Num of People", "AttributeValue": "6"},
                            {"AttributeName": "Driveway Length", "AttributeValue": "40"},
                        ],
                    },
                    {"CampsiteID": "11", "ATTRIBUTES": []},
                    {"CampsiteID": "12", "ATTRIBUTES": None},
                    {"CampsiteID": "13", "ATTRIBUTES": [{"AttributeName": "Shade", "AttributeValue": "Yes"}]},
                ],
                [
                    {"CampsiteID": "10", "AttributeName": "Max Num of People", "AttributeValue": "6"},
                    {"CampsiteID": "10", "AttributeName": "Driveway Length", "AttributeValue": "40"},
                    {"CampsiteID": "13", "AttributeName": "Shade", "AttributeValue": "Yes"},
                ],
            ),
            (
                "PermitEntranceZones",
                "/api/v1/permitentrances",
                [
                    {
                        "PermitEntranceID": "200",
                        "ATTRIBUTES": [{"AttributeName": "Quota", "AttributeValue": "10"}],
                        "ZONES": [{"PermitEntranceZoneID": "1", "Zone": "North"}],
                    }
                ],
                [{"PermitEntranceID": "200", "PermitEntranceZoneID": "1", "Zone": "North"}],
            ),
        ],
    )
    def test_nested_tables_explode_the_parent_list_arrays(
        self,
        endpoint: str,
        expected_path: str,
        parent_rows: list[dict[str, Any]],
        expected_rows: list[dict[str, Any]],
    ) -> None:
        result = self._drive(endpoint, [_ridb_response(parent_rows, total_count=len(parent_rows), offset=0)])

        assert result.rows == expected_rows
        assert result.requests[0].path == expected_path

    def test_reservations_walk_pages_to_the_first_empty_page_and_checkpoint_the_page(self) -> None:
        responses: list[ScriptedResponse | BaseException] = [
            _reservations_response(0, PAGE_LIMIT),
            _reservations_response(PAGE_LIMIT, PAGE_LIMIT),
            _reservations_response(2 * PAGE_LIMIT, 0),
        ]
        result = self._drive("Reservations", responses)

        assert len(result.rows) == 2 * PAGE_LIMIT
        assert result.params("page") == ["0", "1", "2"]
        assert result.params("limit") == [str(PAGE_LIMIT)] * 3
        assert result.saved_states[0] == RecreationResumeConfig(
            page=1, date_from=result.params("dateFrom")[0], date_to=result.params("dateTo")[0]
        )

    def test_reservations_resume_from_the_saved_page_and_date_window(self) -> None:
        resume_state = RecreationResumeConfig(page=7, date_from="2025-01-01", date_to="2027-01-01")
        result = self._drive(
            "Reservations",
            [_reservations_response(0, 0)],
            resume_state=resume_state,
            incremental_field="OrderDate",
            db_incremental_field_last_value="2026-03-04",
        )

        assert result.params("page") == ["7"]
        assert result.params("dateFrom") == ["2025-01-01"]
        assert result.params("dateTo") == ["2027-01-01"]

    @pytest.mark.parametrize(
        ("inputs", "expected_from"),
        [
            ({}, None),
            ({"incremental_field": "OrderDate"}, None),
            ({"incremental_field": "OrderDate", "db_incremental_field_last_value": "2026-03-04"}, date(2026, 3, 4)),
            (
                {"incremental_field": "OrderDate", "db_incremental_field_last_value": datetime(2026, 3, 4, 15, 0)},
                date(2026, 3, 4),
            ),
            (
                {
                    "incremental_field": "OrderDate",
                    "should_use_incremental_field": False,
                    "db_incremental_field_last_value": "2026-03-04",
                },
                None,
            ),
        ],
    )
    def test_reservations_date_range(self, inputs: dict[str, Any], expected_from: date | None) -> None:
        result = self._drive("Reservations", [_reservations_response(0, 0)], **inputs)

        today = datetime.now(UTC).date()
        if expected_from is None:
            expected_from = today - timedelta(days=RESERVATIONS_LOOKBACK_DAYS)
        assert result.params("dateFrom") == [expected_from.isoformat()]
        assert result.params("dateTo") == [(today + timedelta(days=RESERVATIONS_FORWARD_DAYS)).isoformat()]
