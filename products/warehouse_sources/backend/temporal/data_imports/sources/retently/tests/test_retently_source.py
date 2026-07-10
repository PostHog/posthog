import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RetentlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.retently import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.retently.retently import RetentlyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.retently.source import RetentlySource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestRetentlySourceConfig:
    def setup_method(self) -> None:
        self.source = RetentlySource()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.RETENTLY

    def test_config_has_api_key_password_field(self) -> None:
        config = self.source.get_source_config
        fields = {f.name: f for f in config.fields}
        assert set(fields) == {"api_key"}
        api_key_field = fields["api_key"]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.required is True
        assert api_key_field.secret is True

    def test_config_is_unreleased_alpha(self) -> None:
        config = self.source.get_source_config
        # Deliberately shipped hidden: the source lands unreleased until it has been verified
        # against a live Retently account.
        assert config.unreleasedSource is True
        assert config.releaseStatus == "alpha"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/retently"

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — required for the public-docs table list to render.
        assert self.source.lists_tables_without_credentials is True


class TestGetSchemas:
    def setup_method(self) -> None:
        self.schemas = {s.name: s for s in RetentlySource().get_schemas(MagicMock(), team_id=1)}

    def test_all_expected_tables_present(self) -> None:
        assert set(self.schemas) == {
            "customers",
            "companies",
            "feedback",
            "outbox",
            "campaigns",
            "templates",
            "reports",
        }

    def test_feedback_is_the_only_incremental_table(self) -> None:
        assert self.schemas["feedback"].supports_incremental is True
        assert [f["field"] for f in self.schemas["feedback"].incremental_fields] == ["createdDate"]
        for name, schema in self.schemas.items():
            if name != "feedback":
                assert schema.supports_incremental is False, name
                assert schema.incremental_fields == [], name

    def test_names_filter(self) -> None:
        filtered = RetentlySource().get_schemas(MagicMock(), team_id=1, names=["feedback"])
        assert [s.name for s in filtered] == ["feedback"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", (True, None)),
            ("invalid", (False, "Invalid Retently API key")),
            ("inconclusive", (False, "Could not connect to Retently: boom")),
        ]
    )
    def test_validate_credentials_passes_probe_result_through(self, _name: str, probe_result: tuple) -> None:
        config = RetentlySourceConfig(api_key="key")
        with patch.object(source_module, "validate_retently_credentials", return_value=probe_result):
            assert RetentlySource().validate_credentials(config, team_id=1) == probe_result


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://app.retently.com/api/v2/feedback"),
            ("forbidden", "403 Client Error: Forbidden for url: https://app.retently.com/api/v2/customers?page=1"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = RetentlySource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://app.retently.com/api/v2/feedback",
            ),
            ("read_timeout", "HTTPSConnectionPool(host='app.retently.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = RetentlySource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestResumablePlumbing:
    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = RetentlySource().get_resumable_source_manager(MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is RetentlyResumeConfig

    def test_source_for_pipeline_passes_incremental_inputs(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "feedback"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        config = RetentlySourceConfig(api_key="key")
        manager = MagicMock()

        with patch.object(source_module, "retently_source") as mock_source:
            RetentlySource().source_for_pipeline(config, manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == "feedback"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "customers"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "ignored"
        config = RetentlySourceConfig(api_key="key")

        with patch.object(source_module, "retently_source") as mock_source:
            RetentlySource().source_for_pipeline(config, MagicMock(), inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "not_a_real_table"
        with pytest.raises(ValueError):
            RetentlySource().source_for_pipeline(RetentlySourceConfig(api_key="key"), MagicMock(), inputs)
