from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.ding_connect import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.ding_connect.ding_connect import (
    DingConnectResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ding_connect.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.ding_connect.source import DingConnectSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert DingConnectSource().source_type == ExternalDataSourceType.DINGCONNECT

    def test_get_source_config_basics(self) -> None:
        config = DingConnectSource().get_source_config
        assert config.label == "DingConnect"
        assert config.category == DataWarehouseSourceCategory.PAYMENTS___BILLING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/ding-connect"

    def test_source_config_has_single_required_secret_api_key(self) -> None:
        fields = DingConnectSource().get_source_config.fields
        assert len(fields) == 1
        api_key_field = fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.required is True
        assert api_key_field.secret is True


class TestGetSchemas:
    def test_returns_every_endpoint(self) -> None:
        schemas = DingConnectSource().get_schemas(MagicMock(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_all_endpoints_are_full_refresh_only(self) -> None:
        # No DingConnect endpoint exposes a server-side timestamp filter, so nothing supports
        # incremental or append — guarding against an accidental incremental flip.
        schemas = DingConnectSource().get_schemas(MagicMock(), team_id=1)
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)

    def test_transfer_records_notes_retention_window(self) -> None:
        schemas = {s.name: s for s in DingConnectSource().get_schemas(MagicMock(), team_id=1)}
        assert "2 months" in (schemas["TransferRecords"].description or "")

    def test_names_filter(self) -> None:
        schemas = DingConnectSource().get_schemas(MagicMock(), team_id=1, names=["Countries", "Balance"])
        assert {s.name for s in schemas} == {"Countries", "Balance"}


class TestValidateCredentials:
    def test_valid_credentials(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(source_module, "validate_ding_connect_credentials", lambda api_key: True)
        ok, error = DingConnectSource().validate_credentials(MagicMock(api_key="key"), team_id=1)
        assert ok is True
        assert error is None

    def test_invalid_credentials(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(source_module, "validate_ding_connect_credentials", lambda api_key: False)
        ok, error = DingConnectSource().validate_credentials(MagicMock(api_key="key"), team_id=1)
        assert ok is False
        assert error == "Invalid DingConnect API key"


class TestResumableSourceManager:
    def test_manager_is_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        manager = DingConnectSource().get_resumable_source_manager(inputs)
        assert manager._data_class is DingConnectResumeConfig


class TestSourceForPipeline:
    def test_plumbs_through_to_transport(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}
        sentinel = object()

        def fake_ding_connect_source(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return sentinel

        monkeypatch.setattr(source_module, "ding_connect_source", fake_ding_connect_source)

        manager = MagicMock()
        inputs = MagicMock(schema_name="TransferRecords", logger=MagicMock())
        result = DingConnectSource().source_for_pipeline(MagicMock(api_key="key"), manager, inputs)

        assert result is sentinel
        assert captured["api_key"] == "key"
        assert captured["endpoint"] == "TransferRecords"
        assert captured["resumable_source_manager"] is manager


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.dingconnect.com/api/V1/GetCountries",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.dingconnect.com/api/V1/GetProducts",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable_errors = DingConnectSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.dingconnect.com"),
            ("read_timeout", "HTTPSConnectionPool(host='api.dingconnect.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable_errors = DingConnectSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)
