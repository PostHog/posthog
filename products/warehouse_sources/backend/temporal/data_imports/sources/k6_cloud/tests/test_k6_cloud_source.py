import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.k6cloud import (
    K6CloudSourceConfig,
)
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

    @pytest.mark.parametrize(
        "mock_return, schema_name, expected_valid, expected_has_message",
        [
            ((True, False), None, True, False),
            ((False, False), None, False, True),  # 401 bad token/stack
            ((False, True), None, True, False),  # 403 at source-create -> accepted
            ((False, True), "test_runs", False, True),  # 403 for a specific schema -> rejected
        ],
    )
    def test_validate_credentials(
        self,
        mock_return: tuple[bool, bool],
        schema_name: str | None,
        expected_valid: bool,
        expected_has_message: bool,
    ) -> None:
        status = 200 if mock_return[0] else 403 if mock_return[1] else 401
        with scripted_network([ScriptedResponse(status=status)]) as network:
            is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)

        assert is_valid is expected_valid
        assert (message is not None) is expected_has_message
        assert network.requests_log[0].path == (
            "/cloud/v6/test_runs" if schema_name == "test_runs" else "/cloud/v6/auth"
        )
        assert network.requests_log[0].headers["authorization"] == "Bearer tok"
        assert network.requests_log[0].headers["x-stack-id"] == "12345"
