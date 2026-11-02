import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.greenhouse import (
    GreenhouseSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.source import GreenhouseSource

INCREMENTAL_ENDPOINTS = {
    "candidates",
    "applications",
    "jobs",
    "job_posts",
    "offers",
    "scorecards",
    "scheduled_interviews",
    "users",
}
FULL_REFRESH_ENDPOINTS = {"departments", "offices", "sources", "rejection_reasons", "close_reasons"}


class TestGreenhouseSource:
    def setup_method(self) -> None:
        self.source = GreenhouseSource()
        self.team_id = 123
        self.config = GreenhouseSourceConfig(api_key="test_api_key", client_id="cid", client_secret="csecret")

    def test_validate_credentials_at_source_create_accepts_forbidden(self) -> None:
        with scripted_network(
            [ScriptedResponse(json={"access_token": "test_token", "expires_in": 3600}), ScriptedResponse(status=403)]
        ) as network:
            is_valid, error = self.source.validate_credentials(self.config, self.team_id, schema_name=None)

        assert is_valid is True
        assert error is None
        assert [request.path for request in network.requests_log] == ["/token", "/v3/candidates"]
        assert network.requests_log[-1].param("per_page") == "1"

    @pytest.mark.parametrize(
        "pinned_version, expected_version, expected_path",
        [
            (None, "v3", "/interviews"),
            ("v3", "v3", "/interviews"),
            # A v1-pinned source must be probed on v1, not on the (newer) default.
            ("v1", "v1", "/scheduled_interviews"),
        ],
    )
    def test_validate_credentials_probes_the_pinned_version(
        self,
        pinned_version: str | None,
        expected_version: str,
        expected_path: str,
    ) -> None:
        script = (
            [ScriptedResponse(json={"access_token": "test_token", "expires_in": 3600})]
            if expected_version == "v3"
            else []
        )
        script.append(ScriptedResponse(status=200))
        with scripted_network(script) as network:
            is_valid, error = self.source.validate_credentials(
                self.config, self.team_id, schema_name="scheduled_interviews", api_version=pinned_version
            )

        assert is_valid is True
        assert error is None
        assert network.requests_log[-1].path == f"/{expected_version}{expected_path}"
        assert network.requests_log[-1].param("per_page") == "1"

    def test_validate_credentials_rejects_v3_only_schema_on_v1(self) -> None:
        with scripted_network([]) as network:
            is_valid, error = self.source.validate_credentials(
                self.config, self.team_id, schema_name="openings", api_version="v1"
            )

        assert is_valid is False
        assert error is not None and "Harvest v3" in error
        assert network.requests_log == []

    def test_source_for_pipeline_passes_incremental_inputs(self) -> None:
        result = SourceDriver(self.source, self.config).run(
            "candidates",
            [ScriptedResponse(json=[{"id": 1}])],
            api_version="v1",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00.000Z",
            incremental_field="updated_at",
        )

        assert result.raised is None
        assert result.requests[0].path == "/v1/candidates"
        assert result.requests[0].headers["authorization"] == "Basic dGVzdF9hcGlfa2V5Og=="
        assert result.requests[0].param("updated_after") == "2026-01-01T00:00:00.000Z"

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self) -> None:
        result = SourceDriver(self.source, self.config).run(
            "departments",
            [ScriptedResponse(json=[{"id": 1}])],
            api_version="v1",
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00.000Z",
        )

        assert result.raised is None
        assert result.requests[0].path == "/v1/departments"
        assert result.queries == [{"per_page": ("500",)}]
