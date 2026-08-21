import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mention import (
    MentionSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mention.source import MentionSource


class TestMentionSource:
    def setup_method(self) -> None:
        self.source = MentionSource()
        self.team_id = 123
        self.config = MentionSourceConfig(access_token="tok")

    def test_new_sources_default_to_latest_version(self) -> None:
        # New sources are stamped with default_version; it must be the newest supported label.
        assert self.source.supported_versions == ("1.19", "1.21")
        assert self.source.default_version == "1.21"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mention.source.mention_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "mentions"
        inputs.api_version = "1.21"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["access_token"] == "tok"
        assert kwargs["endpoint"] == "mentions"
        assert kwargs["resumable_source_manager"] is manager
        # The resolved source pin is threaded to the request layer so it drives the Accept-Version header.
        assert kwargs["api_version"] == "1.21"

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Mention schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
