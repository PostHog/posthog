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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OnfleetSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.onfleet.onfleet import (
    OnfleetResumeConfig,
    get_credentials_status,
    onfleet_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onfleet.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    ONFLEET_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OnfleetSource(ResumableSource[OnfleetSourceConfig, OnfleetResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ONFLEET

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ONFLEET,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Onfleet",
            caption="""Enter your Onfleet API key to pull your Onfleet last-mile delivery data into the PostHog Data warehouse.

You can create an API key in your [Onfleet dashboard](https://onfleet.com/dashboard#/manage) under **Settings → API & Webhooks**. Onfleet API keys are org-scoped and grant read access to your organization's data.""",
            iconPath="/static/services/onfleet.png",
            docsUrl="https://posthog.com/docs/cdp/sources/onfleet",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
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

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.onfleet.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://onfleet.com": "Your Onfleet API key is invalid or has been revoked. Create a new API key in your Onfleet dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://onfleet.com": "Your Onfleet API key does not have permission to read this data. Check the key's permissions in your Onfleet dashboard, then reconnect.",
        }

    def get_schemas(
        self,
        config: OnfleetSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=ONFLEET_ENDPOINTS[endpoint].should_sync_default,
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: OnfleetSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        status = get_credentials_status(config.api_key)
        if status == 200:
            return True, None
        # A 403 at source-create means the token is genuine but scoped; accept it so users can
        # still connect a restricted key. Only reject 403 when validating a specific schema.
        if status == 403 and schema_name is None:
            return True, None
        if status in (401, 403):
            return False, "Invalid or unauthorized Onfleet API key"
        return False, "Could not validate Onfleet API key. Please try again."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OnfleetResumeConfig]:
        return ResumableSourceManager[OnfleetResumeConfig](inputs, OnfleetResumeConfig)

    def source_for_pipeline(
        self,
        config: OnfleetSourceConfig,
        resumable_source_manager: ResumableSourceManager[OnfleetResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return onfleet_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
