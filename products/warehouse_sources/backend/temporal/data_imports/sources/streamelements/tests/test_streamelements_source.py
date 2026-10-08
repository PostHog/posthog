import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.streamelements import (
    StreamElementsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.streamelements.source import StreamElementsSource


class TestStreamElementsSource:
    def setup_method(self) -> None:
        self.source = StreamElementsSource()
        self.team_id = 123
        self.config = StreamElementsSourceConfig(api_token="jwt-token")

    @pytest.mark.parametrize(
        "mock_return",
        [
            (True, None),
            (False, "Invalid StreamElements token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.streamelements.source.validate_streamelements_credentials"
    )
    def test_validate_credentials(self, mock_validate: mock.MagicMock, mock_return: tuple[bool, str | None]) -> None:
        mock_validate.return_value = mock_return

        assert self.source.validate_credentials(self.config, self.team_id) == mock_return
        # No pin passed -> resolves to default_version (what new rows are stamped with).
        mock_validate.assert_called_once_with(self.config.api_token, "v3")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.streamelements.source.streamelements_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "tips"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1567780450202
        inputs.api_version = "v2"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_token"] == "jwt-token"
        assert kwargs["endpoint"] == "tips"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1567780450202

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.streamelements.source.streamelements_source"
    )
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "store_items"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1567780450202

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
