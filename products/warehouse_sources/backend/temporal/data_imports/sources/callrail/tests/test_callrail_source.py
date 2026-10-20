import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.callrail.source import CallRailSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.callrail import (
    CallRailSourceConfig,
)


class TestCallRailSource:
    def setup_method(self) -> None:
        self.source = CallRailSource()
        self.team_id = 123
        self.config = CallRailSourceConfig(api_key="key", account_id=None)

    def test_connection_host_fields_includes_account_id(self) -> None:
        # Changing account_id retargets the stored API key, so editing it must require re-entering secrets.
        assert self.source.connection_host_fields == ["account_id"]

    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid CallRail API key"),
        ],
    )
    def test_validate_credentials(
        self,
        status_code: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert len(network.requests_log) == 1
        assert network.requests_log[0].headers["authorization"] == 'Token token="key"'

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.callrail.source.callrail_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_callrail_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "calls"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000
        config = CallRailSourceConfig(api_key="key", account_id="ACC1")
        manager = mock.MagicMock()

        self.source.source_for_pipeline(config, manager, inputs)

        kwargs = mock_callrail_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["account_id"] == "ACC1"
        assert kwargs["endpoint"] == "calls"
        assert kwargs["team_id"] is inputs.team_id
        assert kwargs["job_id"] is inputs.job_id
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000

    def test_source_for_pipeline_blank_account_id_becomes_none(self) -> None:
        config = CallRailSourceConfig(api_key="key", account_id="")
        result = SourceDriver(self.source, config).run(
            "calls",
            [
                ScriptedResponse(json={"accounts": [{"id": "ACC1"}]}),
                ScriptedResponse(json={"calls": [{"id": "C1"}], "total_pages": 1}),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/v3/a.json", "/v3/a/ACC1/calls.json"]
