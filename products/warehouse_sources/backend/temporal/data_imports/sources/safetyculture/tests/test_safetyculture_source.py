import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.safetyculture import (
    SafetyCultureSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.settings import (
    ENDPOINTS,
    SAFETYCULTURE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.source import SafetyCultureSource


class TestSafetyCultureSource:
    def setup_method(self) -> None:
        self.source = SafetyCultureSource()
        self.team_id = 123
        self.config = SafetyCultureSourceConfig(api_token="sc-token")

    def test_get_schemas_covers_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        by_name = {s.name: s for s in schemas}
        for name, endpoint_config in SAFETYCULTURE_ENDPOINTS.items():
            assert by_name[name].supports_incremental is endpoint_config.supports_incremental
            assert by_name[name].supports_append is endpoint_config.supports_incremental

    @parameterized.expand(
        [
            (200, True, None),
            (401, False, "Invalid SafetyCulture API token"),
            # Feed access is permission-scoped, so a 403 on the probe feed still proves the token
            # itself is genuine — it must not block source-create.
            (403, True, None),
            (500, False, "SafetyCulture returned HTTP 500"),
            (0, False, "Could not connect to SafetyCulture: boom"),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.source.check_access")
    def test_validate_credentials_at_source_create(
        self,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_check: mock.MagicMock,
    ) -> None:
        message = (
            "SafetyCulture returned HTTP 500"
            if status == 500
            else ("Could not connect to SafetyCulture: boom" if status == 0 else None)
        )
        mock_check.return_value = (status, message)
        is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert returned == expected_message

    @parameterized.expand([(200, True), (401, False), (403, False)])
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.source.check_access")
    def test_validate_credentials_for_schema_probes_that_feed(
        self, status: int, expected_valid: bool, mock_check: mock.MagicMock
    ) -> None:
        mock_check.return_value = (status, None)
        is_valid, _ = self.source.validate_credentials(self.config, self.team_id, schema_name="inspections")
        assert is_valid is expected_valid
        mock_check.assert_called_once_with(self.config.api_token, "/feed/inspections")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.source.safetyculture_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "inspections"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-03-01T00:00:00.000Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_token"] == "sc-token"
        assert kwargs["endpoint"] == "inspections"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-03-01T00:00:00.000Z"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.source.safetyculture_source"
    )
    def test_source_for_pipeline_drops_cursor_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "inspections"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-03-01T00:00:00.000Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown SafetyCulture schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
