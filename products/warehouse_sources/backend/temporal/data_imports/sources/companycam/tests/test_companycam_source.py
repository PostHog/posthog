import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.companycam.source import CompanycamSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.companycam import (
    CompanycamSourceConfig,
)

_INCREMENTAL_ENDPOINTS = {"Projects", "Photos", "Videos"}
_FULL_REFRESH_ENDPOINTS = {"Users", "Tags", "Groups", "Checklists", "ChecklistTemplates"}


class TestCompanycamSource:
    def setup_method(self) -> None:
        self.source = CompanycamSource()
        self.team_id = 123
        self.config = CompanycamSourceConfig(api_key="test-key")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.companycam.com/v2/projects?page=1",
            "403 Client Error: Forbidden for url: https://api.companycam.com/v2/photos?page=1",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.companycam.com/v2/photos",
            "500 Server Error: Internal Server Error for url: https://api.companycam.com/v2/photos",
            "HTTPSConnectionPool(host='api.companycam.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.companycam.source.validate_companycam_credentials"
    )
    def test_validate_credentials(
        self, mock_validate: mock.MagicMock, mock_return: bool, expected_valid: bool, expected_message: str | None
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("test-key", "v2")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.companycam.source.companycam_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_companycam_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "Projects"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000
        inputs.api_version = None
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_companycam_source.assert_called_once()
        kwargs = mock_companycam_source.call_args.kwargs
        assert kwargs["api_key"] == "test-key"
        assert kwargs["endpoint"] == "Projects"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == 1700000000
        assert kwargs["api_version"] == "v2"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.companycam.source.companycam_source")
    def test_source_for_pipeline_omits_cursor_when_not_incremental(
        self, mock_companycam_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "Users"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1700000000

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_companycam_source.call_args.kwargs["db_incremental_field_last_value"] is None
