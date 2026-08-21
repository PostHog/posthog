from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.openfda.source import OpenFDASource


def _config(api_key: str | None = "key") -> Any:
    config = MagicMock()
    config.api_key = api_key
    return config


class TestSourceConfig:
    @parameterized.expand([("api_key", "abc"), ("no_key", None)])
    def test_parse_config_accepts_optional_key(self, _name: str, api_key: str | None) -> None:
        # Guards the generated config: api_key is optional, so a source created without one must parse.
        parsed = OpenFDASource().parse_config({"api_key": api_key} if api_key else {})
        assert parsed.api_key == api_key


class TestGetSchemas:
    @parameterized.expand(
        [
            ("drug_events", True, ["safetyreportid"]),
            ("drug_enforcement", True, ["recall_number"]),
            ("food_events", True, ["report_number"]),
            # No reliable server-side date filter -> must be full refresh only, or every "incremental"
            # sync silently re-scans the whole dataset.
            ("drug_labels", False, ["id"]),
            ("drug_ndc", False, ["product_id"]),
        ]
    )
    def test_incremental_support_matches_endpoint(
        self, endpoint: str, expect_incremental: bool, primary_keys: list[str]
    ) -> None:
        schema = {s.name: s for s in OpenFDASource().get_schemas(_config(), team_id=1)}[endpoint]
        assert schema.supports_incremental is expect_incremental
        assert schema.supports_append is expect_incremental
        assert schema.detected_primary_keys == primary_keys
        assert bool(schema.incremental_fields) is expect_incremental


class TestValidateCredentials:
    def test_success(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.sources.openfda.source.validate_openfda_credentials",
            lambda _key: True,
        )
        assert OpenFDASource().validate_credentials(_config(), team_id=1) == (True, None)

    def test_failure_returns_message(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.sources.openfda.source.validate_openfda_credentials",
            lambda _key: False,
        )
        ok, message = OpenFDASource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert message


class TestResumableWiring:
    def test_source_for_pipeline_plumbs_incremental_inputs(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> str:
            captured.update(kwargs)
            return "response"

        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.sources.openfda.source.openfda_source",
            fake_source,
        )
        inputs = MagicMock()
        inputs.schema_name = "drug_enforcement"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "20200101"
        inputs.incremental_field = "report_date"

        result: Any = OpenFDASource().source_for_pipeline(_config(api_key="k"), MagicMock(), inputs)
        assert result == "response"
        assert captured["endpoint"] == "drug_enforcement"
        assert captured["api_key"] == "k"
        assert captured["db_incremental_field_last_value"] == "20200101"
        assert captured["incremental_field"] == "report_date"

    def test_source_for_pipeline_drops_watermark_when_not_incremental(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.sources.openfda.source.openfda_source",
            lambda **kwargs: captured.update(kwargs),
        )
        inputs = MagicMock()
        inputs.schema_name = "drug_ndc"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "20200101"
        inputs.incremental_field = None

        OpenFDASource().source_for_pipeline(_config(), MagicMock(), inputs)
        # A full-refresh run must not pass a stale watermark through as a filter.
        assert captured["db_incremental_field_last_value"] is None
