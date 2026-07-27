from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.location import (
    fill_missing_from_dotted_name,
    normalize_namespace,
    resolve_source_location,
)


def _source_inputs(
    schema_name: str = "users",
    *,
    source_schema: str | None = None,
    source_table_name: str | None = None,
    **overrides: Any,
) -> SourceInputs:
    # Mirror how a real schema row stashes the SQL location keys inside the generic `schema_metadata`.
    metadata: dict[str, Any] = {}
    if source_schema is not None:
        metadata["source_schema"] = source_schema
    if source_table_name is not None:
        metadata["source_table_name"] = source_table_name
    defaults: dict[str, Any] = {
        "schema_name": schema_name,
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": MagicMock(),
        "reset_pipeline": False,
        "schema_metadata": metadata or None,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestResolveSourceLocation:
    @parameterized.expand(
        [
            # (name, schema_name, source_schema, source_table_name, config_namespace, default, exp_schema, exp_table)
            ("metadata wins over config", "users", "analytics", "users", "public", "public", "analytics", "users"),
            ("dotted name self-heals", "analytics.users", None, None, None, None, "analytics", "users"),
            ("config namespace fallback", "users", None, None, "dbo", "public", "dbo", "users"),
            ("default fallback when config blank", "users", None, None, "", "public", "public", "users"),
            ("empty metadata + dotted self-heals", "sales.orders", "", "", None, None, "sales", "orders"),
            ("whitespace config normalizes to default", "users", None, None, "   ", "public", "public", "users"),
            ("all blank yields None schema", "users", "", "", "", None, None, "users"),
        ]
    )
    def test_schema_and_table_resolution(
        self,
        _name: str,
        schema_name: str,
        source_schema: str | None,
        source_table_name: str | None,
        config_namespace: str | None,
        default: str | None,
        exp_schema: str | None,
        exp_table: str,
    ) -> None:
        inputs = _source_inputs(
            schema_name=schema_name,
            source_schema=source_schema,
            source_table_name=source_table_name,
        )
        location = resolve_source_location(inputs, config_namespace=config_namespace, default=default)
        assert location.schema == exp_schema
        assert location.table_name == exp_table

    def test_metadata_takes_precedence_over_dotted_name(self) -> None:
        # A pinned location routes the query; the dotted display name is not re-split.
        inputs = _source_inputs(schema_name="analytics.users", source_schema="reporting", source_table_name="events")
        location = resolve_source_location(inputs, config_namespace="public")
        assert location.schema == "reporting"
        assert location.table_name == "events"

    def test_never_emits_empty_string_schema(self) -> None:
        inputs = _source_inputs(schema_name="users", source_schema="", source_table_name="")
        location = resolve_source_location(inputs, config_namespace="", default=None)
        assert location.schema is None  # driver treats None as "all namespaces", never `WHERE schema = ''`

    def test_response_name_derived_from_schema_name_when_no_storage_key(self) -> None:
        inputs = _source_inputs(schema_name="analytics.users")
        location = resolve_source_location(inputs, config_namespace=None)
        assert location.response_name == "analytics_users"

    def test_storage_key_preserves_legacy_delta_path(self) -> None:
        # Migrated row keeps the legacy Delta subdir (`users`, not `public_users`) or its data is orphaned.
        inputs = _source_inputs(schema_name="public.users", s3_folder_name="users")
        location = resolve_source_location(inputs, config_namespace=None)
        assert location.response_name == "users"
        assert location.schema == "public"
        assert location.table_name == "users"

    def test_storage_key_is_normalized(self) -> None:
        inputs = _source_inputs(schema_name="public.My Table", s3_folder_name="My Table")
        location = resolve_source_location(inputs, config_namespace=None)
        assert location.response_name == "my_table"

    def test_cross_namespace_duplicates_stay_distinct(self) -> None:
        analytics = resolve_source_location(_source_inputs(schema_name="analytics.users"), config_namespace=None)
        sales = resolve_source_location(_source_inputs(schema_name="sales.users"), config_namespace=None)
        assert (analytics.schema, analytics.table_name) == ("analytics", "users")
        assert (sales.schema, sales.table_name) == ("sales", "users")
        assert analytics.response_name != sales.response_name
        assert {analytics.response_name, sales.response_name} == {"analytics_users", "sales_users"}

    def test_single_schema_legacy_row_is_byte_identical(self) -> None:
        # No metadata, no storage key, non-dotted name: resolves exactly like the pre-multi-schema path.
        inputs = _source_inputs(schema_name="users")
        location = resolve_source_location(inputs, config_namespace="public", default="public")
        assert location == ("public", "users", "users")


class TestSelfHealHelpers:
    @parameterized.expand(
        [
            ("value", "public", "public"),
            ("trims", "  dbo  ", "dbo"),
            ("empty to none", "", None),
            ("whitespace to none", "   ", None),
            ("non-string to none", None, None),
        ]
    )
    def test_normalize_namespace(self, _name: str, value: str | None, expected: str | None) -> None:
        assert normalize_namespace(value) == expected

    @parameterized.expand(
        [
            # (name, schema, table, display_name, exp_schema, exp_table)
            ("both present, no heal", "analytics", "users", "analytics.users", "analytics", "users"),
            ("missing both, dotted heals", None, None, "analytics.users", "analytics", "users"),
            ("missing schema only", None, "users", "sales.orders", "sales", "users"),
            ("missing table only", "reporting", None, "x.events", "reporting", "events"),
            ("empty schema treated as missing", "", None, "sales.orders", "sales", "orders"),
            ("not dotted, no heal", None, None, "users", None, None),
        ]
    )
    def test_fill_missing_from_dotted_name(
        self,
        _name: str,
        schema: str | None,
        table: str | None,
        display_name: str,
        exp_schema: str | None,
        exp_table: str | None,
    ) -> None:
        assert fill_missing_from_dotted_name(schema, table, display_name) == (exp_schema, exp_table)
