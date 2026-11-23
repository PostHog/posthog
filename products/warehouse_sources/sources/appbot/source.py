from typing import Optional, cast

from products.warehouse_sources.sources.appbot._config import AppbotSourceConfig
from products.warehouse_sources.sources.appbot.appbot import (
    AppbotResumeConfig,
    appbot_source,
    validate_credentials as validate_appbot_credentials,
)
from products.warehouse_sources.sources.appbot.settings import APPBOT_V2, ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceKey,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
    detect,
    source_key,
)

SOURCE_KEY = "Appbot"


@SourceRegistry.register
class AppbotSource(ResumableSource[AppbotSourceConfig, AppbotResumeConfig]):
    codebase_detection = detect(env=("^APPBOT_",))

    lists_tables_without_credentials = True
    # The version is the `/api/v2` path segment. Appbot answers `/api/v1` with 410 Gone.
    supported_versions = (APPBOT_V2,)
    default_version = APPBOT_V2
    api_docs_url = "https://app.appbot.co/api"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.ANALYTICS,
            keywords=["app reviews", "app ratings", "app store ratings"],
            label="Appbot",
            releaseStatus=ReleaseStatus.BETA,
            caption="""Enter your Appbot API username and password to pull your apps, reviews and star ratings into the PostHog Data warehouse.

The Appbot API is a paid add-on, available on the Large and Premium plans. When your team has it, find the API username and password on the [API page](https://app.appbot.co/api) in Appbot.

Appbot allows 20 API requests a minute, so the first sync of an app with a long review history can take a while.
""",
            iconPath="/static/warehouse-sources/appbot/icon.png",
            docsUrl="https://posthog.com/docs/cdp/sources/appbot",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_username",
                        label="API username",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="Your Appbot API username",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_password",
                        label="API password",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Your Appbot API password",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.appbot.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AppbotSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Incremental runs read a lookback window again, which append would store twice.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=("reviews", "ratings"))

    def validate_credentials(
        self,
        config: AppbotSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_appbot_credentials(config.api_username, config.api_password)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.appbot.co": "Appbot didn't accept your API username and password. Check them on the API page in Appbot, then reconnect the source.",
            "403 Client Error: Forbidden for url: https://api.appbot.co": "Appbot refused access with your API credentials. Check that your Appbot plan includes the API add-on, then reconnect the source.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AppbotResumeConfig]:
        return ResumableSourceManager[AppbotResumeConfig](inputs, AppbotResumeConfig)

    def source_for_pipeline(
        self,
        config: AppbotSourceConfig,
        resumable_source_manager: ResumableSourceManager[AppbotResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return appbot_source(
            username=config.api_username,
            password=config.api_password,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
