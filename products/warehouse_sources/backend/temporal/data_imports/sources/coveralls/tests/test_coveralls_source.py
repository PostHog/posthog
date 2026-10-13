import pytest
from unittest import mock

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.coveralls.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.coveralls.source import CoverallsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.coveralls import (
    CoverallsSourceConfig,
)


def _make_inputs(
    schema_name: str = "builds",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value=None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=123,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=None,
        incremental_field="created_at" if should_use_incremental_field else None,
        incremental_field_type=None,
        job_id="job-id",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestCoverallsSource:
    def setup_method(self):
        self.source = CoverallsSource()
        self.team_id = 123
        self.config = CoverallsSourceConfig(repositories="acme/widgets\nacme/gadgets", service="github")

    def test_connection_host_fields_gate_token_retargeting(self):
        # `service` and `repositories` decide which repos the stored token queries, so the update
        # serializer must re-require the token when either changes — dropping them here would let
        # an editor reuse a preserved token against repos it never had token access to.
        assert self.source.connection_host_fields == ["service", "repositories"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["builds"])

        assert [schema.name for schema in schemas] == ["builds"]

    @pytest.mark.parametrize(
        "api_token, expected_reason",
        [
            (None, "Requires a personal API token from your Coveralls account settings."),
            ("tok", None),
        ],
    )
    def test_endpoint_permissions_gate_repositories_on_token(self, api_token, expected_reason):
        config = CoverallsSourceConfig(repositories="acme/widgets", service="github", api_token=api_token)

        permissions = self.source.get_endpoint_permissions(config, self.team_id, list(ENDPOINTS))

        assert permissions["builds"] is None
        assert permissions["repositories"] == expected_reason

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.coveralls.source.coveralls_source")
    def test_source_for_pipeline_passes_watermark_only_when_incremental(self, mock_coveralls_source):
        # A stale watermark left on the schema must not leak into a full-refresh run.
        inputs = _make_inputs(should_use_incremental_field=False, db_incremental_field_last_value="2021-04-16")

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_coveralls_source.call_args[1]["db_incremental_field_last_value"] is None
