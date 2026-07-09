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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PipelinerSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pipeliner.pipeliner import (
    HOST_NOT_ALLOWED_ERROR,
    PipelinerResumeConfig,
    pipeliner_source,
    validate_credentials as validate_pipeliner_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pipeliner.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PIPELINER_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PipelinerSource(ResumableSource[PipelinerSourceConfig, PipelinerResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PIPELINER

    @property
    def connection_host_fields(self) -> list[str]:
        # `service_url` is where the stored API key pair is sent; retargeting it must re-require
        # the credentials.
        return ["service_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PIPELINER,
            category=DataWarehouseSourceCategory.CRM,
            label="Pipeliner",
            keywords=["coevera", "pipeliner crm"],
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Import data from your Pipeliner CRM (Coevera) team space into the PostHog Data warehouse.

To connect, create an API application in Pipeliner under **Administration → Unit, Users & Roles → Applications**, then click **Show API Access** to reveal the space ID, service URL, and API credentials. The username and password are shown only once, so store them safely.
""",
            iconPath="/static/services/pipeliner.png",
            docsUrl="https://posthog.com/docs/cdp/sources/pipeliner",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="service_url",
                        label="Service URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="us-east.api.pipelinersales.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="space_id",
                        label="Space ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="username",
                        label="API username",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="password",
                        label="API password",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.pipeliner.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Pipeliner API credentials are invalid or have been revoked. Create a new API application under Administration → Applications, then reconnect.",
            "403 Client Error": "Your Pipeliner API application does not have access to this data. Check the application's permissions, then reconnect.",
            HOST_NOT_ALLOWED_ERROR: "The Pipeliner service URL is not allowed. Please use the service URL shown in your API application's access details.",
        }

    def get_schemas(
        self,
        config: PipelinerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: PipelinerSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key pair is space-wide, so a single probe validates access to every schema.
        return validate_pipeliner_credentials(
            config.service_url, config.space_id, config.username, config.password, schema_name, team_id
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PipelinerResumeConfig]:
        return ResumableSourceManager[PipelinerResumeConfig](inputs, PipelinerResumeConfig)

    def source_for_pipeline(
        self,
        config: PipelinerSourceConfig,
        resumable_source_manager: ResumableSourceManager[PipelinerResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in PIPELINER_ENDPOINTS:
            raise ValueError(f"Unknown Pipeliner schema '{inputs.schema_name}'")

        return pipeliner_source(
            service_url=config.service_url,
            space_id=config.space_id,
            username=config.username,
            password=config.password,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            team_id=inputs.team_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
