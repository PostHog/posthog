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
    get_resource,
    validate_credentials,
)


class TestGetResource:
    def test_unknown_endpoint_raises(self) -> None:
        with pytest.raises(KeyError):
            get_resource("NotAnEndpoint")


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


class TestValidateCredentials:
    def test_ok(self) -> None:
        with scripted_network([ScriptedResponse(json=[])]) as network:
            assert validate_credentials("token") == (True, 200)
        assert network.requests_log[0].path == "/v2/metrics"
        assert network.requests_log[0].headers["authorization"] == "token"
