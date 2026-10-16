from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gorgias import (
    GorgiasSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gorgias.source import GorgiasSource


def _config() -> GorgiasSourceConfig:
    return GorgiasSourceConfig(gorgias_domain="acme", email="you@acme.com", api_key="key")


class TestGorgiasSource:
    def test_get_schemas_filters_by_names(self) -> None:
        schemas = GorgiasSource().get_schemas(_config(), team_id=1, names=["tickets", "customers"])
        assert {s.name for s in schemas} == {"tickets", "customers"}

    def test_source_for_pipeline_plumbs_schema_name(self) -> None:
        result = SourceDriver(GorgiasSource(), _config()).run(
            "customers", [ScriptedResponse(json={"data": [], "meta": {"next_cursor": None}})]
        )
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == "customers"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
