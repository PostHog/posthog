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
from products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.babelforce import (
    BabelforceResumeConfig,
    babelforce_source,
    is_environment_valid,
    validate_credentials as validate_babelforce_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BabelforceSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BabelforceSource(ResumableSource[BabelforceSourceConfig, BabelforceResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BABELFORCE

    @property
    def connection_host_fields(self) -> list[str]:
        # `environment` is the babelforce subdomain the stored access token is sent to;
        # retargeting it must re-require the token.
        return ["environment"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Babelforce authentication failed. Please check your access ID and access token.",
            "403 Client Error: Forbidden for url": "Babelforce denied access. Please check that your API credentials have manager permissions.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BABELFORCE,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Babelforce",
            caption="""Enter your babelforce API credentials to pull your contact center data into the PostHog Data warehouse.

You can create an access ID and access token pair in your babelforce manager app - see babelforce's [authentication guide](https://help.babelforce.com/hc/en-us/articles/6418329977108-Authentication-Best-Practice). The environment is the subdomain your account is served from - usually `services`, unless you are on a dedicated environment with a custom subdomain.""",
            iconPath="/static/services/babelforce.png",
            docsUrl="https://posthog.com/docs/cdp/sources/babelforce",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="environment",
                        label="Environment (subdomain)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="services",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="access_id",
                        label="Access ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: BabelforceSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: BabelforceSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not is_environment_valid(config.environment):
            return False, "Babelforce environment must be a subdomain like `services`"

        if validate_babelforce_credentials(config.environment, config.access_id, config.access_token):
            return True, None

        return False, "Invalid Babelforce API credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BabelforceResumeConfig]:
        return ResumableSourceManager[BabelforceResumeConfig](inputs, BabelforceResumeConfig)

    def source_for_pipeline(
        self,
        config: BabelforceSourceConfig,
        resumable_source_manager: ResumableSourceManager[BabelforceResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return babelforce_source(
            environment=config.environment,
            access_id=config.access_id,
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
