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
from products.warehouse_sources.backend.temporal.data_imports.sources.aha_ideas.aha_ideas import (
    AhaIdeasResumeConfig,
    aha_ideas_source,
    validate_credentials as validate_aha_ideas_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aha_ideas.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ahaideas import (
    AhaIdeasSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AhaIdeasSource(ResumableSource[AhaIdeasSourceConfig, AhaIdeasResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://www.aha.io/api/resources/ideas"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AHAIDEAS

    @property
    def connection_host_fields(self) -> list[str]:
        # The API key is sent to `<subdomain>.aha.io`, so changing the subdomain must re-require it.
        return ["subdomain"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AHA_IDEAS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Aha! Ideas",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Aha! account domain and API key to pull your Aha! Ideas portal data — ideas, votes, comments, submitters, and portals — into the PostHog Data warehouse.

Create an API key under **Settings → Personal → Developer → API keys** in your Aha! account. The key inherits your account permissions, so it can read every record you can see.""",
            iconPath="/static/services/aha_ideas.png",
            docsUrl="https://posthog.com/docs/cdp/sources/aha-ideas",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Account domain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="yourcompany",
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

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.aha_ideas.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when the REST client calls `raise_for_status()`.
            # Retrying can never fix a credential/permission problem, so fail the sync. Match the
            # stable status text, not the per-request path.
            "401 Client Error: Unauthorized": "Your Aha! API key is invalid or has been revoked. Create a new key in your Aha! account settings, then reconnect.",
            "403 Client Error: Forbidden": "Your Aha! API key is missing the permissions needed to sync this data. Check the key's account permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: AhaIdeasSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # `build_endpoint_schemas` treats any endpoint present in the mapping as incremental, so
        # drop the full-refresh endpoints (empty `incremental_fields`) to keep them full refresh.
        incremental_fields = {name: fields for name, fields in INCREMENTAL_FIELDS.items() if fields}
        return build_endpoint_schemas(ENDPOINTS, incremental_fields, names)

    def validate_credentials(
        self,
        config: AhaIdeasSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            ok, status_code = validate_aha_ideas_credentials(config.subdomain, config.api_key)
        except ValueError as e:
            return False, str(e)

        if ok:
            return True, None
        if status_code == 401:
            return False, "Invalid Aha! API key"
        return False, "Could not connect to Aha! with the provided account domain and API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AhaIdeasResumeConfig]:
        return ResumableSourceManager[AhaIdeasResumeConfig](inputs, AhaIdeasResumeConfig)

    def source_for_pipeline(
        self,
        config: AhaIdeasSourceConfig,
        resumable_source_manager: ResumableSourceManager[AhaIdeasResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aha_ideas_source(
            subdomain=config.subdomain,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
