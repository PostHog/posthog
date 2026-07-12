from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MaxioSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.maxio.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.maxio.maxio import MaxioResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.maxio.settings import (
    ENDPOINTS,
    TIMEZONE_SKEW_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.maxio.source import MaxioSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(**overrides: Any) -> MaxioSourceConfig:
    defaults: dict[str, Any] = {"subdomain": "acme", "api_key": "test-key", "region": "us"}
    defaults.update(overrides)
    return MaxioSourceConfig(**defaults)


def _inputs(schema_name: str, should_use_incremental_field: bool = False, **overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": schema_name,
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 123,
        "should_use_incremental_field": should_use_incremental_field,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestMaxioSource:
    def test_source_type(self) -> None:
        assert MaxioSource().source_type == ExternalDataSourceType.MAXIO

    def test_source_config_shape(self) -> None:
        config = MaxioSource().get_source_config

        assert config.category == DataWarehouseSourceCategory.PAYMENTS___BILLING
        assert config.label == "Maxio"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/maxio"
        assert config.unreleasedSource is True
        assert config.releaseStatus == ReleaseStatus.ALPHA

        fields_by_name = {f.name: f for f in config.fields}
        assert set(fields_by_name.keys()) == {"subdomain", "api_key", "region"}

        api_key_field = fields_by_name["api_key"]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.secret is True

        region_field = fields_by_name["region"]
        assert isinstance(region_field, SourceFieldSelectConfig)
        assert region_field.defaultValue == "us"
        assert {option.value for option in region_field.options} == {"us", "eu"}

    def test_connection_host_fields_cover_host_determining_fields(self) -> None:
        assert MaxioSource().connection_host_fields == ["subdomain", "region"]

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = MaxioSource().get_schemas(_config(), team_id=123)

        assert {schema.name for schema in schemas} == set(ENDPOINTS.keys())

    @pytest.mark.parametrize(
        ("schema_name", "supports_incremental", "incremental_field"),
        [
            ("customers", True, "created_at"),
            ("subscriptions", True, "updated_at"),
            ("invoices", True, "updated_at"),
            ("events", True, "id"),
            ("products", False, None),
            ("product_families", False, None),
            ("coupons", False, None),
            ("components", False, None),
            ("payment_profiles", False, None),
            ("credit_notes", False, None),
        ],
    )
    def test_get_schemas_incremental_support(
        self, schema_name: str, supports_incremental: bool, incremental_field: str | None
    ) -> None:
        schemas = {schema.name: schema for schema in MaxioSource().get_schemas(_config(), team_id=123)}
        schema = schemas[schema_name]

        assert schema.supports_incremental is supports_incremental
        assert schema.supports_append is supports_incremental
        if incremental_field is None:
            assert schema.incremental_fields == []
        else:
            assert [f["field"] for f in schema.incremental_fields] == [incremental_field]

    @pytest.mark.parametrize(
        ("schema_name", "expected_lookback"),
        [
            # Datetime windows are interpreted in the site's timezone, so those schemas
            # re-read a trailing day; the integer `since_id` cursor is exact.
            ("customers", TIMEZONE_SKEW_LOOKBACK_SECONDS),
            ("subscriptions", TIMEZONE_SKEW_LOOKBACK_SECONDS),
            ("invoices", TIMEZONE_SKEW_LOOKBACK_SECONDS),
            ("events", None),
        ],
    )
    def test_get_schemas_lookback_only_on_datetime_windows(
        self, schema_name: str, expected_lookback: int | None
    ) -> None:
        schemas = {schema.name: schema for schema in MaxioSource().get_schemas(_config(), team_id=123)}

        assert schemas[schema_name].default_incremental_lookback_seconds == expected_lookback

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = MaxioSource().get_schemas(_config(), team_id=123, names=["customers", "invoices"])

        assert {schema.name for schema in schemas} == {"customers", "invoices"}

    @pytest.mark.parametrize("subdomain", ["bad domain", "acme!", ""])
    def test_validate_credentials_rejects_invalid_subdomain_without_network(self, subdomain: str) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.maxio.source.validate_maxio_credentials"
        ) as mock_validate:
            valid, error = MaxioSource().validate_credentials(_config(subdomain=subdomain), team_id=123)

        assert valid is False
        assert error == "Maxio subdomain is incorrect"
        mock_validate.assert_not_called()

    @pytest.mark.parametrize(("result", "message"), [((True, None), None), ((False, "nope"), "nope")])
    def test_validate_credentials_delegates_to_api_probe(
        self, result: tuple[bool, str | None], message: str | None
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.maxio.source.validate_maxio_credentials",
            return_value=result,
        ) as mock_validate:
            valid, error = MaxioSource().validate_credentials(_config(), team_id=123)

        assert (valid, error) == result
        mock_validate.assert_called_once_with("test-key", "acme", "us")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = MaxioSource().get_resumable_source_manager(_inputs("customers"))

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is MaxioResumeConfig

    def test_non_retryable_errors_cover_auth_failures(self) -> None:
        errors = MaxioSource().get_non_retryable_errors()

        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)

    def test_canonical_descriptions_match_endpoint_names(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS.keys()) == set(ENDPOINTS.keys())
        assert MaxioSource().get_canonical_descriptions() is CANONICAL_DESCRIPTIONS

    def test_documented_tables_render_without_credentials(self) -> None:
        tables = MaxioSource().get_documented_tables()

        assert {table["name"] for table in tables} == set(ENDPOINTS.keys())


class TestMaxioSourceForPipeline:
    def _run(self, schema_name: str) -> Any:
        source = MaxioSource()
        inputs = _inputs(schema_name)
        manager = MagicMock(spec=ResumableSourceManager)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.maxio.source.maxio_source"
        ) as mock_source:
            mock_source.return_value.name = schema_name
            mock_source.return_value.column_hints = None
            response = source.source_for_pipeline(_config(), manager, inputs)

        return response, mock_source

    def test_plumbs_config_and_inputs_to_transport(self) -> None:
        _, mock_source = self._run("customers")

        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "test-key"
        assert kwargs["subdomain"] == "acme"
        assert kwargs["region"] == "us"
        assert kwargs["endpoint"] == "customers"
        assert kwargs["team_id"] == 123
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None

    @pytest.mark.parametrize(
        ("schema_name", "primary_keys", "partition_keys"),
        [
            ("customers", ["id"], ["created_at"]),
            ("subscriptions", ["id"], ["created_at"]),
            ("invoices", ["uid"], ["created_at"]),
            ("events", ["id"], ["created_at"]),
            ("payment_profiles", ["id"], None),
            ("credit_notes", ["uid"], None),
        ],
    )
    def test_primary_keys_and_partitioning(
        self, schema_name: str, primary_keys: list[str], partition_keys: list[str] | None
    ) -> None:
        response, _ = self._run(schema_name)

        assert response.primary_keys == primary_keys
        assert response.partition_keys == partition_keys
        if partition_keys is not None:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "week"

    def test_incremental_last_value_only_passed_when_enabled(self) -> None:
        source = MaxioSource()
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = _inputs("subscriptions", should_use_incremental_field=False)
        inputs.db_incremental_field_last_value = "2024-05-01"

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.maxio.source.maxio_source"
        ) as mock_source:
            mock_source.return_value.name = "subscriptions"
            mock_source.return_value.column_hints = None
            source.source_for_pipeline(_config(), manager, inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
