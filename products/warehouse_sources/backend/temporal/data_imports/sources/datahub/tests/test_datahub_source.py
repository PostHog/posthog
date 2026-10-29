from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
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
    def test_source_for_pipeline_only_passes_the_watermark_on_an_incremental_run(
        self, should_use_incremental_field: bool, expected: int | None
    ) -> None:
        result = SourceDriver(self.source, self.config).run(
            "dataset_profiles",
            [ScriptedResponse(json={"results": []})],
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=1500,
        )

        assert result.raised is None
        assert result.params("startTimeMillis") == [str(expected) if expected is not None else None]
