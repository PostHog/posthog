from typing import Any, cast

import pytest
from unittest import mock

import structlog

from products.warehouse_sources.backend.facade.source_config import SourceFieldInputConfig, SourceFieldInputConfigType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.transistor import (
    TransistorSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.transistor.settings import (
    ENDPOINTS,
    TRANSISTOR_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.transistor.source import TransistorSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.transistor.source"


def _make_inputs(
    schema_name: str = "shows",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
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


class TestTransistorSource:
    def setup_method(self):
        self.source = TransistorSource()
        self.config = TransistorSourceConfig(api_key="secret-key")

    def test_api_key_field_is_stored_as_a_secret(self):
        fields = [field for field in self.source.get_source_config.fields if isinstance(field, SourceFieldInputConfig)]

        assert [field.name for field in fields] == ["api_key"]
        # A non-password, non-secret field would leak the key into non-sensitive job inputs.
        assert fields[0].type == SourceFieldInputConfigType.PASSWORD
        assert fields[0].secret is True
        assert fields[0].required is True

    def test_get_schemas_filters_by_name(self):
        schemas = self.source.get_schemas(self.config, team_id=123, names=["show_analytics", "unknown"])

        assert [schema.name for schema in schemas] == ["show_analytics"]

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_for_pipeline_uses_the_endpoint_primary_keys(self, endpoint):
        manager = self.source.get_resumable_source_manager(_make_inputs(schema_name=endpoint))

        response = self.source.source_for_pipeline(self.config, manager, _make_inputs(schema_name=endpoint))

        assert response.name == endpoint
        assert response.primary_keys == TRANSISTOR_ENDPOINTS[endpoint].primary_keys

    @pytest.mark.parametrize(
        "should_use_incremental_field, expected_last_value",
        [(True, "2026-08-01"), (False, None)],
    )
    def test_source_for_pipeline_only_passes_the_watermark_when_syncing_incrementally(
        self, should_use_incremental_field, expected_last_value
    ):
        inputs = _make_inputs(
            schema_name="show_analytics",
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value="2026-08-01",
        )
        manager = self.source.get_resumable_source_manager(inputs)

        with mock.patch(f"{SOURCE_MODULE}.transistor_source") as transistor_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = cast(dict[str, Any], transistor_source.call_args.kwargs)
        assert kwargs["should_use_incremental_field"] is should_use_incremental_field
        assert kwargs["db_incremental_field_last_value"] == expected_last_value
        assert kwargs["api_key"] == "secret-key"
        assert kwargs["endpoint"] == "show_analytics"
