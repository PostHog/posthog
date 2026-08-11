import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import DEFAULT_RETRY
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.doit.doit import DOIT_RETRY, DoItReport
from products.warehouse_sources.backend.temporal.data_imports.sources.doit.source import DoItSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.doit import DoItSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.doit.source"

CONFIG = DoItSourceConfig(api_key="key")


class TestDoItSource:
    def setup_method(self):
        self.source = DoItSource()

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.DOIT

    @pytest.mark.parametrize("pattern", ["Report no longer exists", "Request to get report failed with status: 404"])
    def test_non_retryable_errors_includes_pattern(self, pattern):
        errors = self.source.get_non_retryable_errors()

        assert pattern in errors

    def test_get_schemas_stamps_the_report_id_so_renames_stay_resolvable(self):
        with patch(
            f"{_SOURCE_MODULE}.doit_list_reports",
            return_value=[DoItReport(id="r1", name="cost_by_product", report_name="Cost by product")],
        ):
            schemas = self.source.get_schemas(CONFIG, team_id=1)

        assert [(s.name, s.label, s.schema_metadata) for s in schemas] == [
            ("cost_by_product", "Cost by product", {"report_id": "r1"})
        ]

    def test_source_for_pipeline_fetches_the_report_id_from_schema_metadata(self):
        inputs = MagicMock(
            spec=SourceInputs,
            schema_name="cost_by_product",
            schema_metadata={"report_id": "r1"},
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            logger=MagicMock(),
        )

        with patch(f"{_SOURCE_MODULE}.doit_source") as mock_source:
            self.source.source_for_pipeline(CONFIG, inputs)

        assert mock_source.call_args.args[1:] == ("cost_by_product", "r1")

    @pytest.mark.parametrize("status_code", [520, 521, 522, 523, 524])
    def test_doit_retry_includes_cloudflare_transient_statuses(self, status_code):
        assert status_code in (DOIT_RETRY.status_forcelist or ())

    def test_doit_retry_preserves_default_statuses(self):
        assert set(DEFAULT_RETRY.status_forcelist or ()).issubset(set(DOIT_RETRY.status_forcelist or ()))
