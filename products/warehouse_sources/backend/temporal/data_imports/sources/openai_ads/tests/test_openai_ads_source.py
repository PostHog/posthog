from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceFieldInputConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.openai_ads.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openai_ads.openai_ads import OpenAIAdsResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.openai_ads.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.openai_ads.source import OpenAIAdsSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_ENTITY_ENDPOINTS = ["campaigns", "ad_groups", "ads"]
_INSIGHTS_ENDPOINTS = ["campaign_insights", "ad_group_insights", "ad_insights", "ad_account_insights"]


class TestOpenAIAdsSourceConfig:
    def test_source_type(self) -> None:
        assert OpenAIAdsSource().source_type == ExternalDataSourceType.OPENAIADS

    def test_config_is_released_with_single_secret_api_key_field(self) -> None:
        config = OpenAIAdsSource().get_source_config
        assert config.name == SchemaExternalDataSourceType.OPEN_AI_ADS
        # A finished source must be visible: alpha-labelled, never hidden via unreleasedSource.
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/openai-ads"
        fields = [f for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert [f.name for f in fields] == ["api_key"]
        assert fields[0].secret is True and fields[0].required is True


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


class TestOpenAIAdsResumableManager:
    def test_manager_bound_to_resume_config(self) -> None:
        manager = OpenAIAdsSource().get_resumable_source_manager(MagicMock())
        assert manager._data_class is OpenAIAdsResumeConfig


class TestOpenAIAdsSourceForPipeline:
    @parameterized.expand(
        [
            ("campaigns", ["id"], ["created_at"], "asc"),
            ("ad_groups", ["campaign_id", "id"], ["created_at"], "asc"),
            ("ads", ["ad_group_id", "id"], ["created_at"], "asc"),
            # Insights row ordering within a window is unverified, so the watermark must only
            # commit at sync completion.
            ("campaign_insights", ["id"], ["start_time"], "desc"),
            ("ad_account_insights", ["id"], ["start_time"], "desc"),
        ]
    )
    def test_primary_keys_partitioning_and_sort_mode(
        self, endpoint: str, primary_keys: list[str], partition_keys: list[str], sort_mode: str
    ) -> None:
        inputs = MagicMock()
        inputs.schema_name = endpoint
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = None
        manager = MagicMock()
        manager.can_resume.return_value = False
        response = OpenAIAdsSource().source_for_pipeline(MagicMock(api_key="k"), manager, inputs)
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == partition_keys
        assert response.partition_mode == "datetime"
        assert response.sort_mode == sort_mode


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.ads.openai.com/v1/campaigns?limit=500",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.ads.openai.com/v1/ad_account/insights",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = OpenAIAdsSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.ads.openai.com', port=443): Read timed out."),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.ads.openai.com/v1/campaigns",
            ),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = OpenAIAdsSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestDocumentedTables:
    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        # The docs' Supported tables section keys canonical entries by endpoint name — a drifted
        # key silently loses its curated description.
        assert set(CANONICAL_DESCRIPTIONS.keys()) == set(ENDPOINTS)

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog => the source opts into publishing its table list to public docs.
        assert OpenAIAdsSource().lists_tables_without_credentials is True
        tables = OpenAIAdsSource().get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        campaign_insights = next(t for t in tables if t["name"] == "campaign_insights")
        assert "Incremental" in campaign_insights["sync_methods"]
        assert campaign_insights["description"]
