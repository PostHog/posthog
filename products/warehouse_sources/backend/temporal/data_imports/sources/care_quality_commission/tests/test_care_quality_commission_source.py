from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.care_quality_commission import (
    source as cqc_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.care_quality_commission.care_quality_commission import (
    CQCResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.care_quality_commission.source import (
    CareQualityCommissionSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(api_key: str = "key", partner_code: str | None = "PC") -> Any:
    config = MagicMock()
    config.api_key = api_key
    config.partner_code = partner_code
    return config


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert CareQualityCommissionSource().source_type == ExternalDataSourceType.CAREQUALITYCOMMISSION

    def test_config_metadata(self) -> None:
        config = CareQualityCommissionSource().get_source_config
        assert config.label == "Care Quality Commission"
        assert config.category == DataWarehouseSourceCategory.ANALYTICS
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # docsUrl slug must match the published doc filename so the website doesn't 404.
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/care-quality-commission"
        assert config.unreleasedSource is None

    def test_fields(self) -> None:
        fields: dict[str, Any] = {f.name: f for f in CareQualityCommissionSource().get_source_config.fields}
        assert set(fields) == {"api_key", "partner_code"}
        # The subscription key is the secret; the partner code is an optional throttling hint.
        assert fields["api_key"].required is True
        assert fields["api_key"].secret is True
        assert fields["partner_code"].required is False


class TestGetSchemas:
    def test_returns_both_streams_as_full_refresh(self) -> None:
        schemas = {s.name: s for s in CareQualityCommissionSource().get_schemas(MagicMock(), team_id=1)}
        assert set(schemas) == {"providers", "locations"}
        for schema in schemas.values():
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    @parameterized.expand([("providers", ["providerId"]), ("locations", ["locationId"])])
    def test_primary_keys(self, endpoint: str, expected_keys: list[str]) -> None:
        schemas = {s.name: s for s in CareQualityCommissionSource().get_schemas(MagicMock(), team_id=1)}
        assert schemas[endpoint].detected_primary_keys == expected_keys

    def test_names_filter(self) -> None:
        schemas = CareQualityCommissionSource().get_schemas(MagicMock(), team_id=1, names=["locations"])
        assert [s.name for s in schemas] == ["locations"]


class TestDocumentedTables:
    def test_lists_tables_without_credentials(self) -> None:
        # The endpoint catalog is static (no I/O), so the public docs can render the table list.
        assert CareQualityCommissionSource.lists_tables_without_credentials is True

    def test_documented_tables_carry_descriptions_and_keys(self) -> None:
        tables = {t["name"]: t for t in CareQualityCommissionSource().get_documented_tables()}
        assert set(tables) == {"providers", "locations"}
        assert tables["providers"]["primary_keys"] == ["providerId"]
        assert tables["providers"]["sync_methods"] == ["Full refresh"]
        assert tables["providers"]["description"]


class TestValidateCredentials:
    def test_valid(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(cqc_source, "validate_cqc_credentials", lambda api_key, partner_code: True)
        ok, error = CareQualityCommissionSource().validate_credentials(_config(), team_id=1)
        assert ok is True
        assert error is None

    def test_invalid(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(cqc_source, "validate_cqc_credentials", lambda api_key, partner_code: False)
        ok, error = CareQualityCommissionSource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert error is not None

    def test_passes_partner_code_through(self, monkeypatch: Any) -> None:
        seen: dict[str, Any] = {}

        def fake_validate(api_key: str, partner_code: str | None) -> bool:
            seen["api_key"] = api_key
            seen["partner_code"] = partner_code
            return True

        monkeypatch.setattr(cqc_source, "validate_cqc_credentials", fake_validate)
        CareQualityCommissionSource().validate_credentials(_config(api_key="k", partner_code="P1"), team_id=1)
        assert seen == {"api_key": "k", "partner_code": "P1"}


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.cqc.org.uk/public/v1/providers/1-123",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.cqc.org.uk/public/v1/locations"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = CareQualityCommissionSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.cqc.org.uk/public/v1/providers",
            ),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.cqc.org.uk/public/v1/providers"),
            ("read_timeout", "HTTPSConnectionPool(host='api.cqc.org.uk', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = CareQualityCommissionSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestResumableSourceManager:
    def test_returns_manager_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        manager = CareQualityCommissionSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CQCResumeConfig


class TestSourceForPipeline:
    def test_plumbs_arguments(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> str:
            captured.update(kwargs)
            return "response"

        monkeypatch.setattr(cqc_source, "care_quality_commission_source", fake_source)

        inputs = MagicMock()
        inputs.schema_name = "providers"
        manager = MagicMock()
        result: Any = CareQualityCommissionSource().source_for_pipeline(
            _config(api_key="k", partner_code="P1"), manager, inputs
        )

        assert result == "response"
        assert captured["api_key"] == "k"
        assert captured["partner_code"] == "P1"
        assert captured["endpoint"] == "providers"
        assert captured["resumable_source_manager"] is manager
