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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import WrikeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.wrike.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.wrike.wrike import (
    WrikeResumeConfig,
    validate_credentials as validate_wrike_credentials,
    wrike_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WrikeSource(ResumableSource[WrikeSourceConfig, WrikeResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WRIKE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WRIKE,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Wrike",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter a Wrike permanent access token to pull your Wrike data into the PostHog Data warehouse.

Create a permanent access token under **Apps & Integrations → API** in Wrike. The token needs read access (the default `Default` scope is sufficient) to the resources you want to sync.

Set **Host** to the domain shown in your browser when you're logged into Wrike (e.g. `www.wrike.com`, `app-us2.wrike.com`, or `app-eu.wrike.com`).""",
            iconPath="/static/services/wrike.png",
            docsUrl="https://posthog.com/docs/cdp/sources/wrike",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Permanent access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="host",
                        label="Host",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="www.wrike.com",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.wrike.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid or expired Wrike access token. Please generate a new token and reconnect.",
            "403 Client Error": "Your Wrike access token does not have the required permissions for this resource.",
        }

    def get_schemas(
        self,
        config: WrikeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Wrike's API has no reliably-verifiable server-side timestamp filter, so every endpoint
        # ships as full refresh (see settings.py for the rationale).
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: WrikeSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_wrike_credentials(config.access_token, config.host)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[WrikeResumeConfig]:
        return ResumableSourceManager[WrikeResumeConfig](inputs, WrikeResumeConfig)

    def source_for_pipeline(
        self,
        config: WrikeSourceConfig,
        resumable_source_manager: ResumableSourceManager[WrikeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return wrike_source(
            access_token=config.access_token,
            host=config.host,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
