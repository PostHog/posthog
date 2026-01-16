from parameterized import parameterized

from posthog.schema import NativeMarketingSource

from .constants import (
    _CONFIG_MODELS,
    _DEFAULT_SOURCES_ENUMS,
    _TABLE_EXCLUSIONS_ENUMS,
    _TABLE_KEYWORDS_ENUMS,
    INTEGRATION_DEFAULT_SOURCES,
    INTEGRATION_FIELD_NAMES,
    INTEGRATION_PRIMARY_SOURCE,
    NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS,
    TABLE_PATTERNS,
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

    def test_table_keywords_enums_covers_all_sources(self):
        all_sources = set(NativeMarketingSource)
        covered_sources = set(_TABLE_KEYWORDS_ENUMS.keys())
        missing = all_sources - covered_sources
        assert covered_sources == all_sources, f"Missing sources in _TABLE_KEYWORDS_ENUMS: {missing}"

    def test_table_exclusions_enums_covers_all_sources(self):
        all_sources = set(NativeMarketingSource)
        covered_sources = set(_TABLE_EXCLUSIONS_ENUMS.keys())
        missing = all_sources - covered_sources
        assert covered_sources == all_sources, f"Missing sources in _TABLE_EXCLUSIONS_ENUMS: {missing}"

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
        required_keys = ["campaign_table_keywords", "campaign_table_exclusions", "stats_table_keywords"]
        for key in required_keys:
            assert key in patterns, f"{source}: missing '{key}'"
            assert isinstance(patterns[key], list), f"{source}: '{key}' should be a list"
            assert len(patterns[key]) > 0, f"{source}: '{key}' is empty"


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
