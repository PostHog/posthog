import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rocketlane import (
    RocketlaneSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane.source import RocketlaneSource


class TestRocketlaneSource:
    def setup_method(self) -> None:
        self.source = RocketlaneSource()
        self.team_id = 123
        self.config = RocketlaneSourceConfig(api_key="rl-key")

    @parameterized.expand(
        [
            ("valid", 200, True, None),
            ("unauthorized", 401, False, "Invalid Rocketlane API key"),
            ("forbidden", 403, False, "Invalid Rocketlane API key"),
            ("server_error", 500, False, "Rocketlane returned HTTP 500"),
            ("connection_error", 0, False, "Could not connect to Rocketlane: boom"),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane.source.check_access")
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_check: mock.MagicMock,
    ) -> None:
        message = (
            "Rocketlane returned HTTP 500"
            if status == 500
            else ("Could not connect to Rocketlane: boom" if status == 0 else None)
        )
        mock_check.return_value = (status, message)
        is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert returned == expected_message

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane.source.check_access")
    def test_validate_credentials_probes_the_account_key(self, mock_check: mock.MagicMock) -> None:
        # The api-key is account-wide, so validation probes the key, not a per-schema scope.
        mock_check.return_value = (200, None)
        self.source.validate_credentials(self.config, self.team_id, schema_name="tasks")
        mock_check.assert_called_once_with("rl-key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane.source.rocketlane_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_rocketlane_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "projects"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_rocketlane_source.assert_called_once()
        kwargs = mock_rocketlane_source.call_args.kwargs
        assert kwargs["api_key"] == "rl-key"
        assert kwargs["endpoint"] == "projects"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Rocketlane schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
