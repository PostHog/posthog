from typing import Optional, cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.appsignal.appsignal import (
    AppsignalResumeConfig,
    appsignal_source,
    validate_credentials as validate_appsignal_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appsignal.settings import (
    APPSIGNAL_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AppsignalSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AppsignalSource(ResumableSource[AppsignalSourceConfig, AppsignalResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.APPSIGNAL

    @property
    def connection_host_fields(self) -> list[str]:
        # app_id selects which AppSignal app the stored token is used against; changing it must
        # require re-entering the secret so a preserved token can't be retargeted at another app.
        return ["app_id"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://appsignal.com": "Your AppSignal personal API token is invalid or has been revoked. Copy a fresh token from your AppSignal personal settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://appsignal.com": "Your AppSignal personal API token does not have access to this app. Check the token and app ID, then reconnect.",
            "404 Client Error: Not Found for url: https://appsignal.com": "AppSignal app not found. Check that the app ID matches the ID in your AppSignal app's URL.",
            "AppSignal app not found": "AppSignal app not found. Check that the app ID matches the ID in your AppSignal app's URL.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.APPSIGNAL,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="AppSignal",
            caption="""Enter your AppSignal personal API token and app ID to pull your AppSignal error and performance data into the PostHog Data warehouse.

Your personal API token is in your [AppSignal personal settings](https://appsignal.com/users/edit) under "API key". The app ID is the identifier in your app's AppSignal URL: `https://appsignal.com/<organization>/sites/<app ID>`.""",
            iconPath="/static/services/appsignal.png",
            docsUrl="https://posthog.com/docs/cdp/sources/appsignal",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["apm", "error tracking", "monitoring"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Personal API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="app_id",
                        label="App ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.appsignal.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AppsignalSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint) is not None,
                # Only immutable rows (samples) may append; deploy markers mutate after
                # creation, so incremental syncs must merge on the primary key.
                supports_append=APPSIGNAL_ENDPOINTS[endpoint].immutable_rows,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: AppsignalSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_appsignal_credentials(config.api_token, config.app_id):
            return True, None

        return False, "Invalid AppSignal personal API token or app ID"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AppsignalResumeConfig]:
        return ResumableSourceManager[AppsignalResumeConfig](inputs, AppsignalResumeConfig)

    def source_for_pipeline(
        self,
        config: AppsignalSourceConfig,
        resumable_source_manager: ResumableSourceManager[AppsignalResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return appsignal_source(
            api_token=config.api_token,
            app_id=config.app_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
