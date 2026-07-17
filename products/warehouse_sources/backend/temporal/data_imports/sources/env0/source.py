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
from products.warehouse_sources.backend.temporal.data_imports.sources.env0.env0 import (
    Env0ResumeConfig,
    env0_source,
    validate_credentials as validate_env0_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.env0.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import Env0SourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class Env0Source(ResumableSource[Env0SourceConfig, Env0ResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ENV0

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ENV0,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="env0",
            caption="""Enter your env0 API key credentials to pull your env0 data into the PostHog Data warehouse.

You can create an organization API key in your env0 [Organization Settings > API Keys](https://docs.envzero.com/docs/api-keys), or a personal API key from your user settings. The key needs read access to the organizations you want to sync.

Environment cost data is only available for environments with [cost monitoring](https://docs.envzero.com/docs/cost-monitoring) configured.""",
            iconPath="/static/services/env0.png",
            docsUrl="https://posthog.com/docs/cdp/sources/env0",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["env zero", "iac", "terraform"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key_id",
                        label="API key ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key_secret",
                        label="API key secret",
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
            "401 Client Error: Unauthorized for url: https://api.env0.com": "env0 authentication failed. Please check your API key ID and secret.",
            "403 Client Error: Forbidden for url: https://api.env0.com": "env0 denied access. Please check that your API key has read access to this organization.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.env0.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: Env0SourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
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
        self, config: Env0SourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_env0_credentials(config.api_key_id, config.api_key_secret):
            return True, None

        return False, "Invalid env0 API key credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[Env0ResumeConfig]:
        return ResumableSourceManager[Env0ResumeConfig](inputs, Env0ResumeConfig)

    def source_for_pipeline(
        self,
        config: Env0SourceConfig,
        resumable_source_manager: ResumableSourceManager[Env0ResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return env0_source(
            api_key_id=config.api_key_id,
            api_key_secret=config.api_key_secret,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
