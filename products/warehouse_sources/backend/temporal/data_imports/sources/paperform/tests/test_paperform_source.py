from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.paperform import (
    PaperformSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paperform.source import PaperformSource


class TestPaperformSource:
    def setup_method(self) -> None:
        self.source = PaperformSource()
        self.team_id = 123
        self.config = PaperformSourceConfig(api_key="pf-key")

    def test_validate_credentials_delegates_with_api_key(self) -> None:
        # The status-to-message mapping lives in paperform.validate_credentials; here we only assert
        # the source probes with the configured key and returns the delegate's verdict unchanged.
        with scripted_network([ScriptedResponse(status=401)]) as network:
            result = self.source.validate_credentials(self.config, self.team_id)

        assert result == (False, "Invalid Paperform API key")
        assert len(network.requests_log) == 1
        assert network.requests_log[0].headers["authorization"] == "Bearer pf-key"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.paperform.source.paperform_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "submissions"
        inputs.team_id = 123
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "pf-key"
        assert kwargs["endpoint"] == "submissions"
        assert kwargs["team_id"] == 123
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00Z"

    def test_source_for_pipeline_drops_watermark_on_full_refresh(self) -> None:
        result = SourceDriver(self.source, self.config).run(
            "submissions",
            [
                ScriptedResponse(json={"results": {"forms": [{"id": "f1"}]}, "has_more": False}),
                ScriptedResponse(json={"results": {"submissions": []}, "has_more": False}),
            ],
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
        )

        # A full refresh must re-read everything, even when a stale watermark is still stored.
        assert result.raised is None
        assert result.paths == ["/v1/forms", "/v1/forms/f1/submissions"]
        assert result.requests[1].param("after_date") is None
