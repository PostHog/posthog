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
from products.warehouse_sources.backend.temporal.data_imports.sources.fusionauth.fusionauth import (
    HOST_NOT_ALLOWED_ERROR,
    HTTP_NOT_ALLOWED_ERROR,
    FusionAuthResumeConfig,
    fusionauth_source,
    validate_credentials as validate_fusionauth_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fusionauth.settings import (
    ENDPOINTS,
    FUSIONAUTH_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fusionauth import (
    FusionAuthSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FusionAuthSource(ResumableSource[FusionAuthSourceConfig, FusionAuthResumeConfig]):
    api_docs_url = "https://fusionauth.io/docs/apis/"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FUSIONAUTH

    @property
    def connection_host_fields(self) -> list[str]:
        # `base_url` is where the stored API key is sent; retargeting it must re-require the key.
        return ["base_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FUSION_AUTH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="FusionAuth",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your FusionAuth instance's base URL and an API key to pull your FusionAuth data into the PostHog Data warehouse.

You can create an API key in the FusionAuth admin UI under **Settings > API Keys**.

The key needs read access to the resources you want to sync, for example:
- `/api/user/search`
- `/api/system/audit-log/search`
- `/api/system/event-log/search`
- `/api/system/login-record/search`

Audit logs, event logs, and login records require the Elasticsearch search engine to be configured on your FusionAuth instance.
""",
            iconPath="/static/services/fusionauth.png",
            docsUrl="https://posthog.com/docs/cdp/sources/fusionauth",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="base_url",
                        label="FusionAuth base URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://your-instance.fusionauth.io",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
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
            "401 Client Error": "Invalid FusionAuth API key. Please generate a new key and reconnect.",
            HOST_NOT_ALLOWED_ERROR: "The FusionAuth base URL is not allowed. Please use your organization's FusionAuth instance URL.",
            HTTP_NOT_ALLOWED_ERROR: "The FusionAuth base URL must use HTTPS. Update the source to an https:// URL and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.fusionauth.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: FusionAuthSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(FUSIONAUTH_ENDPOINTS[endpoint].incremental_fields),
                supports_append=bool(FUSIONAUTH_ENDPOINTS[endpoint].incremental_fields),
                incremental_fields=FUSIONAUTH_ENDPOINTS[endpoint].incremental_fields,
                description="Full sync only; the search API's result window is capped at ~10,000 rows."
                if endpoint == "Users"
                else None,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: FusionAuthSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_fusionauth_credentials(config.base_url, config.api_key, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FusionAuthResumeConfig]:
        return ResumableSourceManager[FusionAuthResumeConfig](inputs, FusionAuthResumeConfig)

    def source_for_pipeline(
        self,
        config: FusionAuthSourceConfig,
        resumable_source_manager: ResumableSourceManager[FusionAuthResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return fusionauth_source(
            base_url=config.base_url,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            db_incremental_field_earliest_value=inputs.db_incremental_field_earliest_value
            if inputs.should_use_incremental_field
            else None,
        )
