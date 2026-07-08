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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PlausibleSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.plausible.plausible import (
    PlausibleResumeConfig,
    hostname_of,
    plausible_source,
    validate_credentials as validate_plausible_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.plausible.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PLAUSIBLE_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PlausibleSource(ResumableSource[PlausibleSourceConfig, PlausibleResumeConfig], ValidateDatabaseHostMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PLAUSIBLE

    @property
    def connection_host_fields(self) -> list[str]:
        # `host` determines where the stored API key is sent; retargeting it must re-require the key.
        return ["host"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Plausible API key is invalid or has been revoked. Create a new key in your Plausible account settings, then reconnect.",
            "403 Client Error": "Your Plausible API key is missing the stats read scope needed to sync this data. Grant it in your Plausible account settings, then reconnect.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PLAUSIBLE,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Plausible",
            caption="""Connect Plausible Analytics to pull your web analytics into the PostHog Data warehouse.

Works with Plausible Cloud and self-hosted instances. Create an API key under **Account settings → API keys** with the `stats read` scope, then enter your site's domain (e.g. `example.com`). Leave the host blank for Plausible Cloud, or set it to your instance URL for self-hosted (e.g. `https://plausible.example.com`).""",
            iconPath="/static/services/plausible.png",
            docsUrl="https://posthog.com/docs/cdp/sources/plausible",
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
                    SourceFieldInputConfig(
                        name="site_id",
                        label="Site domain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="example.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="host",
                        label="Host (self-hosted only)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://plausible.io",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.plausible.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: PlausibleSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            incremental_fields = INCREMENTAL_FIELDS.get(endpoint)
            return SourceSchema(
                name=endpoint,
                # date_range is a genuine server-side filter, so every report supports incremental
                # syncing by sliding the window forward.
                supports_incremental=incremental_fields is not None,
                supports_append=incremental_fields is not None,
                incremental_fields=incremental_fields or [],
                should_sync_default=PLAUSIBLE_ENDPOINTS[endpoint].should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: PlausibleSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            host_valid, host_error = self.is_database_host_valid(hostname_of(config.host), team_id)
        except ValueError:
            return False, "Invalid Plausible host URL"
        if not host_valid:
            return False, host_error

        return validate_plausible_credentials(config.host, config.site_id, config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PlausibleResumeConfig]:
        return ResumableSourceManager[PlausibleResumeConfig](inputs, PlausibleResumeConfig)

    def source_for_pipeline(
        self,
        config: PlausibleSourceConfig,
        resumable_source_manager: ResumableSourceManager[PlausibleResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        host_valid, host_error = self.is_database_host_valid(hostname_of(config.host), inputs.team_id)
        if not host_valid:
            raise ValueError(host_error or "Invalid Plausible host")

        return plausible_source(
            host=config.host,
            site_id=config.site_id,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
