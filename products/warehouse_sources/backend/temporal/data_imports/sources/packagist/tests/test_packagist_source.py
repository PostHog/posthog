import pytest
from unittest import mock

import structlog

from posthog.schema import ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.packagist import (
    PackagistSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.packagist.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.packagist.source import PackagistSource


def _make_inputs(
    schema_name: str = "packages",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: str | None = None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=123,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=None,
        incremental_field="date" if should_use_incremental_field else None,
        incremental_field_type=None,
        job_id="job-id",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestPackagistSource:
    def setup_method(self):
        self.source = PackagistSource()
        self.team_id = 123
        self.config = PackagistSourceConfig(packages="monolog/monolog\nsymfony/console")

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Packagist"
        assert config.label == "Packagist"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/packagist"
        # A finished source must be visible in the wizard, not hidden behind unreleasedSource.
        assert not config.unreleasedSource

    def test_get_schemas_lists_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_get_schemas_incremental_flags(self, endpoint):
        # Only the download stats endpoint has a server-side date-window filter; the metadata
        # endpoints return the full document every time, so they are full refresh only.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        expected = endpoint == "downloads"
        assert schemas[endpoint].supports_incremental is expected
        assert schemas[endpoint].supports_append is expected

    def test_downloads_has_incremental_lookback(self):
        # Packagist stats lag behind real time, so incremental syncs re-read a trailing window.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["downloads"].default_incremental_lookback_seconds == 3 * 24 * 60 * 60
        assert schemas["packages"].default_incremental_lookback_seconds is None

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["downloads"])

        assert [schema.name for schema in schemas] == ["downloads"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    def test_no_non_retryable_errors(self):
        # Unauthenticated API: there are no credential errors to permanently fail on.
        assert self.source.get_non_retryable_errors() == {}

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True
        assert len(self.source.get_documented_tables()) == len(ENDPOINTS)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.packagist.source.packagist_source")
    def test_source_for_pipeline_drops_watermark_when_not_incremental(self, mock_packagist_source):
        # A stale watermark from a previous incremental run must not leak into a full refresh.
        inputs = _make_inputs(schema_name="downloads", db_incremental_field_last_value="2026-07-01")

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_packagist_source.call_args.kwargs["db_incremental_field_last_value"] is None
