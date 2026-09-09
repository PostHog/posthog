from typing import Any, cast

import pytest
from unittest import mock

import structlog

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

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

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Transistor"
        assert config.label == "Transistor.fm"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source must be visible in the wizard, not hidden behind unreleasedSource.
        assert not config.unreleasedSource

    def test_api_key_field_is_stored_as_a_secret(self):
        fields = [field for field in self.source.get_source_config.fields if isinstance(field, SourceFieldInputConfig)]

        assert [field.name for field in fields] == ["api_key"]
        # A non-password, non-secret field would leak the key into non-sensitive job inputs.
        assert fields[0].type == SourceFieldInputConfigType.PASSWORD
        assert fields[0].secret is True
        assert fields[0].required is True

    def test_get_schemas_matches_the_endpoint_catalog(self):
        schemas = self.source.get_schemas(self.config, team_id=123)

        assert [schema.name for schema in schemas] == list(ENDPOINTS)
        for schema in schemas:
            endpoint = TRANSISTOR_ENDPOINTS[schema.name]
            assert schema.detected_primary_keys == endpoint.primary_keys
            assert schema.supports_incremental is endpoint.supports_incremental

    @pytest.mark.parametrize(
        "endpoint, supports_incremental",
        [
            # Only the analytics endpoints take a server-side start_date/end_date filter; the
            # entity lists have no updated-since filter, so advertising incremental would make
            # every sync silently re-read everything.
            ("shows", False),
            ("episodes", False),
            ("subscribers", False),
            ("webhooks", False),
            ("show_analytics", True),
            ("episode_analytics", True),
        ],
    )
    def test_incremental_support_per_endpoint(self, endpoint, supports_incremental):
        schema = self.source.get_schemas(self.config, team_id=123, names=[endpoint])[0]

        assert schema.supports_incremental is supports_incremental
        assert [field["field"] for field in schema.incremental_fields] == (["date"] if supports_incremental else [])
        # Download counts keep accruing for days, so incremental analytics re-read a trailing window.
        assert (schema.default_incremental_lookback_seconds is not None) is supports_incremental

    def test_get_schemas_filters_by_name(self):
        schemas = self.source.get_schemas(self.config, team_id=123, names=["show_analytics", "unknown"])

        assert [schema.name for schema in schemas] == ["show_analytics"]

    def test_documented_tables_render_without_credentials(self):
        # Public source docs call get_schemas with a placeholder config; a source that made a
        # request here would hang the docs endpoint.
        tables = self.source.get_documented_tables()

        assert [table["name"] for table in tables] == list(ENDPOINTS)
        assert all(table["description"] for table in tables)

    def test_canonical_descriptions_cover_every_endpoint(self):
        descriptions = self.source.get_canonical_descriptions()

        assert set(descriptions) == set(ENDPOINTS)
        for endpoint, entry in descriptions.items():
            # Every primary key column needs a description, since those are the join keys the
            # agent reasons about.
            assert set(TRANSISTOR_ENDPOINTS[endpoint].primary_keys) <= set(entry.get("columns", {}))

    @pytest.mark.parametrize("status", ["401", "403"])
    def test_auth_failures_are_non_retryable(self, status):
        errors = self.source.get_non_retryable_errors()

        # Without these the job retries a permanently bad key until the schedule gives up.
        assert any(status in pattern for pattern in errors)
        assert all(message for message in errors.values())

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
