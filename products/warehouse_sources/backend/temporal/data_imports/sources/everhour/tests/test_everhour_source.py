import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.everhour.everhour import EverhourResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.everhour.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.everhour.source import EverhourSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import EverhourSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.everhour.source"


class TestEverhourSource:
    def setup_method(self) -> None:
        self.source = EverhourSource()
        self.team_id = 123
        self.config = EverhourSourceConfig(api_key="ev_abc")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.EVERHOUR

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Everhour"
        assert config.label == "Everhour"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/everhour.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/everhour"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert key_field.type == SourceFieldInputConfigType.PASSWORD
        assert key_field.secret is True
        assert key_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.everhour.com/clients?limit=100",
            "403 Client Error: Forbidden for url: https://api.everhour.com/time-records?from=2026-01-01",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.everhour.com/projects",
            "HTTPSConnectionPool(host='api.everhour.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient(self, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_covers_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_only_time_records_is_incremental(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["time_records"].supports_incremental is True
        assert schemas["time_records"].supports_append is True
        assert [f["field"] for f in schemas["time_records"].incremental_fields] == ["date"]

        for name in ("clients", "projects", "users", "tasks"):
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["time_records"])
        assert len(schemas) == 1
        assert schemas[0].name == "time_records"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas does no I/O, so the static catalog can render in public docs.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Everhour API key"),
        ],
    )
    @mock.patch(f"{SOURCE_MODULE}.validate_everhour_credentials")
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: bool,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is EverhourResumeConfig

    @mock.patch(f"{SOURCE_MODULE}.everhour_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_everhour_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "time_records"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_everhour_source.assert_called_once()
        kwargs = mock_everhour_source.call_args.kwargs
        assert kwargs["api_key"] == "ev_abc"
        assert kwargs["endpoint"] == "time_records"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01"

    @mock.patch(f"{SOURCE_MODULE}.everhour_source")
    def test_source_for_pipeline_omits_last_value_when_not_incremental(
        self, mock_everhour_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "clients"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "should-be-ignored"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_everhour_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None
