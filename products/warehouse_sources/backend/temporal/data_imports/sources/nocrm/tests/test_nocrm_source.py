from typing import Any

from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.nocrm import NoCRMSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.nocrm.source import NoCRMSource


class TestNoCRMSource:
    def setup_method(self) -> None:
        self.source = NoCRMSource()
        self.config = NoCRMSourceConfig(subdomain="acme", api_key="key")
        self.team_id = 123

    def test_validate_credentials_success(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.nocrm.source.validate_nocrm_credentials",
            return_value=True,
        ):
            assert self.source.validate_credentials(self.config, self.team_id) == (True, None)

    def test_validate_credentials_failure(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.nocrm.source.validate_nocrm_credentials",
            return_value=False,
        ):
            ok, message = self.source.validate_credentials(self.config, self.team_id)
            assert ok is False
            assert message is not None

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "leads"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = mock.MagicMock()

        captured: dict[str, Any] = {}
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.nocrm.source.nocrm_source",
            side_effect=lambda **kwargs: captured.update(kwargs),
        ):
            self.source.source_for_pipeline(self.config, manager, inputs)

        assert captured["api_key"] == "key"
        assert captured["subdomain"] == "acme"
        assert captured["endpoint"] == "leads"
        assert captured["team_id"] is inputs.team_id
        assert captured["job_id"] is inputs.job_id
        assert captured["resumable_source_manager"] is manager
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    def test_source_for_pipeline_drops_watermark_when_not_incremental(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "users"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        captured: dict[str, Any] = {}
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.nocrm.source.nocrm_source",
            side_effect=lambda **kwargs: captured.update(kwargs),
        ):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert captured["db_incremental_field_last_value"] is None
