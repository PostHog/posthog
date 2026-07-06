from typing import Optional

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.awin import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.awin.awin import AwinResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.awin.source import AwinSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AwinSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _inputs(schema_name: str = "transactions", **overrides: object) -> MagicMock:
    inputs = MagicMock()
    inputs.schema_name = schema_name
    inputs.should_use_incremental_field = overrides.get("should_use_incremental_field", True)
    inputs.db_incremental_field_last_value = overrides.get("db_incremental_field_last_value", "2024-01-01T00:00:00")
    inputs.incremental_field = overrides.get("incremental_field", "transactionDate")
    return inputs


class TestAwinSourceClass:
    def test_source_type(self) -> None:
        assert AwinSource().source_type == ExternalDataSourceType.AWIN

    def test_get_source_config_fields(self) -> None:
        config = AwinSource().get_source_config
        assert config.name.value == "Awin"
        assert len(config.fields) == 1
        field = config.fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_token"
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True
        assert field.secret is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/awin"

    def test_lists_tables_without_credentials(self) -> None:
        assert AwinSource.lists_tables_without_credentials is True

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = AwinSource().get_schemas(AwinSourceConfig(api_token="x"), team_id=1)
        names = {s.name for s in schemas}
        assert names == {"accounts", "programmes", "transactions", "reports_advertiser"}

    @parameterized.expand(
        [
            ("transactions", True),
            ("accounts", False),
            ("programmes", False),
            ("reports_advertiser", False),
        ]
    )
    def test_supports_incremental_per_endpoint(self, endpoint: str, expected: bool) -> None:
        schemas = AwinSource().get_schemas(AwinSourceConfig(api_token="x"), team_id=1, names=[endpoint])
        assert len(schemas) == 1
        assert schemas[0].supports_incremental is expected

    def test_transactions_advertises_both_date_fields(self) -> None:
        schemas = AwinSource().get_schemas(AwinSourceConfig(api_token="x"), team_id=1, names=["transactions"])
        fields = {f["field"] for f in schemas[0].incremental_fields}
        assert fields == {"transactionDate", "validationDate"}

    def test_documented_tables_render_without_credentials(self) -> None:
        tables = AwinSource().get_documented_tables()
        names = {t["name"] for t in tables}
        assert names == {"accounts", "programmes", "transactions", "reports_advertiser"}

    @parameterized.expand([("valid", True, True, None), ("invalid", False, False, "Invalid Awin API token")])
    def test_validate_credentials(self, _name: str, api_result: bool, ok: bool, err: Optional[str]) -> None:
        with patch.object(source_module, "validate_awin_credentials", return_value=api_result):
            result = AwinSource().validate_credentials(AwinSourceConfig(api_token="x"), team_id=1)
        assert result == (ok, err)

    def test_get_non_retryable_errors_cover_auth(self) -> None:
        errors = AwinSource().get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)

    def test_get_resumable_source_manager_bound_to_data_class(self) -> None:
        manager = AwinSource().get_resumable_source_manager(_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is AwinResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        manager = MagicMock()
        inputs = _inputs(schema_name="transactions")
        with patch.object(source_module, "awin_source") as mock_awin_source:
            AwinSource().source_for_pipeline(AwinSourceConfig(api_token="tok"), manager, inputs)

        mock_awin_source.assert_called_once()
        kwargs = mock_awin_source.call_args.kwargs
        assert kwargs["api_token"] == "tok"
        assert kwargs["endpoint"] == "transactions"
        assert kwargs["incremental_field"] == "transactionDate"
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00"

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self) -> None:
        manager = MagicMock()
        inputs = _inputs(should_use_incremental_field=False)
        with patch.object(source_module, "awin_source") as mock_awin_source:
            AwinSource().source_for_pipeline(AwinSourceConfig(api_token="tok"), manager, inputs)

        assert mock_awin_source.call_args.kwargs["db_incremental_field_last_value"] is None
