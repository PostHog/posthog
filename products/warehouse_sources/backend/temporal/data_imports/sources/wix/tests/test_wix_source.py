import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.wix import WixSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.wix.source import WixSource

_SOURCE = "products.warehouse_sources.backend.temporal.data_imports.sources.wix.source"


def _config() -> WixSourceConfig:
    return WixSourceConfig(api_key="key", site_id="site")


class TestWixSource:
    def test_an_unknown_schema_fails_before_any_request_goes_out(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_wix_table"

        with pytest.raises(ValueError, match="Unknown Wix endpoint"):
            WixSource().source_for_pipeline(_config(), mock.MagicMock(), inputs)

    def test_the_users_chosen_incremental_field_reaches_the_transport(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "updatedDate"
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        with mock.patch(f"{_SOURCE}.wix_source") as wix_source:
            WixSource().source_for_pipeline(_config(), mock.MagicMock(), inputs)

        assert wix_source.call_args.kwargs["incremental_field"] == "updatedDate"
        assert wix_source.call_args.kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    def test_a_full_refresh_run_passes_no_watermark(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.should_use_incremental_field = False
        inputs.incremental_field = "updatedDate"
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        with mock.patch(f"{_SOURCE}.wix_source") as wix_source:
            WixSource().source_for_pipeline(_config(), mock.MagicMock(), inputs)

        assert wix_source.call_args.kwargs["incremental_field"] is None
        assert wix_source.call_args.kwargs["db_incremental_field_last_value"] is None
