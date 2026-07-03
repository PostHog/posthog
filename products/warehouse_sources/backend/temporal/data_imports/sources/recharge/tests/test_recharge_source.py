from unittest.mock import MagicMock, patch

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RechargeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.recharge.recharge import RechargeResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.recharge.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recharge.source import RechargeSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(api_key: str = "sk_test") -> RechargeSourceConfig:
    return RechargeSourceConfig(api_key=api_key)


class TestRechargeSourceType:
    def test_source_type(self) -> None:
        assert RechargeSource().source_type == ExternalDataSourceType.RECHARGE


class TestRechargeSourceConfigFields:
    def test_exposes_required_secret_api_key(self) -> None:
        cfg = RechargeSource().get_source_config

        assert cfg.unreleasedSource is None
        names = {f.name for f in cfg.fields}
        assert names == {"api_key"}

        api_key_field = next(f for f in cfg.fields if f.name == "api_key")
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.required is True
        assert api_key_field.secret is True
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD


class TestRechargeSourceGetSchemas:
    def test_lists_every_endpoint(self) -> None:
        schemas = RechargeSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_incremental_support_matches_settings(self) -> None:
        schemas = RechargeSource().get_schemas(_config(), team_id=1)
        for schema in schemas:
            expected = INCREMENTAL_FIELDS.get(schema.name) is not None
            assert schema.supports_incremental is expected
            assert schema.supports_append is expected

    def test_collections_is_full_refresh_only(self) -> None:
        schemas = RechargeSource().get_schemas(_config(), team_id=1)
        collections = next(s for s in schemas if s.name == "collections")
        assert collections.supports_incremental is False
        assert collections.incremental_fields == []

    def test_products_is_full_refresh_only(self) -> None:
        # The 2021-11 `/products` endpoint has no `sort_by` or `*_min` filter, so
        # it can't sync incrementally — it must be advertised as full-refresh.
        schemas = RechargeSource().get_schemas(_config(), team_id=1)
        products = next(s for s in schemas if s.name == "products")
        assert products.supports_incremental is False
        assert products.incremental_fields == []

    def test_filters_by_names(self) -> None:
        schemas = RechargeSource().get_schemas(_config(), team_id=1, names=["customers", "orders"])
        assert {s.name for s in schemas} == {"customers", "orders"}


class TestRechargeSourceValidateCredentials:
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.recharge.source.validate_recharge_credentials"
    )
    def test_delegates_to_client(self, mock_validate: MagicMock) -> None:
        mock_validate.return_value = (True, None)
        ok, error = RechargeSource().validate_credentials(_config("tok"), team_id=1)
        assert ok is True
        assert error is None
        mock_validate.assert_called_once_with("tok")


class TestRechargeSourceNonRetryableErrors:
    def test_includes_auth_errors(self) -> None:
        errors = RechargeSource().get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)


class TestRechargeSourceResumableManager:
    def test_returns_manager_bound_to_resume_config(self) -> None:
        manager = RechargeSource().get_resumable_source_manager(MagicMock())
        assert manager._data_class is RechargeResumeConfig


class TestRechargeSourcePipelinePlumbing:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.recharge.source.recharge_source")
    def test_passes_through_inputs(self, mock_recharge_source: MagicMock) -> None:
        sentinel = object()
        mock_recharge_source.return_value = sentinel

        inputs = MagicMock()
        inputs.schema_name = "customers"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00"
        inputs.incremental_field = "updated_at"

        manager = MagicMock()
        result = RechargeSource().source_for_pipeline(_config("tok"), manager, inputs)

        assert result is sentinel
        kwargs = mock_recharge_source.call_args.kwargs
        assert kwargs["api_key"] == "tok"
        assert kwargs["endpoint"] == "customers"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00"
        assert kwargs["incremental_field"] == "updated_at"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.recharge.source.recharge_source")
    def test_clears_last_value_when_not_incremental(self, mock_recharge_source: MagicMock) -> None:
        inputs = MagicMock()
        inputs.schema_name = "collections"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00"
        inputs.incremental_field = None

        RechargeSource().source_for_pipeline(_config("tok"), MagicMock(), inputs)

        kwargs = mock_recharge_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None
