import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
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
        "response, expected_valid, expected_message",
        [
            (ScriptedResponse(json={"organizationId": "org_1"}), True, None),
            (
                ScriptedResponse(status=401, json={"error": {"message": "boom"}}),
                False,
                "Invalid or expired Octolens API key",
            ),
            (ScriptedResponse(status=403, json={"error": {"message": "boom"}}), False, "boom"),
            (ConnectionError("boom"), False, "Could not connect to Octolens"),
        ],
    )
    def test_validate_credentials(
        self,
        response: ScriptedResponse | ConnectionError,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        with scripted_network(always(response)):
            is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if isinstance(response, ConnectionError):
            assert message is not None
            assert expected_message is not None
            assert expected_message in message
        else:
            assert message == expected_message

    def test_validate_credentials_rejects_unknown_schema_without_probing(self) -> None:
        with scripted_network([]) as network:
            is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name="not_a_table")

        assert is_valid is False
        assert message == "Unknown Octolens schema 'not_a_table'"
        assert network.requests_log == []

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
