import math

from parameterized import parameterized

from posthog.schema import MarketingAnalyticsBaseColumns, NativeMarketingSource, WebAnalyticsItemKind

from .constants import (
    _CONFIG_MODELS,
    _DEFAULT_SOURCES_ENUMS,
    INTEGRATION_DEFAULT_SOURCES,
    INTEGRATION_FIELD_NAMES,
    INTEGRATION_PRIMARY_SOURCE,
    NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS,
    TABLE_PATTERNS,
    to_marketing_analytics_data,
)


class TestMarketingAnalyticsConstantsCoverage:
    def test_config_models_covers_all_sources(self):
        all_sources = set(NativeMarketingSource)
        covered_sources = set(_CONFIG_MODELS.keys())
        missing = all_sources - covered_sources
        assert covered_sources == all_sources, f"Missing sources in _CONFIG_MODELS: {missing}"

    def test_default_sources_enums_covers_all_sources(self):
        all_sources = set(NativeMarketingSource)
        covered_sources = set(_DEFAULT_SOURCES_ENUMS.keys())
        missing = all_sources - covered_sources
        assert covered_sources == all_sources, f"Missing sources in _DEFAULT_SOURCES_ENUMS: {missing}"

    def test_integration_default_sources_covers_all_sources(self):
        all_sources = set(NativeMarketingSource)
        covered_sources = set(INTEGRATION_DEFAULT_SOURCES.keys())
        missing = all_sources - covered_sources
        assert covered_sources == all_sources, f"Missing sources in INTEGRATION_DEFAULT_SOURCES: {missing}"

    def test_integration_field_names_covers_all_sources(self):
        all_sources = set(NativeMarketingSource)
        covered_sources = set(INTEGRATION_FIELD_NAMES.keys())
        missing = all_sources - covered_sources
        assert covered_sources == all_sources, f"Missing sources in INTEGRATION_FIELD_NAMES: {missing}"

    def test_integration_primary_source_covers_all_sources(self):
        all_sources = set(NativeMarketingSource)
        covered_sources = set(INTEGRATION_PRIMARY_SOURCE.keys())
        missing = all_sources - covered_sources
        assert covered_sources == all_sources, f"Missing sources in INTEGRATION_PRIMARY_SOURCE: {missing}"

    def test_needed_fields_covers_all_sources(self):
        all_sources = set(NativeMarketingSource)
        covered_sources = set(NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS.keys())
        missing = all_sources - covered_sources
        assert covered_sources == all_sources, (
            f"Missing sources in NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS: {missing}"
        )

    def test_table_patterns_covers_all_sources(self):
        all_sources = set(NativeMarketingSource)
        covered_sources = set(TABLE_PATTERNS.keys())
        missing = all_sources - covered_sources
        assert covered_sources == all_sources, f"Missing sources in TABLE_PATTERNS: {missing}"


class TestMarketingAnalyticsConstantsStructure:
    @parameterized.expand([(source,) for source in NativeMarketingSource])
    def test_integration_field_names_has_required_fields(self, source):
        field_names = INTEGRATION_FIELD_NAMES[source]
        assert "name_field" in field_names, f"{source}: missing 'name_field'"
        assert "id_field" in field_names, f"{source}: missing 'id_field'"
        assert field_names["name_field"], f"{source}: 'name_field' is empty"
        assert field_names["id_field"], f"{source}: 'id_field' is empty"

    @parameterized.expand([(source,) for source in NativeMarketingSource])
    def test_integration_default_sources_is_non_empty_list(self, source):
        sources = INTEGRATION_DEFAULT_SOURCES[source]
        assert isinstance(sources, list), f"{source}: expected list, got {type(sources)}"
        assert len(sources) > 0, f"{source}: default sources list is empty"
        for s in sources:
            assert isinstance(s, str), f"{source}: source '{s}' is not a string"
            assert s, f"{source}: contains empty string"

    @parameterized.expand([(source,) for source in NativeMarketingSource])
    def test_integration_primary_source_is_in_default_sources(self, source):
        primary = INTEGRATION_PRIMARY_SOURCE[source]
        defaults = INTEGRATION_DEFAULT_SOURCES[source]
        assert primary in defaults, f"{source}: primary source '{primary}' not in default sources {defaults}"

    @parameterized.expand([(source,) for source in NativeMarketingSource])
    def test_needed_fields_has_two_tables(self, source):
        tables = NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS[source]
        assert isinstance(tables, list), f"{source}: expected list, got {type(tables)}"
        assert len(tables) == 2, f"{source}: expected 2 tables, got {len(tables)}"
        for table in tables:
            assert isinstance(table, str), f"{source}: table '{table}' is not a string"
            assert table, f"{source}: contains empty table name"

    @parameterized.expand([(source,) for source in NativeMarketingSource])
    def test_table_patterns_has_required_keys(self, source):
        patterns = TABLE_PATTERNS[source]
        stats_keywords = patterns["stats_table_keywords"]
        assert isinstance(stats_keywords, list), f"{source}: 'stats_table_keywords' should be a list"
        assert len(stats_keywords) > 0, f"{source}: 'stats_table_keywords' is empty"

        campaign_table_name = patterns["campaign_table_name"]
        assert isinstance(campaign_table_name, str), f"{source}: 'campaign_table_name' should be a string"
        assert campaign_table_name, f"{source}: 'campaign_table_name' is empty"


