from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.openai_ads.source import OpenAIAdsSource

_ENTITY_ENDPOINTS = ["campaigns", "ad_groups", "ads"]
_INSIGHTS_ENDPOINTS = ["campaign_insights", "ad_group_insights", "ad_insights", "ad_account_insights"]


class TestOpenAIAdsSchemas:
    def test_all_endpoints_present(self) -> None:
        names = {s.name for s in OpenAIAdsSource().get_schemas(MagicMock(), team_id=1)}
        assert names == {*_ENTITY_ENDPOINTS, *_INSIGHTS_ENDPOINTS}

    @parameterized.expand([(endpoint,) for endpoint in _INSIGHTS_ENDPOINTS])
    def test_insights_are_incremental_on_start_time_with_lookback(self, endpoint: str) -> None:
        # Insights have a genuine server-side time filter (time_ranges[]); recent buckets get
        # restated, so a trailing lookback re-reads them and merge dedupes.
        schema = next(s for s in OpenAIAdsSource().get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is True
        assert schema.supports_append is False
        assert [f["field"] for f in schema.incremental_fields] == ["start_time"]
        assert schema.default_incremental_lookback_seconds == 60 * 60 * 24 * 3

    @parameterized.expand([(endpoint,) for endpoint in _ENTITY_ENDPOINTS])
    def test_entity_endpoints_are_full_refresh_only(self, endpoint: str) -> None:
        # The list endpoints have no server-side date filter, so they must not advertise incremental.
        schema = next(s for s in OpenAIAdsSource().get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is False
        assert schema.supports_append is False

    def test_names_filter(self) -> None:
        schemas = OpenAIAdsSource().get_schemas(MagicMock(), team_id=1, names=["campaigns"])
        assert [s.name for s in schemas] == ["campaigns"]
