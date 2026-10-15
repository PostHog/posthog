from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.schematic import (
    SchematicSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.schematic.schematic import SchematicResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.schematic.settings import (
    PAGE_SIZE,
    SCHEMATIC_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.schematic.source import SchematicSource


def _driver() -> SourceDriver:
    return SourceDriver(SchematicSource(), SchematicSourceConfig(api_key="sch_test_key"))


def _page(rows: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"data": rows, "params": {"limit": PAGE_SIZE}})


def _rows(prefix: str, count: int) -> list[dict[str, Any]]:
    return [{"id": f"{prefix}_{index}", "product_id": f"{prefix}_{index}"} for index in range(count)]


class TestSchematicPagination:
    @pytest.mark.parametrize("endpoint", sorted(SCHEMATIC_ENDPOINTS))
    def test_walks_offset_pages_until_a_short_page(self, endpoint: str) -> None:
        # A full page advances the offset and stages it; the short second page ends the walk, so no
        # third request goes out and no state covers it.
        result = _driver().run(endpoint, [_page(_rows("a", PAGE_SIZE)), _page(_rows("b", 3))])

        assert result.raised is None
        assert result.paths == [SCHEMATIC_ENDPOINTS[endpoint].path] * 2
        assert result.params("offset") == ["0", str(PAGE_SIZE)]
        assert result.params("limit") == [str(PAGE_SIZE)] * 2
        assert [request.headers["x-schematic-api-key"] for request in result.requests] == ["sch_test_key"] * 2
        assert result.saved_states == [SchematicResumeConfig(offset=PAGE_SIZE)]
        assert len(result.rows) == PAGE_SIZE + 3

    def test_empty_first_page_yields_nothing_and_saves_no_state(self) -> None:
        result = _driver().run("companies", [_page([])])

        assert result.raised is None
        assert result.rows == []
        assert result.saved_states == []

    def test_resume_starts_from_the_saved_offset(self) -> None:
        result = _driver().run("companies", [_page(_rows("c", 1))], resume_state=SchematicResumeConfig(offset=300))

        assert result.raised is None
        assert result.params("offset") == ["300"]


class TestSchematicValidateCredentials:
    @pytest.mark.parametrize(
        ("status", "body", "expected_valid", "expected_fragment"),
        [
            (200, {"data": [], "params": {}}, True, None),
            (401, {"error": "Unauthorized", "message": "invalid api key"}, False, "rejected the API key"),
            (500, {"error": "internal"}, False, "Could not reach"),
        ],
    )
    def test_maps_the_probe_status_to_a_message(
        self, status: int, body: dict[str, Any], expected_valid: bool, expected_fragment: str | None
    ) -> None:
        config = SchematicSourceConfig(api_key="sch_test_key")
        # `always` because the transport retries a 5xx; assert the set of URLs, not the count.
        with scripted_network(always(ScriptedResponse(status=status, json=body))) as network:
            is_valid, message = SchematicSource().validate_credentials(config, team_id=1)

        assert is_valid is expected_valid
        assert (message is None) if expected_fragment is None else (expected_fragment in (message or ""))
        assert {request.url for request in network.requests_log} == {"https://api.schematichq.com/companies?limit=1"}
        assert network.requests_log[0].headers["x-schematic-api-key"] == "sch_test_key"
