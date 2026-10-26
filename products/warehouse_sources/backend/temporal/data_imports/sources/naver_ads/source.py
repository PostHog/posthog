import datetime as dt
from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import NOT_DETECTABLE
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.naverads import (
    NaverAdsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.naver_ads.naver_ads import (
    NaverAdsResumeConfig,
    naver_ads_source,
    validate_credentials as validate_naver_ads_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.naver_ads.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    STATS_ENDPOINTS,
    STATS_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NaverAdsSource(ResumableSource[NaverAdsSourceConfig, NaverAdsResumeConfig]):
    codebase_detection = NOT_DETECTABLE
    lists_tables_without_credentials = True
    api_docs_url = "https://naver.github.io/searchad-apidoc/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NAVERADS

    def history_lookback_for_schema(
        self, schema_name: str, config: NaverAdsSourceConfig | None = None
    ) -> dt.timedelta | None:
        endpoint = ENDPOINTS.get(schema_name)
        if endpoint is None or endpoint.history_days is None:
            return None
        return dt.timedelta(days=endpoint.history_days)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.searchad.naver.com": (
                "Naver rejected your API credentials. Check the API license, secret key and customer ID, then reconnect the source."
            ),
            "403 Client Error: Forbidden for url: https://api.searchad.naver.com": (
                "Your Naver API license can't read this ad account. Check that the customer ID belongs to the account that issued the license."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.naver_ads.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: NaverAdsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Restated days come back on later syncs, so stats tables merge on (id, date) and never append.
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            merge_only=STATS_ENDPOINTS,
            default_incremental_lookback_seconds=dict.fromkeys(STATS_ENDPOINTS, STATS_LOOKBACK_SECONDS),
        )

    def validate_credentials(
        self,
        config: NaverAdsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not config.customer_id.strip().isdigit():
            return False, "The customer ID is the number shown next to your account name in Search Ad Manager."
        return validate_naver_ads_credentials(config)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[NaverAdsResumeConfig]:
        return ResumableSourceManager[NaverAdsResumeConfig](inputs, NaverAdsResumeConfig)

    def source_for_pipeline(
        self,
        config: NaverAdsSourceConfig,
        resumable_source_manager: ResumableSourceManager[NaverAdsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return naver_ads_source(config, inputs, resumable_source_manager)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NAVERADS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Naver Ads",
            keywords=["naver search ad", "searchad", "powerlink"],
            caption=(
                "Import campaigns, ad groups, ads, keywords and daily performance from Naver Search Ads. "
                "In [Search Ad Manager](https://manage.searchad.naver.com), open **Tools > API Manager**, "
                "create an API license and paste the API license, secret key and customer ID below."
            ),
            iconPath="/static/services/naver_ads.png",
            docsUrl="https://posthog.com/docs/cdp/sources/naver-ads",
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API license",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="secret_key",
                        label="Secret key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="customer_id",
                        label="Customer ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="1234567",
                        secret=False,
                    ),
                ],
            ),
        )
