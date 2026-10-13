from typing import Optional, cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.folk.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.folk.folk import (
    FolkResumeConfig,
    folk_source,
    probe_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.folk.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.folk import FolkSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FolkSource(ResumableSource[FolkSourceConfig, FolkResumeConfig]):
    api_docs_url = "https://developer.folk.app/api-reference/overview"
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FOLK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FOLK,
            category=DataWarehouseSourceCategory.CRM,
            label="Folk",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Folk API key to pull your CRM contacts, companies, groups, notes, tasks, and reminders into the PostHog Data warehouse.

You can create an API key in your [Folk workspace settings](https://app.folk.app/apps/contacts/network/settings/api-keys) under the "API" section. The key syncs the data its creating user can access, so create it as a user who can see the groups you want to sync.""",
            iconPath="/static/services/folk.png",
            docsUrl="https://posthog.com/docs/cdp/sources/folk",
            keywords=["crm", "contacts"],
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
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError from the transport's raise_for_status. No
            # retry can satisfy a credential problem. Match the stable status text + host, not the
            # per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.folk.app": "Your Folk API key is invalid or has been revoked. Create a new API key in your Folk workspace settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.folk.app": "Your Folk API key does not have permission to read this resource. Check the key in your Folk workspace settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: FolkSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh — see the rationale in settings.py.
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: FolkSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        status = probe_credentials(config.api_key, schema_name)

        if status == 200:
            return True, None
        # At source-create (schema_name is None) a 403 means the key is genuine but scoped away
        # from the probe resource — accept it; per-endpoint access is checked when configuring a schema.
        if status == 403 and schema_name is None:
            return True, None
        if status == 401:
            return False, "Your Folk API key is invalid or has been revoked."
        if status == 403:
            return False, "Your Folk API key does not have access to this resource."
        return False, "Could not validate your Folk API key. Please check the key and try again."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FolkResumeConfig]:
        return ResumableSourceManager[FolkResumeConfig](inputs, FolkResumeConfig)

    def source_for_pipeline(
        self,
        config: FolkSourceConfig,
        resumable_source_manager: ResumableSourceManager[FolkResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return folk_source(
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
