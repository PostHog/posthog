from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.easypromos.settings import EASYPROMOS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.easypromos.source import EasypromosSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.easypromos import (
    EasypromosSourceConfig,
)


class TestSourceConfig:
    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog, so the public docs can render the table list.
        assert EasypromosSource.lists_tables_without_credentials is True


class TestSourceForPipeline:
    def test_plumbs_endpoint_and_keys(self) -> None:
        config = EasypromosSourceConfig(access_token="tok")
        result = SourceDriver(EasypromosSource(), config).run(
            "participations", [ScriptedResponse(json={"items": [], "paging": {"next_cursor": None, "items_page": 100}})]
        )
        assert result.raised is None
        assert result.response is not None
        assert result.response.name == "participations"
        assert result.response.primary_keys == EASYPROMOS_ENDPOINTS["participations"].primary_keys
