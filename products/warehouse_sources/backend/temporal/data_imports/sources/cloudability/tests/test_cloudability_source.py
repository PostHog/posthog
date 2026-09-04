from types import SimpleNamespace
from typing import cast

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.source import CloudabilitySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudability import (
    CloudabilitySourceConfig,
)


class TestCloudabilitySource:
    def setup_method(self):
        self.source = CloudabilitySource()
        self.team_id = 123
        self.config = CloudabilitySourceConfig(api_key="key", region="us", view_id=None)

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_no_endpoint_advertises_incremental(self, endpoint):
        # None of Cloudability's endpoints expose a server-side "modified since" filter.
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        assert schema.supports_incremental is False
        assert schema.incremental_fields == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid credentials. Check your API key and region."),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.source.validate_cloudability_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key, self.config.region)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.source.cloudability_source"
    )
    def test_source_for_pipeline_plumbs_inputs(self, mock_cloudability_source):
        mock_cloudability_source.return_value = SimpleNamespace(name="Views")
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = SimpleNamespace(schema_name="Views", team_id=self.team_id, job_id="job-1")

        response = self.source.source_for_pipeline(self.config, manager, cast(SourceInputs, inputs))

        mock_cloudability_source.assert_called_once_with(
            api_key="key",
            region="us",
            endpoint="Views",
            team_id=self.team_id,
            job_id="job-1",
            resumable_source_manager=manager,
            view_id=None,
        )
        assert response is mock_cloudability_source.return_value

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.source.cloudability_source"
    )
    def test_source_for_pipeline_passes_blank_view_id_as_none(self, mock_cloudability_source):
        # An empty string from the form must not be sent to Cloudability as a literal viewId="".
        config = CloudabilitySourceConfig(api_key="key", region="eu", view_id="")
        mock_cloudability_source.return_value = SimpleNamespace(name="Anomalies")
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = SimpleNamespace(schema_name="Anomalies", team_id=self.team_id, job_id="job-2")

        self.source.source_for_pipeline(config, manager, cast(SourceInputs, inputs))

        assert mock_cloudability_source.call_args.kwargs["view_id"] is None

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.source.cloudability_source"
    )
    def test_source_for_pipeline_passes_configured_view_id(self, mock_cloudability_source):
        config = CloudabilitySourceConfig(api_key="key", region="us", view_id="42")
        mock_cloudability_source.return_value = SimpleNamespace(name="Anomalies")
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = SimpleNamespace(schema_name="Anomalies", team_id=self.team_id, job_id="job-3")

        self.source.source_for_pipeline(config, manager, cast(SourceInputs, inputs))

        assert mock_cloudability_source.call_args.kwargs["view_id"] == "42"
