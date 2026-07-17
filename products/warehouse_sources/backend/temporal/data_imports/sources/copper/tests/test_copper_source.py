import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.copper.copper import CopperResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.copper.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.copper.source import CopperSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> MagicMock:
    config = MagicMock()
    config.api_key = "key"
    config.user_email = "user@example.com"
    return config


class TestCopperSource:
    def setup_method(self):
        self.source = CopperSource()

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.COPPER

    def test_source_config_fields(self):
        config = self.source.get_source_config

        assert config.label == "Copper"
        assert config.unreleasedSource is None
        assert config.releaseStatus == "alpha"

        fields = {f.name: f for f in config.fields if isinstance(f, SourceFieldInputConfig)}
        assert set(fields) == {"api_key", "user_email"}
        assert fields["api_key"].secret is True
        assert fields["api_key"].type.value == "password"
        assert fields["user_email"].secret is False
        assert fields["user_email"].type.value == "email"

    @pytest.mark.parametrize(
        "pattern",
        ["401 Client Error", "403 Client Error"],
    )
    def test_non_retryable_errors(self, pattern):
        assert pattern in self.source.get_non_retryable_errors()

    def test_get_schemas_lists_all_endpoints(self):
        schemas = self.source.get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint,expected_incremental",
        [
            ("people", True),
            ("companies", True),
            ("opportunities", True),
            ("users", False),
            ("pipelines", False),
            ("loss_reasons", False),
        ],
    )
    def test_get_schemas_incremental_support(self, endpoint, expected_incremental):
        schemas = {s.name: s for s in self.source.get_schemas(_config(), team_id=1)}
        schema = schemas[endpoint]
        assert schema.supports_incremental is expected_incremental
        assert schema.supports_append is expected_incremental
        if expected_incremental:
            assert {f["field"] for f in schema.incremental_fields} == {"date_modified", "date_created"}
        else:
            assert schema.incremental_fields == []

    def test_get_schemas_filters_by_names(self):
        schemas = self.source.get_schemas(_config(), team_id=1, names=["people"])
        assert [s.name for s in schemas] == ["people"]

    @pytest.mark.parametrize(
        "returned,expected_valid",
        [((True, None), True), ((False, "bad"), False)],
    )
    def test_validate_credentials_delegates(self, returned, expected_valid):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.copper.source.validate_copper_credentials",
            return_value=returned,
        ) as mock_validate:
            valid, _error = self.source.validate_credentials(_config(), team_id=1)

        assert valid is expected_valid
        mock_validate.assert_called_once_with("key", "user@example.com")

    def test_get_resumable_source_manager(self):
        inputs = MagicMock()
        inputs.logger = MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CopperResumeConfig

    def test_source_for_pipeline_threads_inputs(self):
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = MagicMock()
        inputs.schema_name = "people"
        inputs.logger = MagicMock()
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000
        inputs.incremental_field = "date_modified"

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.copper.source.copper_source"
        ) as mock_source:
            self.source.source_for_pipeline(_config(), manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["endpoint"] == "people"
        assert kwargs["api_key"] == "key"
        assert kwargs["user_email"] == "user@example.com"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000
        assert kwargs["incremental_field"] == "date_modified"

    def test_source_for_pipeline_full_refresh_drops_incremental(self):
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = MagicMock()
        inputs.schema_name = "people"
        inputs.logger = MagicMock()
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1700000000
        inputs.incremental_field = "date_modified"

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.copper.source.copper_source"
        ) as mock_source:
            self.source.source_for_pipeline(_config(), manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None
        assert kwargs["incremental_field"] is None
