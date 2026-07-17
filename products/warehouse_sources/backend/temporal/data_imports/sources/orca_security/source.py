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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OrcaSecuritySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.orca_security.orca_security import (
    OrcaResumeConfig,
    orca_source,
    validate_credentials as validate_orca_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.orca_security.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    ORCA_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OrcaSecuritySource(ResumableSource[OrcaSecuritySourceConfig, OrcaResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ORCASECURITY

    @property
    def connection_host_fields(self) -> list[str]:
        # `region` selects the origin the stored API token is sent to; changing it must
        # re-require the token (Orca tokens are region-scoped anyway).
        return ["region"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.orca_security.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        message = (
            "Orca rejected the API token. Generate a new token in Orca under "
            "Settings → Users & Permissions → API (Viewer role is enough) and reconnect."
        )
        return {
            "401 Client Error: Unauthorized": message,
            "403 Client Error: Forbidden": message,
        }

    def get_schemas(
        self,
        config: OrcaSecuritySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None
                and len(INCREMENTAL_FIELDS[endpoint]) > 0,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None
                and len(INCREMENTAL_FIELDS[endpoint]) > 0,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=ORCA_ENDPOINTS[endpoint].should_sync_default,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: OrcaSecuritySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_orca_credentials(config.api_token, config.region)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OrcaResumeConfig]:
        return ResumableSourceManager[OrcaResumeConfig](inputs, OrcaResumeConfig)

    def source_for_pipeline(
        self,
        config: OrcaSecuritySourceConfig,
        resumable_source_manager: ResumableSourceManager[OrcaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return orca_source(
            api_token=config.api_token,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ORCA_SECURITY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Orca Security",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "Enter your Orca Security API token to pull your cloud security posture data into the "
                "PostHog Data warehouse.\n\n"
                "Create an API token in Orca under **Settings → Users & Permissions → API**. A user with the "
                "**Viewer** role is enough to read alerts, assets, cloud accounts, and vulnerabilities.\n\n"
                "Pick the **region** that matches the URL you sign in to — the token is only valid for the "
                "region it was created in."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/orca-security",
            iconPath="/static/services/orca_security.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="global",
                        options=[
                            SourceFieldSelectConfigOption(label="Global (api.orcasecurity.io)", value="global"),
                            SourceFieldSelectConfigOption(label="US (app.us.orcasecurity.io)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (app.eu.orcasecurity.io)", value="eu"),
                        ],
                    ),
                ],
            ),
        )
