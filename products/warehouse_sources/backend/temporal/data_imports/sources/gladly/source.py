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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GladlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.gladly import (
    GladlyResumeConfig,
    gladly_source,
    validate_credentials as validate_gladly_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GladlySource(ResumableSource[GladlySourceConfig, GladlyResumeConfig]):
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://developer.gladly.com"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GLADLY

    @property
    def connection_host_fields(self) -> list[str]:
        # `organization` determines the host the stored token is sent to;
        # retargeting it must re-require the token.
        return ["organization"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Gladly authentication failed. Please check your agent email and API token.",
            "403 Client Error: Forbidden for url": "Gladly denied access. Please check that the agent has the API User permission.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GLADLY,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Gladly",
            caption="""Connect your Gladly account to pull your customer service data into the PostHog Data warehouse.

Your organization is the first part of your Gladly URL — for `myorg.gladly.com` enter `myorg`. The API token must belong to an agent with the API User permission (Settings > API Tokens). Data comes from Gladly's scheduled export jobs, which retain files for 14 days — history older than that requires asking Gladly support to regenerate exports.""",
            iconPath="/static/services/gladly.png",
            docsUrl="https://posthog.com/docs/cdp/sources/gladly",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="organization",
                        label="Organization",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="myorg",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="agent_email",
                        label="Agent email",
                        type=SourceFieldInputConfigType.EMAIL,
                        required=True,
                        placeholder="agent@company.com",
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

    def get_schemas(
        self,
        config: GladlySourceConfig,
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
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: GladlySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            if validate_gladly_credentials(config.organization, config.agent_email, config.api_token):
                return True, None
        except ValueError as e:
            # A malformed organization is a distinct, actionable error — surface it
            # instead of the generic credentials message.
            return False, str(e)

        return False, "Invalid Gladly credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GladlyResumeConfig]:
        return ResumableSourceManager[GladlyResumeConfig](inputs, GladlyResumeConfig)

    def source_for_pipeline(
        self,
        config: GladlySourceConfig,
        resumable_source_manager: ResumableSourceManager[GladlyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return gladly_source(
            organization=config.organization,
            agent_email=config.agent_email,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
