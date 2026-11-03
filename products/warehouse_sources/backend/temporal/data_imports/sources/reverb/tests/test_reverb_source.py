import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.reverb import ReverbSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.reverb.reverb import ReverbResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.reverb.source import ReverbSource

_INCREMENTAL_ENDPOINTS = {"Orders", "Payouts"}
_FULL_REFRESH_ENDPOINTS = {"Listings"}


class TestReverbSource:
    def setup_method(self):
        self.source = ReverbSource()
        self.team_id = 123
        self.config = ReverbSourceConfig(api_token="token")

    @pytest.mark.parametrize(
        "script, expected_valid, expected_message",
        [
            (always(ScriptedResponse(status=200, json={})), True, None),
        ],
    )
    def test_validate_credentials(self, script, expected_valid, expected_message):
        with scripted_network(script) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert network.requests_log[0].headers["authorization"] == "Bearer token"
        assert network.requests_log[0].headers["accept-version"] == "3.0"

    def test_source_for_pipeline_plumbs_arguments(self):
        result = SourceDriver(self.source, self.config).run(
            "Orders",
            [ScriptedResponse(json={"orders": [], "total_pages": 1})],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            resume_state=ReverbResumeConfig(next_page=4),
        )

        request = result.requests[0]
        assert request.headers["authorization"] == "Bearer token"
        assert request.path == "/api/my/orders/selling/all"
        assert request.param("updated_start_date") == "2026-01-01T00:00:00Z"
        assert request.headers["accept-version"] == "3.0"
        # The resume manager reaches the extraction: the first page is the saved page.
        assert request.param("page") == "4"

    def test_source_for_pipeline_omits_cursor_when_not_incremental(self):
        result = SourceDriver(self.source, self.config).run(
            "Orders",
            [ScriptedResponse(json={"orders": [], "total_pages": 1})],
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        assert result.requests[0].param("updated_start_date") is None
