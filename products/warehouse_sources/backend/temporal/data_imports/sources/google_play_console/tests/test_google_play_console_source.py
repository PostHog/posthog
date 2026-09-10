from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googleplayconsole import (
    GooglePlayConsoleKeyFileConfig,
    GooglePlayConsoleSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_play_console.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_play_console.settings import (
    BREAKDOWN_TABLES,
    ENDPOINTS,
    LIST_ENDPOINTS,
    METRIC_SETS,
    PRIMARY_KEYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_play_console.source import (
    GooglePlayConsoleSource,
)
from products.warehouse_sources.backend.types import IncrementalFieldType

SOURCE_MODULE = GooglePlayConsoleSource.__module__


def _config(app_package_names: str | None = None) -> GooglePlayConsoleSourceConfig:
    return GooglePlayConsoleSourceConfig(
        key_file=GooglePlayConsoleKeyFileConfig(
            client_email="reporting@example.iam.gserviceaccount.com",
            private_key="private-key",
            private_key_id="private-key-id",
            token_uri="https://oauth2.googleapis.com/token",
        ),
        app_package_names=app_package_names,
    )


def test_package_names_force_the_key_to_be_re_uploaded() -> None:
    assert GooglePlayConsoleSource().connection_host_fields == ["app_package_names"]


def test_api_version_metadata() -> None:
    source = GooglePlayConsoleSource()

    assert source.supported_versions == ("v1beta1",)
    assert source.default_version == "v1beta1"
    assert source.api_docs_url is not None and source.api_docs_url.startswith("https://")


def test_get_schemas_returns_every_endpoint() -> None:
    schemas = GooglePlayConsoleSource().get_schemas(_config(), team_id=1)

    assert [schema.name for schema in schemas] == list(ENDPOINTS)
    assert all(schema.description for schema in schemas)
    assert {schema.name: schema.detected_primary_keys for schema in schemas} == PRIMARY_KEYS


@pytest.mark.parametrize("name", sorted(METRIC_SETS))
def test_metric_sets_sync_incrementally_on_date_but_never_append(name: str) -> None:
    schema = next(s for s in GooglePlayConsoleSource().get_schemas(_config(), team_id=1) if s.name == name)

    assert schema.supports_incremental is True
    # Play restates recent days, so appending would keep the stale rows alongside the corrections.
    assert schema.supports_append is False
    assert [field["field"] for field in schema.incremental_fields] == ["date"]
    assert schema.incremental_fields[0]["field_type"] == IncrementalFieldType.Date
    assert schema.default_incremental_lookback_seconds == 7 * 24 * 60 * 60


BASE_VITALS_TABLES = (
    "crash_rate",
    "anr_rate",
    "excessive_wakeup_rate",
    "stuck_background_wakelock_rate",
    "slow_start_rate",
    "slow_rendering_rate",
    "lmk_rate",
)


def test_the_default_vitals_tables_keep_their_grain() -> None:
    assert METRIC_SETS["crash_rate"].dimensions == ("versionCode",)
    assert METRIC_SETS["slow_start_rate"].dimensions == ("startType", "versionCode")
    assert METRIC_SETS["error_counts"].dimensions == ("reportType", "versionCode")
    assert PRIMARY_KEYS["crash_rate"] == ["app", "date", "versionCode"]
    assert PRIMARY_KEYS["slow_start_rate"] == ["app", "date", "startType", "versionCode"]
    assert PRIMARY_KEYS["error_counts"] == ["app", "date", "reportType", "versionCode"]


def test_every_vitals_rate_metric_set_gets_a_device_model_and_an_api_level_table() -> None:
    assert set(BREAKDOWN_TABLES) == {
        f"{base}_by_{suffix}" for base in BASE_VITALS_TABLES for suffix in ("device_model", "api_level")
    }
    assert "error_counts_by_device_model" not in METRIC_SETS


def test_the_wider_tables_are_the_only_ones_off_by_default() -> None:
    schemas = GooglePlayConsoleSource().get_schemas(_config(), team_id=1)

    assert {schema.name for schema in schemas if not schema.should_sync_default} == set(BREAKDOWN_TABLES)


@pytest.mark.parametrize(
    "name,base,dimension", [(name, base, dimension) for name, (base, dimension) in sorted(BREAKDOWN_TABLES.items())]
)
def test_a_wider_table_adds_one_dimension_to_its_base_table(name: str, base: str, dimension: str) -> None:
    endpoint = METRIC_SETS[name]
    base_endpoint = METRIC_SETS[base]

    assert endpoint.dimensions == (*base_endpoint.dimensions, dimension)
    assert endpoint.resource == base_endpoint.resource
    assert endpoint.metrics == base_endpoint.metrics
    assert endpoint.history_days == base_endpoint.history_days
    assert PRIMARY_KEYS[name] == ["app", "date", *base_endpoint.dimensions, dimension]
    assert "Off by default" in endpoint.description


def test_error_reports_sync_incrementally_on_event_time() -> None:
    schema = next(s for s in GooglePlayConsoleSource().get_schemas(_config(), team_id=1) if s.name == "error_reports")

    assert schema.supports_incremental is True
    assert schema.supports_append is True
    assert [field["field"] for field in schema.incremental_fields] == ["eventTime"]
    assert schema.default_incremental_lookback_seconds == 24 * 60 * 60


@pytest.mark.parametrize("name", ["apps", "error_issues", "anomalies"])
def test_aggregate_endpoints_are_full_refresh(name: str) -> None:
    schema = next(s for s in GooglePlayConsoleSource().get_schemas(_config(), team_id=1) if s.name == name)

    assert schema.supports_incremental is False
    assert schema.supports_append is False
    assert schema.incremental_fields == []


def test_get_schemas_filters_by_names() -> None:
    schemas = GooglePlayConsoleSource().get_schemas(_config(), team_id=1, names=["crash_rate", "anomalies"])

    assert {schema.name for schema in schemas} == {"crash_rate", "anomalies"}


def test_table_catalog_is_published_without_credentials() -> None:
    source = GooglePlayConsoleSource()

    assert source.lists_tables_without_credentials is True
    tables = source.get_documented_tables()
    assert {table["name"] for table in tables} == set(ENDPOINTS)


def test_canonical_descriptions_cover_every_endpoint() -> None:
    assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)
    for name, entry in CANONICAL_DESCRIPTIONS.items():
        assert entry["description"], name
        assert entry["docs_url"].startswith("https://"), name
        assert entry["columns"], name


@pytest.mark.parametrize("name", sorted(METRIC_SETS))
def test_metric_set_descriptions_document_their_primary_key_columns(name: str) -> None:
    columns = CANONICAL_DESCRIPTIONS[name]["columns"]

    assert set(PRIMARY_KEYS[name]).issubset(columns)


@pytest.mark.parametrize("name", sorted(LIST_ENDPOINTS))
def test_list_endpoint_descriptions_document_their_primary_key_columns(name: str) -> None:
    columns = CANONICAL_DESCRIPTIONS[name]["columns"]

    assert set(PRIMARY_KEYS[name]).issubset(columns)


def _inputs(**overrides: Any) -> mock.MagicMock:
    inputs = mock.MagicMock()
    inputs.schema_name = "crash_rate"
    inputs.api_version = None
    inputs.should_use_incremental_field = True
    inputs.db_incremental_field_last_value = "2024-03-01"
    for key, value in overrides.items():
        setattr(inputs, key, value)
    return inputs


def test_source_for_pipeline_plumbs_config_and_inputs() -> None:
    manager = mock.MagicMock()
    inputs = _inputs()

    with mock.patch(f"{SOURCE_MODULE}.google_play_console_source") as build_source:
        GooglePlayConsoleSource().source_for_pipeline(_config("com.b, com.a"), manager, inputs)

    kwargs = build_source.call_args.kwargs
    assert kwargs["package_names"] == ("com.a", "com.b")
    assert kwargs["resource_name"] == "crash_rate"
    assert kwargs["api_version"] == "v1beta1"
    assert kwargs["resumable_source_manager"] is manager
    assert kwargs["should_use_incremental_field"] is True
    assert kwargs["db_incremental_field_last_value"] == "2024-03-01"
    assert kwargs["key"].client_email == "reporting@example.iam.gserviceaccount.com"


def test_source_for_pipeline_honors_a_pinned_api_version() -> None:
    with mock.patch(f"{SOURCE_MODULE}.google_play_console_source") as build_source:
        GooglePlayConsoleSource().source_for_pipeline(_config(), mock.MagicMock(), _inputs(api_version="v1alpha1"))

    assert build_source.call_args.kwargs["api_version"] == "v1alpha1"


def test_source_for_pipeline_syncs_every_visible_app_when_no_packages_are_configured() -> None:
    with mock.patch(f"{SOURCE_MODULE}.google_play_console_source") as build_source:
        GooglePlayConsoleSource().source_for_pipeline(_config(), mock.MagicMock(), _inputs())

    assert build_source.call_args.kwargs["package_names"] == ()
