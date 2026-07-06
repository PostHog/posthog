from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.concord.concord import (
    ConcordResumeConfig,
    concord_source,
    validate_credentials as validate_concord_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.concord.settings import (
    CONCORD_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ConcordSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ConcordSource(ResumableSource[ConcordSourceConfig, ConcordResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def connection_host_fields(self) -> list[str]:
        # `environment` selects which Concord host the stored API key is sent to, and
        # `organization_id` scopes which organization's data that key reads. Retargeting either
        # without re-entering the key would let an editor exfiltrate the preserved credential or
        # pull another organization's data, so both must force secret re-entry on update.
        return ["environment", "organization_id"]

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CONCORD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CONCORD,
            category=DataWarehouseSourceCategory.SALES,
            label="Concord",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Concord API key to pull your contract lifecycle data into the PostHog Data warehouse.

You can generate an API key in your Concord account settings (API key generation requires a paid plan). Concord sends it as an `X-API-KEY` header.

Leave **Organization ID** blank to use the first organization your API key can access.""",
            iconPath="/static/services/concord.png",
            docsUrl="https://posthog.com/docs/cdp/sources/concord",
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
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue="production",
                        options=[
                            SourceFieldSelectConfigOption(label="Production", value="production"),
                            SourceFieldSelectConfigOption(label="Sandbox", value="sandbox"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="organization_id",
                        label="Organization ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="Leave blank to use your first organization",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.concord.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.concordnow.com": "Your Concord API key is invalid or has been revoked. Generate a new key in your Concord account settings, then reconnect.",
            "401 Client Error: Unauthorized for url: https://uat.concordnow.com": "Your Concord API key is invalid or has been revoked. Generate a new key in your Concord account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.concordnow.com": "Your Concord API key is missing the permissions needed to sync this data (the events log requires the Administrator role). Adjust the key's access, then reconnect.",
            "403 Client Error: Forbidden for url: https://uat.concordnow.com": "Your Concord API key is missing the permissions needed to sync this data (the events log requires the Administrator role). Adjust the key's access, then reconnect.",
        }

    def get_schemas(
        self,
        config: ConcordSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = CONCORD_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_append or endpoint_config.supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                description=endpoint_config.description,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: ConcordSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_concord_credentials(config.api_key, config.environment):
            return True, None
        return False, "Invalid Concord API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ConcordResumeConfig]:
        return ResumableSourceManager[ConcordResumeConfig](inputs, ConcordResumeConfig)

    def source_for_pipeline(
        self,
        config: ConcordSourceConfig,
        resumable_source_manager: ResumableSourceManager[ConcordResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return concord_source(
            api_key=config.api_key,
            environment=config.environment,
            organization_id=config.organization_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
