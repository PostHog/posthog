from types import SimpleNamespace
from typing import cast

from unittest import mock

from sources.recurly._config import RecurlySourceConfig
from sources.recurly.source import RecurlySource
from sources.sdk import ResumableSourceManager, SourceInputs


class TestRecurlySource:
    def setup_method(self):
        self.source = RecurlySource()
        self.team_id = 123
        self.config = RecurlySourceConfig(api_key="test-key", region="us")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["accounts"])
        assert len(schemas) == 1
        assert schemas[0].name == "accounts"

    @mock.patch("sources.recurly.source.recurly_source")
    def test_source_for_pipeline_plumbs_inputs(self, mock_recurly_source):
        mock_recurly_source.return_value = SimpleNamespace(name="accounts", column_hints=None)
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = SimpleNamespace(
            schema_name="accounts",
            team_id=self.team_id,
            job_id="job-1",
            should_use_incremental_field=True,
            incremental_field="updated_at",
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
        )

        response = self.source.source_for_pipeline(self.config, manager, cast(SourceInputs, inputs))

        mock_recurly_source.assert_called_once_with(
            api_key="test-key",
            region="us",
            endpoint="accounts",
            team_id=self.team_id,
            job_id="job-1",
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            incremental_field="updated_at",
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
        )
        assert response.name == "accounts"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
        assert response.sort_mode == "asc"

    @mock.patch("sources.recurly.source.recurly_source")
    def test_source_for_pipeline_drops_last_value_on_full_refresh(self, mock_recurly_source):
        mock_recurly_source.return_value = SimpleNamespace(name="plans", column_hints=None)
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = SimpleNamespace(
            schema_name="plans",
            team_id=self.team_id,
            job_id="job-2",
            should_use_incremental_field=False,
            incremental_field=None,
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
        )

        self.source.source_for_pipeline(self.config, manager, cast(SourceInputs, inputs))

        # When the user isn't running incrementally, no watermark should leak through.
        assert mock_recurly_source.call_args.kwargs["db_incremental_field_last_value"] is None
