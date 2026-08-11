import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.duckgres_naming import duckgres_data_imports_table_name_for_version


class TestDuckgresDataImportsTableNameForVersion:
    @parameterized.expand(
        [
            ("mysql", "MySQL", "SalesEU", "customer_orders", "mysql_saleseu_customer_orders"),
            ("bigquery", "BigQuery", None, "daily_stats", "bigquery_daily_stats"),
            ("google_ads", "GoogleAds", None, "video", "googleads_video"),
            ("tiktok_ads", "TikTokAds", "prod__us", "ad_report", "tiktokads_prod_us_ad_report"),
        ]
    )
    def test_source_keys_are_stable_without_camel_case_splitting(
        self, _name: str, source_type: str, prefix: str | None, schema_name: str, expected: str
    ) -> None:
        assert duckgres_data_imports_table_name_for_version(source_type, prefix, schema_name, "copy_v1") == expected

    def test_legacy_batch_version_preserves_aggressive_snake_case(self) -> None:
        assert (
            duckgres_data_imports_table_name_for_version("TikTokAds", None, "ad_report", "legacy_batch_v1")
            == "tik_tok_ads_ad_report"
        )

    def test_long_names_have_stable_collision_resistant_suffixes(self) -> None:
        first = duckgres_data_imports_table_name_for_version("Postgres", None, "a" * 90, "legacy_batch_v1")
        second = duckgres_data_imports_table_name_for_version("Postgres", None, "a" * 89 + "b", "legacy_batch_v1")

        assert len(first) == 63
        assert len(second) == 63
        assert first != second
        assert first == duckgres_data_imports_table_name_for_version("Postgres", None, "a" * 90, "legacy_batch_v1")

    def test_rejects_unknown_version(self) -> None:
        with pytest.raises(ValueError, match="Unsupported Duckgres data imports table naming version"):
            duckgres_data_imports_table_name_for_version("Postgres", None, "orders", "future")
