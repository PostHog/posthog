import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.octolens import (
    OctolensSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.octolens.source import OctolensSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.octolens.source"


class TestOctolensSource:
    def setup_method(self) -> None:
        self.source = OctolensSource()
        self.team_id = 123
        self.config = OctolensSourceConfig(api_key="octolens-key")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://app.octolens.com/api/v2/mentions",
            "403 Client Error: Forbidden for url: https://app.octolens.com/api/v2/keywords",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "unrelated_error",
        [
            "429 Client Error: Too Many Requests for url: https://app.octolens.com/api/v2/mentions",
            "500 Server Error for url: https://app.octolens.com/api/v2/mentions",
        ],
    )
    def test_non_retryable_errors_ignore_throttling_and_server_errors(self, unrelated_error: str) -> None:
        assert not any(key in unrelated_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid or expired Octolens API key"),
            (403, False, "boom"),
            (0, False, "boom"),
        ],
    )
    @mock.patch(f"{SOURCE_MODULE}.check_access")
    def test_validate_credentials(
        self, mock_check: mock.MagicMock, status: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        mock_check.return_value = (status, "boom")
        is_valid, message = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert message == expected_message

    @mock.patch(f"{SOURCE_MODULE}.check_access")
    def test_validate_credentials_probes_the_resolved_api_version(self, mock_check: mock.MagicMock) -> None:
        mock_check.return_value = (200, None)
        self.source.validate_credentials(self.config, self.team_id)
        mock_check.assert_called_once_with("octolens-key", "v2")

    @mock.patch(f"{SOURCE_MODULE}.check_access")
    def test_validate_credentials_rejects_unknown_schema_without_probing(self, mock_check: mock.MagicMock) -> None:
        is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name="not_a_table")
        assert is_valid is False
        assert message == "Unknown Octolens schema 'not_a_table'"
        mock_check.assert_not_called()

    @mock.patch(f"{SOURCE_MODULE}.octolens_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_octolens_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "mentions"
        inputs.team_id = 123
        inputs.job_id = "job-1"
        inputs.api_version = None
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_octolens_source.call_args.kwargs
        assert kwargs["api_key"] == "octolens-key"
        assert kwargs["endpoint"] == "mentions"
        assert kwargs["team_id"] == 123
        assert kwargs["job_id"] == "job-1"
        # An unset pin resolves to the source's default version rather than reaching the request layer as None.
        assert kwargs["api_version"] == "v2"
        assert kwargs["resumable_source_manager"] is manager
        # Every table is full refresh, so no watermark can reach the request body.
        assert "db_incremental_field_last_value" not in kwargs
        assert "should_use_incremental_field" not in kwargs
