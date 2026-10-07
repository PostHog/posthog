import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.datahub.source import DatahubSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.datahub import (
    DatahubSourceConfig,
)


class TestDatahubSource:
    def setup_method(self) -> None:
        self.source = DatahubSource()
        self.team_id = 123
        self.config = DatahubSourceConfig(instance_url="https://datahub.example.com", api_token="secret-token")

    def test_connection_host_fields_covers_instance_url(self) -> None:
        # The stored access token is sent to whatever `instance_url` points at, so retargeting
        # the URL must force the editor to re-enter the token.
        assert self.source.connection_host_fields == ["instance_url"]

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://datahub.example.com/openapi/v3/entity/dataset",),
            ("403 Client Error: Forbidden for url: https://datahub.example.com/openapi/v3/entity/corpuser",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://datahub.example.com/openapi/v3/entity/dataset",),
            ("429 Client Error: Too Many Requests for url: https://datahub.example.com/openapi/v3/entity/tag",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.datahub.source.check_endpoint_permissions"
    )
    def test_get_endpoint_permissions_delegates_to_shared_helper(self, mock_check: mock.MagicMock) -> None:
        mock_check.return_value = {"users": "needs view privilege", "datasets": None}
        result = self.source.get_endpoint_permissions(self.config, self.team_id, ["users", "datasets"])
        assert result == {"users": "needs view privilege", "datasets": None}
        mock_check.assert_called_once_with(
            "https://datahub.example.com", "secret-token", ["users", "datasets"], self.team_id
        )

    @parameterized.expand([(True, 1500), (False, None)])
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.datahub.source.datahub_source")
    def test_source_for_pipeline_only_passes_the_watermark_on_an_incremental_run(
        self, should_use_incremental_field: bool, expected: int | None, mock_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "dataset_profiles"
        inputs.should_use_incremental_field = should_use_incremental_field
        inputs.db_incremental_field_last_value = 1500

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] == expected

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "nope"
        with pytest.raises(ValueError, match="Unknown DataHub schema"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
