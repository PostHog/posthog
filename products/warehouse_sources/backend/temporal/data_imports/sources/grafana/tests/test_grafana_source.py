from typing import Literal

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.grafana import (
    GrafanaAuthMethodConfig,
    GrafanaSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.grafana.grafana import (
    GrafanaAuth,
    GrafanaRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.grafana.source import GrafanaSource


def _config(selection: Literal["token", "basic"] = "token", **auth_kwargs) -> GrafanaSourceConfig:
    return GrafanaSourceConfig(
        host="https://yourstack.grafana.net",
        auth_method=GrafanaAuthMethodConfig(selection=selection, **auth_kwargs),
    )


class TestGrafanaSource:
    def setup_method(self):
        self.source = GrafanaSource()
        self.team_id = 123
        self.config = _config(token="glsa_secret")

    @pytest.mark.parametrize("status_code", [429, 503])
    def test_retryable_status_error_matches_retryable_pattern(self, status_code):
        # `fetch()` in grafana.py raises this after its own tenacity retries are exhausted; it
        # must stay classified as retryable rather than paging on every remaining Temporal attempt.
        patterns = self.source.get_retryable_errors()
        error = GrafanaRetryableError(
            f"Grafana API error (retryable): status={status_code}, url=https://yourstack.grafana.net/api/annotations"
        )
        assert any(pattern in str(error) for pattern in patterns)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["dashboards"])
        assert [s.name for s in schemas] == ["dashboards"]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.grafana.source.grafana_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_grafana_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "annotations"
        inputs.team_id = 42
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1784131261208
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_grafana_source.assert_called_once()
        kwargs = mock_grafana_source.call_args.kwargs
        assert kwargs["host"] == "https://yourstack.grafana.net"
        assert isinstance(kwargs["auth"], GrafanaAuth)
        assert kwargs["endpoint"] == "annotations"
        assert kwargs["team_id"] == 42
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1784131261208

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.grafana.source.grafana_source")
    def test_source_for_pipeline_drops_watermark_for_full_refresh(self, mock_grafana_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "annotations"
        inputs.team_id = 42
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1784131261208

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_grafana_source.call_args.kwargs["db_incremental_field_last_value"] is None
