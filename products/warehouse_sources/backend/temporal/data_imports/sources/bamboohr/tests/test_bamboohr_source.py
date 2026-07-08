from typing import cast

from unittest.mock import MagicMock, patch

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.bamboohr.bamboohr import BambooHRResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.bamboohr.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.bamboohr.source import BambooHRSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BambooHRSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.bamboohr.source"


def _config() -> BambooHRSourceConfig:
    return BambooHRSourceConfig(subdomain="acme", api_key="key")


class TestBambooHRSource:
    def test_source_type(self) -> None:
        assert BambooHRSource().source_type == ExternalDataSourceType.BAMBOOHR

    def test_source_config_fields(self) -> None:
        config = BambooHRSource().get_source_config
        assert config.label == "BambooHR"
        assert not config.unreleasedSource

        fields = cast(list[SourceFieldInputConfig], config.fields)
        by_name = {f.name: f for f in fields}
        assert set(by_name) == {"subdomain", "api_key"}
        assert by_name["subdomain"].type == SourceFieldInputConfigType.TEXT
        assert by_name["subdomain"].required is True
        assert by_name["api_key"].type == SourceFieldInputConfigType.PASSWORD
        assert by_name["api_key"].secret is True

    def test_get_schemas_returns_all_endpoints_full_refresh(self) -> None:
        schemas = BambooHRSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = BambooHRSource().get_schemas(_config(), team_id=1, names=["employees"])
        assert [s.name for s in schemas] == ["employees"]

    def test_validate_credentials_delegates(self) -> None:
        with patch(f"{MODULE}.validate_bamboohr_credentials", return_value=(True, None)) as mock_validate:
            valid, message = BambooHRSource().validate_credentials(_config(), team_id=1, schema_name="employees")
        assert valid is True
        assert message is None
        mock_validate.assert_called_once_with("acme", "key", "employees")

    def test_get_non_retryable_errors_covers_auth(self) -> None:
        errors = BambooHRSource().get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)

    def test_get_resumable_source_manager(self) -> None:
        inputs = MagicMock()
        manager = BambooHRSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is BambooHRResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "employees"
        manager = MagicMock(spec=ResumableSourceManager)

        with patch(f"{MODULE}.bamboohr_source") as mock_source:
            BambooHRSource().source_for_pipeline(_config(), manager, inputs)

        mock_source.assert_called_once_with(
            subdomain="acme",
            api_key="key",
            endpoint="employees",
            logger=inputs.logger,
            resumable_source_manager=manager,
        )
