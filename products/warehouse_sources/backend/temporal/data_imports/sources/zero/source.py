from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import NOT_DETECTABLE
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zero import ZeroSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zero.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.zero.zero import (
    ZeroResumeConfig,
    check_credentials,
    zero_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ZeroSource(ResumableSource[ZeroSourceConfig, ZeroResumeConfig]):
    codebase_detection = NOT_DETECTABLE

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.zero.inc/developers/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZERO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.zero.inc": "Your Zero API key is invalid, expired or revoked. Generate a new key under Settings > Connections > API keys in Zero, then reconnect the source.",
            "403 Client Error: Forbidden for url: https://api.zero.inc": "Your Zero API key can't read this table. Check that your Zero account has access to this data, or turn off this table.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.zero.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ZeroSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: ZeroSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        check = check_credentials(config.api_key)
        if check.status in (401, 403):
            return False, "Zero rejected the API key. Check that the key is correct and hasn't expired."
        if check.status != 200:
            return False, "Could not reach the Zero API with that key. Check the key and try again."
        workspace_id = (config.workspace_id or "").strip()
        if workspace_id and workspace_id not in check.workspace_ids:
            return (
                False,
                "This API key can't access that workspace. Check the workspace ID in Zero under Settings > Connections > API keys.",
            )
        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ZeroResumeConfig]:
        return ResumableSourceManager[ZeroResumeConfig](inputs, ZeroResumeConfig)

    def source_for_pipeline(
        self,
        config: ZeroSourceConfig,
        resumable_source_manager: ResumableSourceManager[ZeroResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return zero_source(
            api_key=config.api_key,
            workspace_id=(config.workspace_id or "").strip() or None,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            incremental_field=inputs.incremental_field if inputs.should_use_incremental_field else None,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ZERO,
            category=DataWarehouseSourceCategory.CRM,
            releaseStatus=ReleaseStatus.GA,
            label="Zero",
            caption="Sync your Zero companies, contacts, deals, activity, quotes and sequences into the PostHog Data warehouse. "
            "Create an API key in Zero under **Settings > Connections > API keys**. The same page shows your workspace ID.",
            docsUrl="https://posthog.com/docs/cdp/sources/zero",
            iconPath="/static/services/zero.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="workspace_id",
                        label="Workspace ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="Leave empty to sync every workspace the key can access",
                        secret=False,
                    ),
                ],
            ),
        )
