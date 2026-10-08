import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.greenhouse import (
    GreenhouseSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.source import GreenhouseSource

INCREMENTAL_ENDPOINTS = {
    "candidates",
    "applications",
    "jobs",
    "job_posts",
    "offers",
    "scorecards",
    "scheduled_interviews",
    "users",
}
FULL_REFRESH_ENDPOINTS = {"departments", "offices", "sources", "rejection_reasons", "close_reasons"}


class TestGreenhouseSource:
    def setup_method(self) -> None:
        self.source = GreenhouseSource()
        self.team_id = 123
        self.config = GreenhouseSourceConfig(api_key="test_api_key", client_id="cid", client_secret="csecret")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.source.validate_greenhouse_credentials"
    )
    def test_validate_credentials_at_source_create_accepts_forbidden(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)

        is_valid, error = self.source.validate_credentials(self.config, self.team_id, schema_name=None)

        assert is_valid is True
        assert error is None
        mock_validate.assert_called_once_with(
            "v3", api_key="test_api_key", client_id="cid", client_secret="csecret", accept_forbidden=True
        )

    @pytest.mark.parametrize(
        "pinned_version, expected_version, expected_path",
        [
            (None, "v3", "/interviews"),
            ("v3", "v3", "/interviews"),
            # A v1-pinned source must be probed on v1, not on the (newer) default.
            ("v1", "v1", "/scheduled_interviews"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.source.validate_greenhouse_credentials"
    )
    def test_validate_credentials_probes_the_pinned_version(
        self,
        mock_validate: mock.MagicMock,
        pinned_version: str | None,
        expected_version: str,
        expected_path: str,
    ) -> None:
        mock_validate.return_value = (True, None)

        self.source.validate_credentials(
            self.config, self.team_id, schema_name="scheduled_interviews", api_version=pinned_version
        )

        assert mock_validate.call_args.args[0] == expected_version
        assert mock_validate.call_args.kwargs["path"] == expected_path

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.source.validate_greenhouse_credentials"
    )
    def test_validate_credentials_rejects_v3_only_schema_on_v1(self, mock_validate: mock.MagicMock) -> None:
        is_valid, error = self.source.validate_credentials(
            self.config, self.team_id, schema_name="openings", api_version="v1"
        )

        assert is_valid is False
        assert error is not None and "Harvest v3" in error
        mock_validate.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.source.greenhouse_source")
    def test_source_for_pipeline_passes_incremental_inputs(self, mock_greenhouse_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "candidates"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00.000Z"
        inputs.incremental_field = "updated_at"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_greenhouse_source.call_args.kwargs
        assert kwargs["api_key"] == "test_api_key"
        assert kwargs["endpoint"] == "candidates"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00.000Z"
        assert kwargs["incremental_field"] == "updated_at"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.source.greenhouse_source")
    def test_source_for_pipeline_drops_last_value_when_not_incremental(
        self, mock_greenhouse_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "departments"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00.000Z"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_greenhouse_source.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None
