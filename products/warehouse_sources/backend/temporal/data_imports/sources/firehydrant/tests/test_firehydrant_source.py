from typing import Any

from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.firehydrant.settings import FIREHYDRANT_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.firehydrant.source import FireHydrantSource


def _config() -> Any:
    return MagicMock(api_key="fhb_test", region="us")


class TestGetSchemas:
    def test_detected_primary_keys_match_settings(self) -> None:
        schemas = {s.name: s for s in FireHydrantSource().get_schemas(_config(), team_id=1)}
        for name, config in FIREHYDRANT_ENDPOINTS.items():
            assert schemas[name].detected_primary_keys == config.primary_keys


class TestResumableWiring:
    def test_source_for_pipeline_plumbs_api_key_and_schema(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> str:
            captured.update(kwargs)
            return "sentinel"

        import products.warehouse_sources.backend.temporal.data_imports.sources.firehydrant.source as source_module

        monkeypatch.setattr(source_module, "firehydrant_source", fake_source)

        manager = MagicMock()
        inputs = MagicMock(schema_name="incidents", logger=MagicMock())
        result: Any = FireHydrantSource().source_for_pipeline(_config(), manager, inputs)

        assert result == "sentinel"
        assert captured["api_key"] == "fhb_test"
        assert captured["endpoint"] == "incidents"
        assert captured["resumable_source_manager"] is manager
        assert captured["region"] == "us"
