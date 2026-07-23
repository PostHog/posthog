from unittest.mock import MagicMock, patch

import requests

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.veeqo import VeeqoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.veeqo.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.veeqo.source import VeeqoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.veeqo.veeqo import VeeqoResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(api_key: str = "test-key") -> VeeqoSourceConfig:
    return VeeqoSourceConfig(api_key=api_key)


class TestVeeqoSourceType:
    def test_source_type(self) -> None:
        assert VeeqoSource().source_type == ExternalDataSourceType.VEEQO


class TestVeeqoSourceConfigFields:
    def test_exposes_required_secret_api_key(self) -> None:
        cfg = VeeqoSource().get_source_config

        assert cfg.unreleasedSource is None
        names = {f.name for f in cfg.fields}
        assert names == {"api_key"}

        api_key_field = next(f for f in cfg.fields if f.name == "api_key")
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.required is True
        assert api_key_field.secret is True
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD


class TestVeeqoSourceGetSchemas:
    def test_lists_every_endpoint(self) -> None:
        schemas = VeeqoSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_incremental_support_matches_settings(self) -> None:
        schemas = VeeqoSource().get_schemas(_config(), team_id=1)
        for schema in schemas:
            expected = schema.name in INCREMENTAL_FIELDS
            assert schema.supports_incremental is expected
            assert schema.supports_append is expected

    def test_filters_by_names(self) -> None:
        schemas = VeeqoSource().get_schemas(_config(), team_id=1, names=["orders", "products"])
        assert {s.name for s in schemas} == {"orders", "products"}


class TestVeeqoSourceValidateCredentials:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.veeqo.source.validate_veeqo_credentials")
    def test_delegates_to_client(self, mock_validate: MagicMock) -> None:
        mock_validate.return_value = (True, None)
        ok, error = VeeqoSource().validate_credentials(_config("key"), team_id=1)
        assert ok is True
        assert error is None
        mock_validate.assert_called_once_with("key")


class TestVeeqoSourceNonRetryableErrors:
    def test_http_error_message_format_matches_patterns(self) -> None:
        # The patterns must match the exact message `raise_for_status` produces,
        # otherwise auth failures retry forever instead of failing permanently.
        for status, reason in ((401, "Unauthorized"), (403, "Forbidden")):
            response = requests.Response()
            response.status_code = status
            response.reason = reason
            response.url = "https://api.veeqo.com/orders?page=1"

            try:
                response.raise_for_status()
                raise AssertionError("raise_for_status did not raise")
            except requests.HTTPError as e:
                error_msg = str(e)

            patterns = VeeqoSource().get_non_retryable_errors()
            assert any(pattern in error_msg for pattern in patterns), (
                f"HTTPError message '{error_msg}' did not match any non-retryable pattern"
            )


class TestVeeqoSourceResumableManager:
    def test_returns_manager_bound_to_resume_config(self) -> None:
        manager = VeeqoSource().get_resumable_source_manager(MagicMock())
        assert manager._data_class is VeeqoResumeConfig


class TestVeeqoSourcePipelinePlumbing:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.veeqo.source.veeqo_source")
    def test_passes_through_inputs(self, mock_veeqo_source: MagicMock) -> None:
        sentinel = object()
        mock_veeqo_source.return_value = sentinel

        inputs = MagicMock()
        inputs.schema_name = "orders"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01 00:00:00"
        inputs.incremental_field = "updated_at"

        manager = MagicMock()
        result = VeeqoSource().source_for_pipeline(_config("key"), manager, inputs)

        assert result is sentinel
        kwargs = mock_veeqo_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == "orders"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01 00:00:00"
        assert kwargs["incremental_field"] == "updated_at"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.veeqo.source.veeqo_source")
    def test_clears_last_value_when_not_incremental(self, mock_veeqo_source: MagicMock) -> None:
        inputs = MagicMock()
        inputs.schema_name = "customers"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01 00:00:00"
        inputs.incremental_field = None

        VeeqoSource().source_for_pipeline(_config("key"), MagicMock(), inputs)

        kwargs = mock_veeqo_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None
