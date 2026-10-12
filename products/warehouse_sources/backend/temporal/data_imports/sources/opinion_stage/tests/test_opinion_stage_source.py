import pytest
from unittest import mock

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
            (True, 200, True, None),
            (False, 401, False, "Invalid Opinion Stage API key"),
            (False, 403, False, "Invalid Opinion Stage API key"),
            (False, 500, False, "Opinion Stage returned HTTP 500"),
            (False, None, False, "Could not validate Opinion Stage API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.opinion_stage.source.validate_opinion_stage_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        ok: bool,
        status: int | None,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = (ok, status)
        is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert returned == expected_message

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

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Opinion Stage schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
