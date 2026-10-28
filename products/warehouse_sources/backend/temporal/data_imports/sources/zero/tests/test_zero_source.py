import json

import pytest
from unittest import mock
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zero import ZeroSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zero.settings import ENDPOINT_CONFIGS
from products.warehouse_sources.backend.temporal.data_imports.sources.zero.source import ZeroSource

INCREMENTAL_ENDPOINTS = {name for name, config in ENDPOINT_CONFIGS.items() if config.incremental_fields}


class TestZeroSource:
    def setup_method(self) -> None:
        self.source = ZeroSource()
        self.team_id = 123
        self.config = ZeroSourceConfig(api_key="api_test")

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog with no I/O, so the public docs can render it.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid"),
        [(True, True), (False, False)],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.zero.source.validate_zero_credentials"
    )
    def test_validate_credentials(self, mock_validate: MagicMock, mock_return: bool, expected_valid: bool) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert (error_message is None) is expected_valid
        mock_validate.assert_called_once_with("api_test")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.zero.source.zero_source")
    def test_source_for_pipeline_plumbs_inputs(self, mock_zero_source: MagicMock) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = MagicMock()
        inputs.schema_name = "Companies"
        inputs.team_id = 7
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "updatedAt"
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00+00:00"

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_zero_source.assert_called_once_with(
            api_key="api_test",
            endpoint="Companies",
            team_id=7,
            job_id="job-1",
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            incremental_field="updatedAt",
            db_incremental_field_last_value="2026-01-01T00:00:00+00:00",
        )

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self) -> None:
        result = SourceDriver(self.source, self.config).run(
            "Companies",
            route(
                {
                    "/api/workspaces": [ScriptedResponse(json={"data": [{"id": "ws-1"}], "total": 1})],
                    "/api/companies": [ScriptedResponse(json={"data": [], "total": 0})],
                }
            ),
            should_use_incremental_field=False,
            incremental_field=None,
            db_incremental_field_last_value="2026-01-01T00:00:00+00:00",
        )

        company_request = next(request for request in result.requests if request.path == "/api/companies")
        assert json.loads(company_request.param("where") or "{}") == {"workspaceId": "ws-1"}
