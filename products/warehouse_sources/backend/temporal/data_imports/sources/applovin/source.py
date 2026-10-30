from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.applovin import (
    AUTH_ERROR_PREFIX,
    BAD_REQUEST_ERROR_PREFIX,
    MANAGEMENT_AUTH_ERROR_PREFIX,
    MANAGEMENT_CREDENTIALS_MISSING_PREFIX,
    AppLovinResumeConfig,
    applovin_source,
    validate_credentials as validate_applovin_credentials,
    validate_management_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    MANAGEMENT_ENDPOINTS,
    MERGE_ONLY_ENDPOINTS,
    PRIMARY_KEYS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.applovin import (
    AppLovinSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AppLovinSource(ResumableSource[AppLovinSourceConfig, AppLovinResumeConfig]):
    codebase_detection = detect(
        env=("^(APP_LOVIN|APPLOVIN)_",),
        npm=("react-native-applovin-max",),
        cocoapods=(
            "AppLovinSDK",
            "AppLovin",
            "AppLovin-SDK",
            "AppLovinMediationAmazonAdapter",
            "AppLovinMediationByteDanceAdapter",
            "AppLovinMediationChartboostAdapter",
            "AppLovinMediationFacebookAdapter",
            "AppLovinMediationGoogleAdapter",
            "AppLovinMediationHyprMXAdapter",
            "AppLovinMediationIronSourceAdapter",
            "AppLovinMediationMoPubAdapter",
            "AppLovinMediationSnapAdapter",
            "AppLovinMediationTapjoyAdapter",
            "AppLovinMediationUnityAdsAdapter",
            "AppLovinMediationVungleAdapter",
        ),
        maven=("com.applovin:applovin-sdk", "com.applovin:applovin-signal-provider-sdk"),
        pub=("applovin_max",),
        swiftpm=(
            "github.com/applovin/applovin-max-swift-package",
            "github.com/applovin/applovin-max-swift-package-amazonadmarketplace",
            "github.com/applovin/applovin-max-swift-package-bidmachine",
            "github.com/applovin/applovin-max-swift-package-bigoads",
            "github.com/applovin/applovin-max-swift-package-chartboost",
            "github.com/applovin/applovin-max-swift-package-fyber",
            "github.com/applovin/applovin-max-swift-package-google",
            "github.com/applovin/applovin-max-swift-package-googleadsmanager",
            "github.com/applovin/applovin-max-swift-package-inmobi",
            "github.com/applovin/applovin-max-swift-package-ironsource",
            "github.com/applovin/applovin-max-swift-package-liftoff",
            "github.com/applovin/applovin-max-swift-package-line",
            "github.com/applovin/applovin-max-swift-package-meta",
            "github.com/applovin/applovin-max-swift-package-mintegral",
            "github.com/applovin/applovin-max-swift-package-mobilefuse",
            "github.com/applovin/applovin-max-swift-package-moloco",
            "github.com/applovin/applovin-max-swift-package-mytarget",
            "github.com/applovin/applovin-max-swift-package-ogury",
            "github.com/applovin/applovin-max-swift-package-pangle",
            "github.com/applovin/applovin-max-swift-package-pubmatic",
            "github.com/applovin/applovin-max-swift-package-smaato",
            "github.com/applovin/applovin-max-swift-package-unityads",
            "github.com/applovin/applovin-max-swift-package-verve",
            "github.com/applovin/applovin-max-swift-package-yandex",
            "github.com/applovin/applovin-max-swift-package-ysonetwork",
        ),
    )

    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs
    # The reporting endpoints under r.applovin.com carry no version token of any kind.
    api_docs_url = "https://support.applovin.com/en/max/reporting-apis/revenue-reporting-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.APPLOVIN

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            AUTH_ERROR_PREFIX: "AppLovin rejected your Report Key. Generate a new one under your account menu > Keys in the AppLovin dashboard, then reconnect.",
            BAD_REQUEST_ERROR_PREFIX: "AppLovin rejected the report request. This usually means your account can't access the requested report.",
            MANAGEMENT_AUTH_ERROR_PREFIX: "AppLovin rejected your Campaign Management API key or account ID. Check both under your account menu in the AppLovin dashboard, then update this source.",
            MANAGEMENT_CREDENTIALS_MISSING_PREFIX: "Campaign tables need a Campaign Management API key and account ID. Add both to this source, then sync again.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.APPLOVIN,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="AppLovin",
            caption="""Connect your AppLovin account to pull MAX mediation revenue, campaign spend, and cohort reporting into the PostHog Data warehouse.

Find your **Report Key** in the AppLovin dashboard: click your account in the top right, then **Keys**.

To sync campaigns, creative sets, and campaign operation logs, also add your **Campaign Management API key** (under **Keys**) and your **account ID** (under **Go to settings**, the number after your account name).

AppLovin only serves the last 45 days of report data and the last 30 days of campaign operation logs, so anything older than that can't be backfilled.""",
            iconPath="/static/services/applovin.png",
            docsUrl="https://posthog.com/docs/cdp/sources/applovin",
            releaseStatus=ReleaseStatus.GA,
            keywords=["max", "appdiscovery", "axon", "mobile ads"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Report Key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="campaign_api_key",
                        label="Campaign Management API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="123456",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: AppLovinSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=MERGE_ONLY_ENDPOINTS)
        for schema in schemas:
            schema.detected_primary_keys = list(PRIMARY_KEYS[schema.name])
        return schemas

    def get_endpoint_permissions(
        self, config: AppLovinSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        missing = "Add a Campaign Management API key and account ID to this source to sync this table."
        has_management_credentials = bool(config.campaign_api_key and config.account_id)
        return {
            endpoint: missing if endpoint in MANAGEMENT_ENDPOINTS and not has_management_credentials else None
            for endpoint in endpoints
        }

    def validate_credentials(
        self,
        config: AppLovinSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not validate_applovin_credentials(config.api_key):
            return (
                False,
                "AppLovin rejected your Report Key. Copy it again from your account menu > Keys in the AppLovin dashboard, then reconnect.",
            )

        if schema_name is not None and schema_name not in MANAGEMENT_ENDPOINTS:
            return True, None

        if bool(config.campaign_api_key) != bool(config.account_id):
            return False, "Enter both the Campaign Management API key and the account ID, or leave both empty."

        if config.campaign_api_key and config.account_id:
            if not validate_management_credentials(config.campaign_api_key, config.account_id):
                return (
                    False,
                    "AppLovin rejected your Campaign Management API key or account ID. Check both under your account menu in the AppLovin dashboard, then reconnect.",
                )
        elif schema_name in MANAGEMENT_ENDPOINTS:
            return False, "Add a Campaign Management API key and account ID to sync this table."

        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AppLovinResumeConfig]:
        return ResumableSourceManager[AppLovinResumeConfig](inputs, AppLovinResumeConfig)

    def source_for_pipeline(
        self,
        config: AppLovinSourceConfig,
        resumable_source_manager: ResumableSourceManager[AppLovinResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return applovin_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            campaign_api_key=config.campaign_api_key,
            account_id=config.account_id,
        )
