from typing import Optional, cast

import requests

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appstack.appstack import (
    AppstackResumeConfig,
    appstack_source,
    validate_credentials as validate_appstack_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appstack.settings import (
    DEFAULT_INCREMENTAL_LOOKBACK_SECONDS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appstack import (
    AppstackSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AppstackSource(ResumableSource[AppstackSourceConfig, AppstackResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.appstack.tech/api/export"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.APPSTACK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.APPSTACK,
            category=DataWarehouseSourceCategory.ADVERTISING,
            keywords=["mobile attribution", "mmp", "ad attribution"],
            label="Appstack",
            caption="""Enter your Appstack API key to pull your attributed mobile events into the PostHog Data warehouse.

You can find the API key in your Appstack dashboard settings. API keys are scoped to a single app, so add one source per app.""",
            iconPath="/static/services/appstack.png",
            docsUrl="https://posthog.com/docs/cdp/sources/appstack",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.appstack.tech": "Appstack rejected the API key. Copy the current API key for this app from your Appstack dashboard settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.appstack.tech": "Appstack denied access with this API key. Check that the key belongs to the app you want to sync, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.appstack.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AppstackSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            # The incremental lookback re-reads a trailing window each run, so append syncs would
            # duplicate the overlap; only merge dedupes it.
            merge_only=ENDPOINTS,
            descriptions={
                "events": (
                    "Attributed events for the connected app: installs and in-app events matched "
                    "to the ad campaigns that drove them"
                ),
            },
        )
        for schema in schemas:
            schema.default_incremental_lookback_seconds = DEFAULT_INCREMENTAL_LOOKBACK_SECONDS
        return schemas

    def validate_credentials(
        self,
        config: AppstackSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            if validate_appstack_credentials(config.api_key):
                return True, None
            return (
                False,
                "Appstack rejected the API key. Copy the current API key for this app from your Appstack dashboard settings.",
            )
        except requests.RequestException:
            # A rate-limit, 5xx, or network blip isn't a bad credential — don't mislabel it.
            return (
                False,
                "Could not reach Appstack to validate the API key. This may be a temporary issue — please try again.",
            )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AppstackResumeConfig]:
        return ResumableSourceManager[AppstackResumeConfig](inputs, AppstackResumeConfig)

    def source_for_pipeline(
        self,
        config: AppstackSourceConfig,
        resumable_source_manager: ResumableSourceManager[AppstackResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return appstack_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
