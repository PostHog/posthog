import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.waydev import WaydevSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.waydev.source import WaydevSource
from products.warehouse_sources.backend.temporal.data_imports.sources.waydev.waydev import (
    WaydevResumeConfig,
    validate_credentials,
)


class TestWaydevSourceResumeBehavior:
    """End-to-end resume behaviour of ``WaydevSource``, driven through ``source_for_pipeline``."""

    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(WaydevSource(), WaydevSourceConfig(api_key="test-key"))

    def test_incidents_resume_seeds_paginator_with_saved_page(self) -> None:
        result = self._driver().run(
            "Incidents",
            [ScriptedResponse(json={"current_page": 5, "data": []})],
            resume_state=WaydevResumeConfig(next_page=5),
        )

        assert result.params("page") == ["5"]

    def test_a_single_real_page_still_probes_once_more_before_stopping(self) -> None:
        # stop_after_empty_page means the last real page is always followed by one more
        # request that comes back empty (no total-pages field is documented for this endpoint).
        result = self._driver().run(
            "Incidents",
            [
                ScriptedResponse(json={"current_page": 1, "data": [{"id": 1}]}),
                ScriptedResponse(json={"current_page": 2, "data": []}),
            ],
        )

        assert result.params("page") == ["1", "2"]
        assert result.saved_states == [WaydevResumeConfig(next_page=2)]

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = self._driver().run("Incidents", [ScriptedResponse(json={"current_page": 1, "data": []})])

        assert result.params("page") == ["1"]


class TestWaydevListEndpoints:
    @pytest.mark.parametrize(
        ("endpoint", "script", "expected_pages", "expected_ids", "expected_query"),
        [
            (
                "Repositories",
                [
                    ScriptedResponse(json={"count": 3, "values": [{"id": 11}, {"id": 12}]}),
                    ScriptedResponse(json={"count": 3, "values": [{"id": 13}]}),
                    ScriptedResponse(json={"count": 3, "values": []}),
                ],
                ["1", "2", "3"],
                [11, 12, 13],
                {"state": "all", "limit": "500"},
            ),
            (
                "Teams",
                [
                    ScriptedResponse(json={"current_page": 1, "last_page": 2, "data": [{"id": 21}, {"id": 22}]}),
                    ScriptedResponse(json={"current_page": 2, "last_page": 2, "data": [{"id": 23}]}),
                ],
                ["1", "2"],
                [21, 22, 23],
                {"limit": "100"},
            ),
            (
                "Teams",
                [ScriptedResponse(json={"current_page": 1, "last_page": 1, "data": []})],
                ["1"],
                [],
                {"limit": "100"},
            ),
            (
                "Contributors",
                [
                    ScriptedResponse(
                        json={
                            "count": 2,
                            "contributors": [
                                {"id": 31, "official_name": "dev.one", "teams": [], "merged_developers": []},
                                {"id": 32, "official_name": "dev.two", "teams": ["Core"], "merged_developers": []},
                            ],
                        }
                    )
                ],
                [None],
                [31, 32],
                {},
            ),
        ],
    )
    def test_walks_pages_and_extracts_rows(
        self,
        endpoint: str,
        script: list[ScriptedResponse],
        expected_pages: list[str | None],
        expected_ids: list[int],
        expected_query: dict[str, str],
    ) -> None:
        result = SourceDriver(WaydevSource(), WaydevSourceConfig(api_key="test-key")).run(endpoint, script)

        assert result.raised is None
        assert result.paths == [f"/v2/{endpoint.lower()}"] * len(expected_pages)
        assert result.params("page") == expected_pages
        for name, value in expected_query.items():
            assert set(result.params(name)) == {value}
        assert [row["id"] for row in result.rows] == expected_ids


class TestValidateCredentials:
    def test_ok(self) -> None:
        with scripted_network([ScriptedResponse(json=[])]) as network:
            assert validate_credentials("token") == (True, 200)
        assert network.requests_log[0].path == "/v2/metrics"
        assert network.requests_log[0].headers["authorization"] == "token"
