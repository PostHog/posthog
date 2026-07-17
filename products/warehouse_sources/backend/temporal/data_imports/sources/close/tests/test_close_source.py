import pytest
from unittest import mock
from unittest.mock import MagicMock

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.close.close import CloseResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.close.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.close.source import CloseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CloseSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

INCREMENTAL_ENDPOINTS = {"Opportunities", "Activities", "Tasks"}


class TestCloseSource:
    def setup_method(self) -> None:
        self.source = CloseSource()
        self.team_id = 123
        self.config = CloseSourceConfig(api_key="api_test")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.CLOSE

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Close"
        assert config.label == "Close"
        assert config.releaseStatus == "alpha"
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/close.png"
        assert len(config.fields) == 1

        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

    def test_get_schemas_lists_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", sorted(ENDPOINTS))
    def test_get_schemas_incremental_flags(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        expected_incremental = endpoint in INCREMENTAL_ENDPOINTS
        assert schema.supports_incremental is expected_incremental
        assert schema.supports_append is expected_incremental
        if expected_incremental:
            assert len(schema.incremental_fields) >= 1
        else:
            assert schema.incremental_fields == []

    def test_opportunities_advertises_both_cursors(self) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == "Opportunities")
        fields = {f["field"] for f in schema.incremental_fields}
        assert fields == {"date_created", "date_updated"}

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Leads"])
        assert len(schemas) == 1
        assert schemas[0].name == "Leads"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid", "expected_message"),
        [
            (True, True, None),
            (False, False, "Invalid Close API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.close.source.validate_close_credentials"
    )
    def test_validate_credentials(
        self, mock_validate: MagicMock, mock_return: bool, expected_valid: bool, expected_message: str | None
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("api_test")

    def test_validate_credentials_empty_key(self) -> None:
        is_valid, error_message = self.source.validate_credentials(CloseSourceConfig(api_key=""), self.team_id)
        assert is_valid is False
        assert error_message == "Close API key is required"

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error: Unauthorized for url",
            "403 Client Error: Forbidden for url",
        ],
    )
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_resumable_source_manager_binds_data_class(self) -> None:
        inputs = MagicMock()
        inputs.logger = MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CloseResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.close.source.close_source")
    def test_source_for_pipeline_plumbs_inputs(self, mock_close_source: MagicMock) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = MagicMock()
        inputs.schema_name = "Opportunities"
        inputs.team_id = 7
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "date_updated"
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00+00:00"

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_close_source.assert_called_once_with(
            api_key="api_test",
            endpoint="Opportunities",
            team_id=7,
            job_id="job-1",
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            incremental_field="date_updated",
            db_incremental_field_last_value="2024-01-01T00:00:00+00:00",
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.close.source.close_source")
    def test_source_for_pipeline_drops_last_value_when_not_incremental(self, mock_close_source: MagicMock) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = MagicMock()
        inputs.schema_name = "Leads"
        inputs.team_id = 7
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = False
        inputs.incremental_field = None
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00+00:00"

        self.source.source_for_pipeline(self.config, manager, inputs)

        assert mock_close_source.call_args.kwargs["db_incremental_field_last_value"] is None
