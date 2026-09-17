from types import SimpleNamespace
from typing import cast

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.recurly import (
    RecurlySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recurly.settings import (
    ENDPOINTS,
    RECURLY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recurly.source import RecurlySource

INCREMENTAL_ENDPOINTS = [name for name, e in RECURLY_ENDPOINTS.items() if e.supports_incremental]
FULL_REFRESH_ENDPOINTS = [name for name, e in RECURLY_ENDPOINTS.items() if not e.supports_incremental]


class TestRecurlySource:
    def setup_method(self):
        self.source = RecurlySource()
        self.team_id = 123
        self.config = RecurlySourceConfig(api_key="test-key", region="us")

    def test_get_schemas_returns_every_endpoint(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", INCREMENTAL_ENDPOINTS)
    def test_incremental_endpoints_advertise_incremental(self, endpoint):
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        assert schema.supports_incremental is True
        assert schema.supports_append is True
        assert {field["field"] for field in schema.incremental_fields} == {"created_at", "updated_at"}

    @pytest.mark.parametrize("endpoint", FULL_REFRESH_ENDPOINTS)
    def test_full_refresh_endpoints_do_not_advertise_incremental(self, endpoint):
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["accounts"])
        assert len(schemas) == 1
        assert schemas[0].name == "accounts"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.recurly.source.recurly_source")
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

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.recurly.source.recurly_source")
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
