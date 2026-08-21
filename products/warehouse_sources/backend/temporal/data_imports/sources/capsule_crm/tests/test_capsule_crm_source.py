from typing import Any

from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.capsule_crm.source import CapsuleCRMSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.capsulecrm import (
    CapsuleCRMSourceConfig,
)


class TestCapsuleCRMSource:
    def setup_method(self) -> None:
        self.source = CapsuleCRMSource()
        self.config = CapsuleCRMSourceConfig(access_token="tok")
        self.team_id = 123

    def test_validate_credentials_success(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.capsule_crm.source.validate_capsule_crm_credentials",
            return_value=True,
        ):
            assert self.source.validate_credentials(self.config, self.team_id) == (True, None)

    def test_validate_credentials_failure(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.capsule_crm.source.validate_capsule_crm_credentials",
            return_value=False,
        ):
            ok, message = self.source.validate_credentials(self.config, self.team_id)
            assert ok is False
            assert message is not None

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "parties"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = mock.MagicMock()

        captured: dict[str, Any] = {}

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.capsule_crm.source.capsule_crm_source",
            side_effect=lambda **kwargs: captured.update(kwargs),
        ):
            self.source.source_for_pipeline(self.config, manager, inputs)

        assert captured["access_token"] == "tok"
        assert captured["endpoint"] == "parties"
        assert captured["resumable_source_manager"] is manager
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    def test_source_for_pipeline_drops_watermark_when_not_incremental(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "tasks"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        captured: dict[str, Any] = {}

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.capsule_crm.source.capsule_crm_source",
            side_effect=lambda **kwargs: captured.update(kwargs),
        ):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        # A non-incremental run must not pass a stale watermark through as a `since` filter.
        assert captured["db_incremental_field_last_value"] is None
