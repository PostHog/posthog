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
from products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory.ezofficeinventory import (
    EZOfficeInventoryResumeConfig,
    ezofficeinventory_source,
    validate_credentials as validate_ezofficeinventory_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory.settings import (
    ENDPOINTS,
    EZOFFICEINVENTORY_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    EZOfficeInventorySourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class EZOfficeInventorySource(ResumableSource[EZOfficeInventorySourceConfig, EZOfficeInventoryResumeConfig]):
    # `get_schemas` iterates a static endpoint catalog with no I/O, so the table list is safe to
    # render in public docs without credentials.
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EZOFFICEINVENTORY

    @property
    def connection_host_fields(self) -> list[str]:
        # The access token is sent to <subdomain>.ezofficeinventory.com, so retargeting the
        # subdomain must re-require the token.
        return ["subdomain"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Your EZOfficeInventory access token is invalid or expired. Please generate a new token and reconnect.",
            "403 Client Error: Forbidden for url": "Your EZOfficeInventory access token does not have the required permissions, or API access is disabled for the account.",
            "Unauthorized for url": "Your EZOfficeInventory access token is invalid or expired. Please generate a new token and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: EZOfficeInventorySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                detected_primary_keys=EZOFFICEINVENTORY_ENDPOINTS[endpoint].primary_keys,
                should_sync_default=EZOFFICEINVENTORY_ENDPOINTS[endpoint].should_sync_default,
            )
            for endpoint in list(ENDPOINTS)
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: EZOfficeInventorySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        is_valid, error_message = validate_ezofficeinventory_credentials(config.api_key, config.subdomain)
        if is_valid:
            return True, None

        return (
            False,
            error_message
            or "Invalid EZOfficeInventory credentials. Check the subdomain and access token, and that API access is enabled in Settings.",
        )

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[EZOfficeInventoryResumeConfig]:
        return ResumableSourceManager[EZOfficeInventoryResumeConfig](inputs, EZOfficeInventoryResumeConfig)

    def source_for_pipeline(
        self,
        config: EZOfficeInventorySourceConfig,
        resumable_source_manager: ResumableSourceManager[EZOfficeInventoryResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return ezofficeinventory_source(
            api_key=config.api_key,
            subdomain=config.subdomain,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.EZ_OFFICE_INVENTORY,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="EZOfficeInventory",
            caption=(
                "Enter your EZOfficeInventory subdomain and access token. Enable API access in "
                "**Settings → Integrations → API Integration** and generate a token there. All tables "
                "sync via full refresh — the API exposes no general server-side `updated_after` cursor."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/ezofficeinventory",
            iconPath="/static/services/ezofficeinventory.svg",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="your-company",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
