from typing import Any

from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.linode.source import LinodeSource


def _make_config() -> Any:
    config = MagicMock()
    config.api_token = "tok"
    return config


class TestLinodeSourceClass:
    def setup_method(self) -> None:
        self.source = LinodeSource()
        self.team_id = 123

    def test_source_for_pipeline_omits_watermark_when_not_incremental(self) -> None:
        # A full-refresh run must not forward a stale last-value, or the transport would build an
        # X-Filter and silently window the results.
        inputs = MagicMock()
        inputs.schema_name = "volumes"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00"
        inputs.incremental_field = None

        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.linode.source.linode_source",
            side_effect=fake_source,
        ):
            self.source.source_for_pipeline(_make_config(), MagicMock(), inputs)

        assert captured["should_use_incremental_field"] is False
        assert captured["db_incremental_field_last_value"] is None
