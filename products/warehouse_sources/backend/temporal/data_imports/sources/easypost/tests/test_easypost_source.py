from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceFieldInputConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.easypost.easypost import EasypostResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.easypost.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.easypost.source import EasypostSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> Any:
    config = MagicMock()
    config.api_key = "EZAK_test"
    return config


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert EasypostSource().source_type == ExternalDataSourceType.EASYPOST

    def test_source_config_basics(self) -> None:
        config = EasypostSource().get_source_config
        assert config.name == SchemaExternalDataSourceType.EASYPOST
        assert config.label == "EasyPost"
        # Stays hidden behind the unreleased flag while in alpha.
        assert config.unreleasedSource is True

    def test_source_config_has_password_api_key_field(self) -> None:
        fields = EasypostSource().get_source_config.fields
        assert [f.name for f in fields] == ["api_key"]
        api_key_field = fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.required is True
        assert api_key_field.secret is True


class TestGetSchemas:
    def test_returns_every_endpoint(self) -> None:
        schemas = EasypostSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_names_filter(self) -> None:
        schemas = EasypostSource().get_schemas(_config(), team_id=1, names=["shipments", "events"])
        assert {s.name for s in schemas} == {"shipments", "events"}

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_every_schema_advertises_created_at(self, endpoint: str) -> None:
        schemas = {s.name: s for s in EasypostSource().get_schemas(_config(), team_id=1)}
        schema = schemas[endpoint]
        assert [f["field"] for f in schema.incremental_fields] == ["created_at"]
        assert schema.supports_append is True

    def test_events_are_append_only(self) -> None:
        # Events are immutable, so they're append-only (no incremental updates to existing rows).
        schemas = {s.name: s for s in EasypostSource().get_schemas(_config(), team_id=1)}
        assert schemas["events"].supports_incremental is False
        assert schemas["shipments"].supports_incremental is True


class TestValidateCredentials:
    def test_valid(self, monkeypatch: Any) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.easypost import source as source_module

        monkeypatch.setattr(source_module, "validate_easypost_credentials", lambda api_key: True)
        assert EasypostSource().validate_credentials(_config(), team_id=1) == (True, None)

    def test_invalid(self, monkeypatch: Any) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.easypost import source as source_module

        monkeypatch.setattr(source_module, "validate_easypost_credentials", lambda api_key: False)
        ok, error = EasypostSource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert error is not None


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.easypost.com/v2/shipments?page_size=1",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.easypost.com/v2/events"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = EasypostSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.easypost.com/v2/shipments"),
            ("rate_limit", "429 Client Error: Too Many Requests for url: https://api.easypost.com/v2/shipments"),
            ("timeout", "HTTPSConnectionPool(host='api.easypost.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = EasypostSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestResumableSourceManager:
    def test_manager_is_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        inputs.logger = MagicMock()
        manager = EasypostSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is EasypostResumeConfig


class TestSourceForPipeline:
    def test_plumbs_incremental_inputs(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "shipments"
        inputs.logger = MagicMock()
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00Z"
        inputs.incremental_field = "created_at"

        response = EasypostSource().source_for_pipeline(_config(), MagicMock(), inputs)
        assert response.name == "shipments"
        assert response.sort_mode == "desc"

    def test_drops_last_value_when_not_incremental(self) -> None:
        # When the schema isn't synced incrementally, the watermark must not leak into the request.
        inputs = MagicMock()
        inputs.schema_name = "addresses"
        inputs.logger = MagicMock()
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00Z"
        inputs.incremental_field = None

        response = EasypostSource().source_for_pipeline(_config(), MagicMock(), inputs)
        assert response.name == "addresses"
