from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import build_default_sync_settings
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.speedcurve import (
    SpeedcurveSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.speedcurve.source import SpeedcurveSource


def test_incremental_defaults_revisit_recent_records_and_merge_updates() -> None:
    schemas = SpeedcurveSource().get_schemas(
        SpeedcurveSourceConfig(api_key="fake-key"), team_id=1, names=["tests", "deploys", "budgets"]
    )
    settings = {schema.name: build_default_sync_settings(schema) for schema in schemas}
    for name in ("tests", "deploys"):
        assert settings[name]["sync_type"] == "incremental"
        assert settings[name]["incremental_field_lookback_seconds"] == 86400
        assert settings[name]["incremental_field_type"] == "integer"
    assert settings["budgets"]["sync_type"] == "full_refresh"
    assert "incremental_field_lookback_seconds" not in settings["budgets"]
    assert not any(schema.supports_append for schema in schemas)
