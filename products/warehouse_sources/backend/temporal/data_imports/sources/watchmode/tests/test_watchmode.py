import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.watchmode import (
    WatchmodeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.watchmode.source import WatchmodeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.watchmode.watchmode import WatchmodeResumeConfig


class TestWatchmodeSourceResumeBehavior:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(WatchmodeSource(), WatchmodeSourceConfig(api_key="test-key"))

    def test_resume_seeds_paginator_with_saved_page(self) -> None:
        result = self._driver().run(
            "titles",
            [ScriptedResponse(json={"titles": [{"id": 50}], "total_pages": 5})],
            resume_state=WatchmodeResumeConfig(page=5),
        )

        assert result.params("page") == ["5"]
        assert result.rows == [{"id": 50}]
        assert result.raised is None

    def test_endpoint_ignoring_page_param_terminates_without_duplicate_rows(self) -> None:
        body = {"releases": [{"id": 1, "source_id": 203}, {"id": 1, "source_id": 57}]}
        result = self._driver().run("releases", [ScriptedResponse(json=body), ScriptedResponse(json=body)])

        assert len(result.requests) == 2
        assert result.rows == [{"id": 1, "source_id": 203}, {"id": 1, "source_id": 57}]
        assert result.raised is None

    def test_sync_requests_do_not_follow_redirects(self) -> None:
        # `requests` replays the `X-API-Key` header across a cross-host redirect, so a
        # dropped `allow_redirects=False` would forward the customer's key off-host.
        result = self._driver().run(
            "titles",
            [ScriptedResponse(status=302, headers={"Location": "https://example.com/redirect"})],
        )

        assert result.paths == ["/v1/list-titles/"]
        assert result.requests[0].headers["x-api-key"] == "test-key"
        assert isinstance(result.raised, ValueError)

    @pytest.mark.parametrize("endpoint", ["sources", "regions", "networks", "genres"])
    def test_reference_endpoints_fetch_a_single_unpaginated_page(self, endpoint: str) -> None:
        row = {"id": 1, "country": "US", "name": "row"}
        result = self._driver().run(endpoint, [ScriptedResponse(json=[row])])

        assert len(result.requests) == 1
        assert result.requests[0].param("page") is None
        assert result.rows == [row]
        assert result.saved_states == []
        assert result.raised is None
