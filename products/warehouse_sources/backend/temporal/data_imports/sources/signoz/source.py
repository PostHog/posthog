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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SigNozSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.signoz.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LIMITED_RETENTION_ENDPOINTS,
    SIGNOZ_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.signoz.signoz import (
    HOST_NOT_ALLOWED_ERROR,
    SigNozResumeConfig,
    signoz_source,
    validate_credentials as validate_signoz_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SigNozSource(ResumableSource[SigNozSourceConfig, SigNozResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SIGNOZ

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SIG_NOZ,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="SigNoz",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Connect your SigNoz workspace to sync logs, traces, alert rules, dashboards, and notification channels into the PostHog Data warehouse.

Enter your SigNoz host (your SigNoz Cloud tenant, e.g. `example.signoz.io`, or your self-hosted URL) and an API key.

Create the API key in SigNoz under **Settings > Service Accounts**: create a service account, then generate a key from its **Keys** tab. Only users with the Admin role can create service accounts; a key with the Viewer role is enough for syncing.""",
            iconPath="/static/services/signoz.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/signoz",
            keywords=["observability", "apm", "traces", "logs"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="SigNoz host",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="example.signoz.io",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="SigNoz API key",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid SigNoz API key. Generate a new key from a service account and reconnect.",
            "403 Client Error": "Your SigNoz API key lacks the required permissions for this data. Check the service account's role and reconnect.",
            HOST_NOT_ALLOWED_ERROR: "The configured SigNoz host is not allowed. Check the host and try again.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.signoz.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SigNozSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=SIGNOZ_ENDPOINTS[endpoint].supports_incremental,
                supports_append=SIGNOZ_ENDPOINTS[endpoint].supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description=(
                    "Limited to your SigNoz retention window on initial sync"
                    if endpoint in LIMITED_RETENTION_ENDPOINTS
                    else None
                ),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: SigNozSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_signoz_credentials(config.host, config.api_key, schema_name=schema_name, team_id=team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SigNozResumeConfig]:
        return ResumableSourceManager[SigNozResumeConfig](inputs, SigNozResumeConfig)

    def source_for_pipeline(
        self,
        config: SigNozSourceConfig,
        resumable_source_manager: ResumableSourceManager[SigNozResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return signoz_source(
            host=config.host,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
