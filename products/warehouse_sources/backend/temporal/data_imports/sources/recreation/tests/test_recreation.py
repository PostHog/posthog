from typing import Any

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
from products.warehouse_sources.backend.temporal.data_imports.sources.recreation.settings import PAGE_LIMIT
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
