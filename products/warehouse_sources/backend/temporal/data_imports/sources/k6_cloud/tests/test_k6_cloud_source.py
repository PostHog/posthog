import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.k6cloud import (
    K6CloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.k6_cloud.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.k6_cloud.source import K6CloudSource

INCREMENTAL_ENDPOINTS = {"test_runs"}


class TestK6CloudSource:
    def setup_method(self) -> None:
        self.source = K6CloudSource()
        self.team_id = 123
        self.config = K6CloudSourceConfig(api_token="tok", stack_id="12345")

    def test_stack_id_is_a_connection_host_field(self) -> None:
        # `stack_id` routes the stored token to a specific k6 stack, so changing it must re-require
        # the secret — guards against credential retargeting across stacks.
        assert self.source.connection_host_fields == ["stack_id"]

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog -> the public docs table list must render.
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, schema_name, expected_valid, expected_has_message",
        [
            ((True, False), None, True, False),
            ((False, False), None, False, True),  # 401 bad token/stack
            ((False, True), None, True, False),  # 403 at source-create -> accepted
            ((False, True), "test_runs", False, True),  # 403 for a specific schema -> rejected
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.k6_cloud.source.validate_k6_cloud_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: tuple[bool, bool],
        schema_name: str | None,
        expected_valid: bool,
        expected_has_message: bool,
    ) -> None:
        mock_validate.return_value = mock_return
        is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)
        assert is_valid is expected_valid
        assert (message is not None) is expected_has_message
        mock_validate.assert_called_once_with(self.config.api_token, self.config.stack_id, schema_name)
