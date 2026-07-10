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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import KoyebSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb.koyeb import (
    KoyebResumeConfig,
    koyeb_source,
    validate_credentials as validate_koyeb_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    KOYEB_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KoyebSource(ResumableSource[KoyebSourceConfig, KoyebResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KOYEB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.KOYEB,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Koyeb",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Koyeb API access token to sync your Koyeb apps, services, deployments, instances, events, and usage data into the PostHog Data warehouse.

You can create an API access token in the [Koyeb console](https://app.koyeb.com/user/settings/api) under **Settings > API**. The token is scoped to a single organization.""",
            iconPath="/static/services/koyeb.png",
            docsUrl="https://posthog.com/docs/cdp/sources/koyeb",
            keywords=["serverless", "deployments", "hosting", "infrastructure"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A bad/revoked token surfaces as a requests HTTPError from `raise_for_status()`. Retrying
            # can never satisfy a credential problem. Match the stable status text and base host.
            "401 Client Error: Unauthorized for url: https://app.koyeb.com": "Your Koyeb API token is invalid or has been revoked. Create a new API access token in the Koyeb console, then reconnect.",
            "403 Client Error: Forbidden for url: https://app.koyeb.com": "Your Koyeb API token is missing the permissions needed to sync this data. Grant the required access in the Koyeb console, then reconnect.",
        }

    def get_schemas(
        self,
        config: KoyebSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=KOYEB_ENDPOINTS[endpoint].supports_incremental,
                supports_append=KOYEB_ENDPOINTS[endpoint].supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: KoyebSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        valid, error = validate_koyeb_credentials(config.api_key)
        # A 403 at source-create means the token is genuine but lacks scope for the probe endpoint;
        # users may only grant scopes for the tables they want, so accept it there. Only re-raise a
        # 403 when validating a specific schema.
        if not valid and schema_name is None and error and "permission" in error.lower():
            return True, None
        return valid, error

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[KoyebResumeConfig]:
        return ResumableSourceManager[KoyebResumeConfig](inputs, KoyebResumeConfig)

    def source_for_pipeline(
        self,
        config: KoyebSourceConfig,
        resumable_source_manager: ResumableSourceManager[KoyebResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return koyeb_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
