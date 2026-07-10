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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PipedriveSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.pipedrive import (
    PipedriveResumeConfig,
    normalize_company_domain,
    pipedrive_source,
    validate_credentials as validate_pipedrive_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.settings import ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PipedriveSource(ResumableSource[PipedriveSourceConfig, PipedriveResumeConfig]):
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://developers.pipedrive.com/docs/api/v1"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PIPEDRIVE

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored API token is sent to `{company_domain}.pipedrive.com`; retargeting the
        # domain must re-require the token.
        return ["company_domain"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PIPEDRIVE,
            category=DataWarehouseSourceCategory.CRM,
            label="Pipedrive",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Pipedrive API token to sync your Pipedrive CRM data into the PostHog Data warehouse.

You can find your personal API token in Pipedrive under **Settings > Personal preferences > API**. The token inherits your user's permissions, so make sure your user can access the data you want to sync.""",
            iconPath="/static/services/pipedrive.png",
            docsUrl="https://posthog.com/docs/cdp/sources/pipedrive",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="company_domain",
                        label="Company domain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="mycompany",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
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
            "401 Client Error": "Invalid Pipedrive API token. Please check your token and reconnect.",
            "403 Client Error": "Your Pipedrive user lacks permission for this data. Please check your access and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: PipedriveSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Full refresh only: Pipedrive's v1 collections have no server-side updated_after
        # filter, and the v2 `updated_since` filter is unverified (no credentials to curl with).
        schemas = [
            SourceSchema(name=endpoint, supports_incremental=False, supports_append=False, incremental_fields=[])
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: PipedriveSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            status = validate_pipedrive_credentials(config.company_domain, config.api_token)
        except ValueError as e:
            return False, str(e)

        if status == 200:
            return True, None
        # A valid token may lack scope for some endpoints; accept that at source-create
        # (schema_name is None) and only reject when validating a specific schema.
        if status == 403 and schema_name is None:
            return True, None
        if status in (401, 403):
            return False, "Invalid Pipedrive API token or insufficient permissions"
        return False, "Could not validate Pipedrive credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PipedriveResumeConfig]:
        return ResumableSourceManager[PipedriveResumeConfig](inputs, PipedriveResumeConfig)

    def source_for_pipeline(
        self,
        config: PipedriveSourceConfig,
        resumable_source_manager: ResumableSourceManager[PipedriveResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return pipedrive_source(
            company_domain=normalize_company_domain(config.company_domain),
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
