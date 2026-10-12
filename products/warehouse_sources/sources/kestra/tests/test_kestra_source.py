import pytest

from products.warehouse_sources.sources.kestra._config import KestraAuthMethodConfig, KestraSourceConfig
from products.warehouse_sources.sources.kestra.source import KestraSource
from products.warehouse_sources.sources.sdk.testing import build_default_sync_settings


@pytest.mark.parametrize("names", [None, ["executions"], ["flows"]])
def test_lookback_applies_only_to_execution_syncs(names: list[str] | None) -> None:
    config = KestraSourceConfig(host="", tenant="", auth_method=KestraAuthMethodConfig())
    schemas = KestraSource().get_schemas(config, 1, names=names)
    settings = {schema.name: build_default_sync_settings(schema) for schema in schemas}
    if names != ["flows"]:
        assert settings["executions"]["incremental_field_lookback_seconds"] == 604800
    for name, sync_config in settings.items():
        if name != "executions":
            assert "incremental_field_lookback_seconds" not in sync_config
