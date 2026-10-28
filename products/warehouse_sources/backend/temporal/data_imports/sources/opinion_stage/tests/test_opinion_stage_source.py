import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.opinionstage import (
    OpinionStageSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opinion_stage.source import OpinionStageSource


class TestOpinionStageSource:
    def setup_method(self) -> None:
        self.source = OpinionStageSource()
        self.team_id = 123
        self.config = OpinionStageSourceConfig(api_key="os-key")

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        "ok, status, expected_valid, expected_message",
        [
            (False, None, False, "Could not validate Opinion Stage API key"),
        ],
    )
    def test_validate_credentials(
        self,
        ok: bool,
        status: int | None,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        answer = ScriptedResponse(status=status) if status is not None else ConnectionError("reset")
        with scripted_network(always(answer)) as network:
            is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is ok
        assert is_valid is expected_valid
        assert returned == expected_message
        assert network.requests_log
        assert all(request.path == "/api/v2/items" for request in network.requests_log)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.opinion_stage.source.opinion_stage_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "items"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "os-key"
        assert kwargs["endpoint"] == "items"
        assert kwargs["resumable_source_manager"] is manager
