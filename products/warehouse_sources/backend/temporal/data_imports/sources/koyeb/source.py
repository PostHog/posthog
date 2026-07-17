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
    # `get_schemas` iterates the static endpoint catalog with no I/O, so the public docs can
    # render the table list without credentials.
    lists_tables_without_credentials = True

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
            caption="""Enter a Koyeb API token to pull your Koyeb apps, services, deployments, instances, event streams, and usage details into the PostHog Data warehouse.

Create an API token under [API settings](https://app.koyeb.com/user/settings/api) in the Koyeb console. Tokens are scoped to the organization they were created in.""",
            iconPath="/static/services/koyeb.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/koyeb",
            keywords=["serverless", "deployments", "hosting", "infrastructure"],
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
            # 401/403 surface as a requests HTTPError when `_fetch_page` calls raise_for_status().
            # Retrying never satisfies a credential problem, so stop the sync. Match the stable
            # status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://app.koyeb.com": "Your Koyeb API token is invalid or has been revoked. Create a new token in the Koyeb console under API settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://app.koyeb.com": "Your Koyeb API token is not authorized for this organization. Check the token's organization, then reconnect.",
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
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                detected_primary_keys=KOYEB_ENDPOINTS[endpoint].primary_keys,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: KoyebSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_koyeb_credentials(config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[KoyebResumeConfig]:
        return ResumableSourceManager[KoyebResumeConfig](inputs, KoyebResumeConfig)

    def source_for_pipeline(
        self,
        config: KoyebSourceConfig,
        resumable_source_manager: ResumableSourceManager[KoyebResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return koyeb_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
