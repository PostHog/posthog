from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gorgias import (
    GorgiasSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gorgias.source import GorgiasSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.gorgias.source"


def _config() -> GorgiasSourceConfig:
    return GorgiasSourceConfig(gorgias_domain="acme", email="you@acme.com", api_key="key")


def _inputs(schema_name: str = "tickets") -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestGorgiasSource:
    def test_get_schemas_filters_by_names(self) -> None:
        schemas = GorgiasSource().get_schemas(_config(), team_id=1, names=["tickets", "customers"])
        assert {s.name for s in schemas} == {"tickets", "customers"}

    def test_source_for_pipeline_plumbs_schema_name(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        response = GorgiasSource().source_for_pipeline(_config(), manager, _inputs(schema_name="customers"))
        assert response.name == "customers"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
