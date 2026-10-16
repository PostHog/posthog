import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.perigon import (
    PerigonSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.perigon.source import PerigonSource


class TestPerigonSource:
    def setup_method(self) -> None:
        self.source = PerigonSource()
        self.team_id = 123

    @pytest.mark.parametrize(
        "probe_result,schema_name,expected_valid",
        [
            ((True, 200), None, True),
            ((False, 401), None, False),
            # 403 at source-create means the key is genuine but the plan lacks some dataset.
            ((False, 403), None, True),
            # 403 while probing a specific schema means that dataset is out of plan.
            ((False, 403), "stories", False),
            ((False, None), None, False),
        ],
    )
    def test_validate_credentials_status_mapping(
        self, probe_result: tuple[bool, int | None], schema_name: str | None, expected_valid: bool
    ) -> None:
        status = probe_result[1]
        script: Script = [ScriptedResponse(status=status)] if status is not None else always(ConnectionError("boom"))
        config = PerigonSourceConfig(api_key="key")
        with scripted_network(script) as network:
            valid, error = self.source.validate_credentials(config, self.team_id, schema_name=schema_name)

        assert valid is expected_valid
        assert network.requests_log[0].path == ("/v1/stories/all" if schema_name == "stories" else "/v1/articles/all")
        assert network.requests_log[0].headers["authorization"] == "Bearer key"
        if not expected_valid:
            assert error is not None

    def test_source_for_pipeline_plumbs_endpoint_and_incremental(self) -> None:
        result = SourceDriver(self.source, PerigonSourceConfig(api_key="key")).run(
            "articles",
            [ScriptedResponse(json={"articles": []})],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-03-04T00:00:00Z",
        )

        assert result.raised is None
        assert result.paths == ["/v1/articles/all"]
        assert result.requests[0].headers["authorization"] == "Bearer key"
        assert result.params("from") == ["2026-03-04T00:00:00Z"]
        assert result.params("sortBy") == ["reverseDate"]

    def test_source_for_pipeline_drops_incremental_value_when_full_refresh(self) -> None:
        result = SourceDriver(self.source, PerigonSourceConfig(api_key="key")).run(
            "articles",
            [ScriptedResponse(json={"articles": []})],
            should_use_incremental_field=False,
            db_incremental_field_last_value="ignored",
        )

        assert result.raised is None
        assert result.paths == ["/v1/articles/all"]
        assert result.params("from") == [None]
        assert result.params("sortBy") == ["reverseAddDate"]
