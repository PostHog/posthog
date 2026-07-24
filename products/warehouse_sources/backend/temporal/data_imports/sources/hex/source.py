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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hex import HexSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hex.hex import (
    HOST_NOT_ALLOWED_ERROR,
    HexResumeConfig,
    hex_source,
    validate_credentials as validate_hex_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hex.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HexSource(ResumableSource[HexSourceConfig, HexResumeConfig]):
    # Hex's public API has a single, unversioned surface under /api/v1.
    api_docs_url = "https://learn.hex.tech/docs/api-integrations/api/reference"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HEX

    @property
    def connection_host_fields(self) -> list[str]:
        # `workspace_url` is where the stored API token is sent; retargeting it must re-require the token.
        return ["workspace_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HEX,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Hex",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Hex API token to pull your Hex projects, run history, users, groups, and collections into the PostHog Data warehouse.

You can create an API token in Hex under **Workspace settings > API keys**. A personal token inherits your permissions; workspace tokens are available on some plans and can read across the workspace.

If your workspace runs on a single-tenant or self-hosted Hex deployment, enter its URL (for example `https://acme.hex.tech`). Leave it empty to use Hex's multi-tenant cloud at `app.hex.tech`.
""",
            iconPath="/static/services/hex.png",
            docsUrl="https://posthog.com/docs/cdp/sources/hex",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="workspace_url",
                        label="Workspace URL (single-tenant only)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://app.hex.tech",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Hex API token. Please generate a new token in your Hex workspace settings and reconnect.",
            "403 Client Error": "Your Hex API token lacks the required permissions. Please check the token's access and try again.",
            HOST_NOT_ALLOWED_ERROR: "The Hex workspace URL is not allowed. Please use your workspace's Hex URL.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.hex.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: HexSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self, config: HexSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        return validate_hex_credentials(config.workspace_url, config.api_key, schema_name, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HexResumeConfig]:
        return ResumableSourceManager[HexResumeConfig](inputs, HexResumeConfig)

    def source_for_pipeline(
        self,
        config: HexSourceConfig,
        resumable_source_manager: ResumableSourceManager[HexResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return hex_source(
            api_key=config.api_key,
            workspace_url=config.workspace_url,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
