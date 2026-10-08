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

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["tasks"])
        assert len(schemas) == 1
        assert schemas[0].name == "tasks"

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.rocketlane.com/api/1.0/projects?pageSize=100",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.rocketlane.com/api/1.0/tasks?pageSize=100&pageToken=abc",
            ),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.rocketlane.com/api/1.0/projects",
            ),
            ("read_timeout", "HTTPSConnectionPool(host='api.rocketlane.com', port=443): Read timed out."),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.rocketlane.com/api/1.0/users"),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

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
