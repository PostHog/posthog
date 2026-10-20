from typing import Any, cast

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.cloudability import (
    CloudabilityResumeConfig,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.source import CloudabilitySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudability import (
    CloudabilitySourceConfig,
)


class TestGetResource:
    def test_costs_date_window_is_start_before_end(self) -> None:
        endpoint = cast(Endpoint, get_resource("Costs", view_id=None)["endpoint"])
        params = cast(dict[str, Any], endpoint["params"])
        assert params["start_date"] < params["end_date"]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [
            (200, True),
        ],
    )
    def test_validate_credentials_checks_status_code(self, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("api-key", "us") is expected

        assert network.requests_log[0].path == "/v3/views"


class TestCloudabilitySourceResumeBehavior:
    """End-to-end resume behaviour of ``CloudabilitySource`` via ``source_for_pipeline``."""

    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(CloudabilitySource(), CloudabilitySourceConfig(api_key="test-key", region="us"))

    def test_fresh_run_saves_token_after_non_terminal_page(self) -> None:
        result = self._driver().run(
            "Costs",
            [
                ScriptedResponse(json={"results": [{"vendor": "AWS"}], "pagination": {"next": "tok-1"}}),
                ScriptedResponse(json={"results": [{"vendor": "GCP"}]}),
            ],
        )

        assert result.raised is None
        assert result.params("token") == [None, "tok-1"]
        assert result.rows == [{"vendor": "AWS"}, {"vendor": "GCP"}]
        assert result.saved_states == [CloudabilityResumeConfig(cursor="tok-1")]
        assert result.committed_states == [CloudabilityResumeConfig(cursor="tok-1")]

    def test_resume_seeds_paginator_with_saved_token(self) -> None:
        result = self._driver().run(
            "Costs",
            [ScriptedResponse(json={"results": [{"vendor": "Azure"}]})],
            resume_state=CloudabilityResumeConfig(cursor="tok-resumed"),
        )

        assert result.raised is None
        assert result.params("token") == ["tok-resumed"]
        assert result.rows == [{"vendor": "Azure"}]

    @pytest.mark.parametrize(
        ("endpoint", "response_body"),
        [
            ("Views", [{"id": "v1", "title": "Default"}]),
            ("BusinessMappingDimensions", [{"name": "team", "index": 1}]),
            ("BusinessMappingMetrics", [{"name": "allocated_cost", "index": 1}]),
            ("Anomalies", [{"id": "a1", "vendor": "AWS"}]),
        ],
    )
    def test_single_page_endpoints_do_not_save_resume_state(
        self, endpoint: str, response_body: list[dict[str, Any]]
    ) -> None:
        result = self._driver().run(endpoint, [ScriptedResponse(json=response_body)])

        assert result.raised is None
        assert result.rows == response_body
        assert result.saved_states == []
