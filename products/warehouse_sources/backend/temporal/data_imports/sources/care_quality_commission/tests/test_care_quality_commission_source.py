from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.care_quality_commission import (
    source as cqc_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.care_quality_commission.source import (
    CareQualityCommissionSource,
)


def _config(api_key: str = "key", partner_code: str | None = "PC") -> Any:
    config = MagicMock()
    config.api_key = api_key
    config.partner_code = partner_code
    return config


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
