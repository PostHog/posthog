import datetime

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.workiz import WorkizSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.workiz.source import WorkizSource


class TestWorkizSource:
    def setup_method(self) -> None:
        self.source = WorkizSource()
        self.team_id = 123
        self.config = WorkizSourceConfig(api_token="tok")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.workiz.source.workiz_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        mock_source.return_value.name = "Leads"
        mock_source.return_value.column_hints = None
        inputs = mock.MagicMock()
        inputs.schema_name = "Leads"
        inputs.team_id = 123
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = datetime.datetime(2024, 1, 1)
        inputs.incremental_field = "LeadDateTime"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_token"] == "tok"
        assert kwargs["endpoint"] == "Leads"
        assert kwargs["team_id"] == 123
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == datetime.datetime(2024, 1, 1)
        assert kwargs["incremental_field"] == "LeadDateTime"

    @parameterized.expand(
        [
            ("Jobs", ["UUID"], "desc"),
            ("Leads", ["UUID"], "desc"),
            ("Team", ["id"], "asc"),
            ("TimeOff", ["userName", "start"], "asc"),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.workiz.source.workiz_source")
    def test_source_for_pipeline_response_shape(
        self,
        schema_name: str,
        expected_primary_keys: list[str],
        expected_sort_mode: str,
        mock_source: mock.MagicMock,
    ) -> None:
        mock_source.return_value.name = schema_name
        mock_source.return_value.column_hints = None
        inputs = mock.MagicMock()
        inputs.schema_name = schema_name
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = None

        response = self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert response.primary_keys == expected_primary_keys
        assert response.sort_mode == expected_sort_mode
        if schema_name in ("Jobs", "Leads"):
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["CreatedDate"]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