class TestMarketingAnalyticsConstantsConsistency:
    @parameterized.expand([(source,) for source in NativeMarketingSource])
    def test_stats_table_name_matches_pattern(self, source):
        needed_fields = NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS[source]
        patterns = TABLE_PATTERNS[source]
        stats_table = needed_fields[1]
        stats_keywords = patterns["stats_table_keywords"]
        assert stats_table in stats_keywords, f"{source}: stats table '{stats_table}' not in keywords {stats_keywords}"

    @parameterized.expand([(source,) for source in NativeMarketingSource])
    def test_primary_source_is_non_empty_string(self, source):
        primary = INTEGRATION_PRIMARY_SOURCE[source]
        assert isinstance(primary, str), f"{source}: primary source should be string"
        assert primary, f"{source}: primary source is empty"


class TestToMarketingAnalyticsData:
    COST = MarketingAnalyticsBaseColumns.COST.value
    CAMPAIGN = MarketingAnalyticsBaseColumns.CAMPAIGN.value
    CTR = MarketingAnalyticsBaseColumns.CTR.value
    AD_ID = MarketingAnalyticsBaseColumns.AD_ID.value

    @parameterized.expand(
        [
            # name, key, value, previous, kind, is_increase_bad, out_value, out_previous, out_change
            ("cost_column", COST, 150.0, 100.0, "currency", True, 150.0, 100.0, 50),
            ("dimension_column", CAMPAIGN, "Summer sale", None, "unit", False, "Summer sale", None, None),
            ("ctr_is_percentage", CTR, 2.5, 2.0, "percentage", False, 2.5, 2.0, 25),
            ("cost_per_conversion", "Cost per Signup", 10.0, 8.0, "currency", True, 10.0, 8.0, 25),
            ("conversion_goal", "Signup", 12.0, 10.0, "unit", False, 12.0, 10.0, 20),
            # List values from tuple queries are unwrapped to their first element.
            ("list_unwrap", COST, [42.0], [40.0], "currency", True, 42.0, 40.0, 5),
            ("empty_list", COST, [], None, "currency", True, None, None, None),
            # NaN numbers become None.
            ("nan_cleanup", COST, math.nan, 5.0, "currency", True, None, 5.0, None),
            # ID columns keep their string so the frontend can format them compactly.
            ("id_stays_string", AD_ID, "120000000000000", None, "unit", False, "120000000000000", None, None),
            # Numeric columns coerce string values to int or float.
            ("coerce_int", COST, "42", "40", "currency", True, 42, 40, 5),
            ("coerce_float", COST, "42.5", "40.0", "currency", True, 42.5, 40.0, 6),
            ("coerce_unparsable", COST, "n/a", None, "currency", True, None, None, None),
            # Zero-baseline sentinels.
            ("zero_to_zero", COST, 0.0, 0.0, "currency", True, 0.0, 0.0, 0),
            ("zero_to_positive", COST, 5.0, 0.0, "currency", True, 5.0, 0.0, 999999),
            ("zero_to_negative", COST, -5.0, 0.0, "currency", True, -5.0, 0.0, -999999),
        ]
    )
    def test_transform(self, _name, key, value, previous, kind, is_increase_bad, out_value, out_previous, out_change):
        item = to_marketing_analytics_data(key, value, previous)

        assert item.key == key
        assert item.kind == WebAnalyticsItemKind(kind)
        assert item.isIncreaseBad == is_increase_bad
        assert item.value == out_value
        assert item.previous == out_previous
        assert item.changeFromPreviousPct == out_change

    def test_has_comparison_flag_passes_through(self):
        assert to_marketing_analytics_data(self.COST, 1.0, 1.0, has_comparison=True).hasComparison is True
        assert to_marketing_analytics_data(self.COST, 1.0, 1.0).hasComparison is False
