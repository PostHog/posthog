from datetime import date

import duckdb

from products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.restatements import (
    analytics_stream_names,
    restatement_caption,
    restatement_recipe,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.settings import (
    APP_STORE_CONNECT_ENDPOINTS,
    AppStoreConnectEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.source import (
    AppStoreConnectSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalFieldType


def _analytics_config(name: str) -> AppStoreConnectEndpointConfig:
    return AppStoreConnectEndpointConfig(
        name=name,
        kind="analytics_report",
        primary_keys=["app_id", "processing_date", "_line"],
        incremental_fields=[incremental_field("processing_date", IncrementalFieldType.Date)],
        partition_key="processing_date",
    )


# One report date restated across vintages, plus snapshot-backfilled history (negative _line):
#   - 2026-06-15 exists only in the snapshot vintage (processing_date 2026-07-02).
#   - 2026-07-01 has a snapshot row at the boundary plus two ongoing vintages (07-03, 07-04);
#     the (US) tuple is restated in every vintage, the (DE) tuple only in the older ongoing one.
_VINTAGE_ROWS: list[tuple[str, date, int, date, str, int]] = [
    ("app1", date(2026, 7, 2), -1, date(2026, 6, 15), "US", 7),
    ("app1", date(2026, 7, 2), -2, date(2026, 7, 1), "US", 99),
    ("app1", date(2026, 7, 3), 1, date(2026, 7, 1), "US", 5),
    ("app1", date(2026, 7, 3), 2, date(2026, 7, 1), "DE", 3),
    ("app1", date(2026, 7, 4), 1, date(2026, 7, 1), "US", 6),
]


def _run_recipe_on_vintages(sql: str, table_name: str, value_column: str) -> list[tuple]:
    connection = duckdb.connect()
    connection.execute(
        f"CREATE TABLE {table_name} "
        f"(app_id VARCHAR, processing_date DATE, _line BIGINT, date DATE, territory VARCHAR, {value_column} BIGINT)"
    )
    connection.executemany(f"INSERT INTO {table_name} VALUES (?, ?, ?, ?, ?, ?)", _VINTAGE_ROWS)
    return connection.execute(sql).fetchall()


class TestAppStoreConnectRestatements:
    def test_analytics_streams_derive_from_the_catalog(self) -> None:
        expected = tuple(
            name for name, config in APP_STORE_CONNECT_ENDPOINTS.items() if config.kind == "analytics_report"
        )

        assert analytics_stream_names(APP_STORE_CONNECT_ENDPOINTS) == expected
        assert "sales_reports" not in expected

        extended = {
            **APP_STORE_CONNECT_ENDPOINTS,
            "analytics_future_stream": _analytics_config("analytics_future_stream"),
        }
        assert "analytics_future_stream" in analytics_stream_names(extended)

    def test_recipe_keeps_one_row_per_date_and_dimension_tuple_from_the_latest_vintage(self) -> None:
        columns = dict.fromkeys(("app_id", "processing_date", "_line", "date", "territory", "sessions"), "")
        recipe = restatement_recipe(_analytics_config("analytics_events"), columns)

        assert recipe is not None
        assert recipe.dimensions == ("date", "app_id", "territory")
        assert recipe.measures == ("sessions",)

        rows = _run_recipe_on_vintages(recipe.sql, recipe.table_name, "sessions")

        # The 07-04 restatement of 2026-07-01 carries no DE row, and a restatement republishes
        # its report date in full, so DE is gone rather than unchanged. Reading its 07-03 value
        # forward would resurrect a tuple Apple dropped and inflate every total taken from it.
        assert sorted(rows) == [
            (date(2026, 6, 15), "app1", "US", 7),
            (date(2026, 7, 1), "app1", "US", 6),
        ]

    def test_fallback_recipe_keeps_only_the_latest_vintage_when_measures_are_unknown(self) -> None:
        columns = dict.fromkeys(("app_id", "processing_date", "_line", "date", "territory", "happiness"), "")
        recipe = restatement_recipe(_analytics_config("analytics_events"), columns)

        assert recipe is not None
        assert "argMax(" not in recipe.sql
        assert recipe.measures == ()

        rows = _run_recipe_on_vintages(recipe.sql, recipe.table_name, "happiness")

        assert sorted((row[3], row[0], row[4], row[5]) for row in rows) == [
            (date(2026, 6, 15), "app1", "US", 7),
            (date(2026, 7, 1), "app1", "US", 6),
        ]

    def test_caption_recipe_follows_the_catalog(self) -> None:
        caption = restatement_caption()
        first_analytics = analytics_stream_names(APP_STORE_CONNECT_ENDPOINTS)[0]

        assert f"appstoreconnect_{first_analytics}" in caption

    def test_source_rebuilds_its_descriptions_for_a_table_prefix(self) -> None:
        # Guards the wiring: a recipe that honours a prefix is useless if the source never passes one.
        name = analytics_stream_names(APP_STORE_CONNECT_ENDPOINTS)[0]
        descriptions = AppStoreConnectSource().get_canonical_descriptions_for_table_prefix("acme_")

        assert f"FROM acme_appstoreconnect_{name} AS raw" in (descriptions[name].get("description") or "")
