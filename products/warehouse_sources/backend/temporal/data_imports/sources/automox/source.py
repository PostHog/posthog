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
from products.warehouse_sources.backend.temporal.data_imports.sources.automox.automox import (
    MULTIPLE_ORGS_ERROR,
    ORG_NOT_FOUND_ERROR,
    AutomoxResumeConfig,
    automox_source,
    validate_credentials as validate_automox_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.automox.settings import (
    AUTOMOX_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AutomoxSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AutomoxSource(ResumableSource[AutomoxSourceConfig, AutomoxResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AUTOMOX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AUTOMOX,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Automox",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Automox API key to sync your patch management and device compliance data into the PostHog Data warehouse.

Create an API key in the Automox console under **Settings → API Keys**, then paste it here.

If your API key has access to more than one organization, also enter the numeric organization ID (visible in **Settings → Organization**) the source should sync.""",
            iconPath="/static/services/automox.png",
            docsUrl="https://posthog.com/docs/cdp/sources/automox",
            keywords=["patch management", "endpoint management", "device compliance"],
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
                    SourceFieldInputConfig(
                        name="organization_id",
                        label="Organization ID (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.automox.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or expired API key surfaces as a requests HTTPError when `_fetch_json`
            # calls `raise_for_status()`. Retrying can never satisfy a credential problem, so stop
            # the sync. Match the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://console.automox.com": "Your Automox API key is invalid or has expired. Create a new key under Settings → API Keys in the Automox console, then reconnect.",
            "403 Client Error: Forbidden for url: https://console.automox.com": "Your Automox API key does not have permission to read this data. Check the key's permissions, then reconnect.",
            ORG_NOT_FOUND_ERROR: "The configured organization ID is not accessible with this API key. Check the organization ID on the source, then try again.",
            MULTIPLE_ORGS_ERROR: "Your Automox API key has access to multiple organizations. Set the organization ID on the source to pick which one to sync.",
        }

    def get_schemas(
        self,
        config: AutomoxSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=len(AUTOMOX_ENDPOINTS[endpoint].incremental_fields) > 0,
                supports_append=len(AUTOMOX_ENDPOINTS[endpoint].incremental_fields) > 0,
                incremental_fields=AUTOMOX_ENDPOINTS[endpoint].incremental_fields,
                detected_primary_keys=AUTOMOX_ENDPOINTS[endpoint].primary_keys,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: AutomoxSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_automox_credentials(config.api_key, config.organization_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AutomoxResumeConfig]:
        return ResumableSourceManager[AutomoxResumeConfig](inputs, AutomoxResumeConfig)

    def source_for_pipeline(
        self,
        config: AutomoxSourceConfig,
        resumable_source_manager: ResumableSourceManager[AutomoxResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return automox_source(
            api_key=config.api_key,
            organization_id=config.organization_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
