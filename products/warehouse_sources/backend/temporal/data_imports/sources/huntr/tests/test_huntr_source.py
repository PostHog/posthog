from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.huntr import HuntrSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.huntr.huntr import HuntrResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.huntr.source import HuntrSource


class TestHuntrSource:
    def setup_method(self) -> None:
        self.source = HuntrSource()
        self.config = HuntrSourceConfig(access_token="huntr-token")

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        result = SourceDriver(self.source, self.config).run(
            "jobs",
            [ScriptedResponse(json={"data": [{"id": "job-1"}]})],
            resume_state=HuntrResumeConfig(next="previous"),
        )

        assert result.raised is None
        assert result.rows == [{"id": "job-1"}]
        assert result.paths == ["/org/jobs"]
        assert result.params("next") == ["previous"]
        assert result.requests[0].headers["authorization"] == "Bearer huntr-token"

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        result = SourceDriver(self.source, self.config).run("not_a_table", [])

        assert isinstance(result.raised, ValueError)
        assert str(result.raised) == "Unknown Huntr schema 'not_a_table'"
