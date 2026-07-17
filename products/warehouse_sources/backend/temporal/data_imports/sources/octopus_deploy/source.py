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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OctopusDeploySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.octopus_deploy.octopus_deploy import (
    HOST_NOT_ALLOWED_ERROR,
    OctopusDeployResumeConfig,
    octopus_deploy_source,
    validate_credentials as validate_octopus_deploy_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.octopus_deploy.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OctopusDeploySource(ResumableSource[OctopusDeploySourceConfig, OctopusDeployResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OCTOPUSDEPLOY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OCTOPUS_DEPLOY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Octopus Deploy",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Octopus Deploy server URL and an API key to pull your deployment data into the PostHog Data warehouse.

Use your Octopus Cloud URL (like `https://your-org.octopus.app`) or your self-hosted server's public URL.

You can create an API key in the Octopus web portal under **your profile > My API Keys**. The key inherits your user's permissions, so it needs read access to the spaces you want to sync.""",
            iconPath="/static/services/octopus_deploy.png",
            docsUrl="https://posthog.com/docs/cdp/sources/octopus-deploy",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Octopus Deploy URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://your-org.octopus.app",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="API-XXXXXXXXXXXXXXXXXXXXXXXXXX",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Octopus Deploy API key. Please generate a new key and reconnect.",
            "403 Client Error": "Your Octopus Deploy API key lacks the required permissions. Please check the key's user permissions and try again.",
            HOST_NOT_ALLOWED_ERROR: "The Octopus Deploy host is not allowed. Please use your Octopus Cloud or self-hosted server URL.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.octopus_deploy.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: OctopusDeploySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "tasks":
                return "Incremental syncs filter on completion date, so tasks only appear once they finish"
            return None

        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description=_description(endpoint),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: OctopusDeploySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_octopus_deploy_credentials(config.host, config.api_key, schema_name, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OctopusDeployResumeConfig]:
        return ResumableSourceManager[OctopusDeployResumeConfig](inputs, OctopusDeployResumeConfig)

    def source_for_pipeline(
        self,
        config: OctopusDeploySourceConfig,
        resumable_source_manager: ResumableSourceManager[OctopusDeployResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return octopus_deploy_source(
            host=config.host,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            team_id=inputs.team_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
