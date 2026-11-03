from products.warehouse_sources.sources.huntr._config import HuntrSourceConfig
from products.warehouse_sources.sources.huntr.huntr import HuntrResumeConfig
from products.warehouse_sources.sources.huntr.source import HuntrSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver


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
