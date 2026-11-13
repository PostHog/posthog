from typing import Optional, cast

from products.warehouse_sources.sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
    detect,
)
from products.warehouse_sources.sources.virtuous._config import VirtuousSourceConfig
from products.warehouse_sources.sources.virtuous.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.sources.virtuous.virtuous import (
    VirtuousResumeConfig,
    validate_credentials as validate_virtuous_credentials,
    virtuous_source,
)


@SourceRegistry.register
class VirtuousSource(ResumableSource[VirtuousSourceConfig, VirtuousResumeConfig]):
    codebase_detection = detect(env=("^VIRTUOUS_",))

    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs
    api_docs_url = "https://docs.virtuoussoftware.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.VIRTUOUS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.virtuoussoftware.com": (
                "Virtuous rejected the API key. Create a key in Virtuous under Settings > Connectivity > "
                "API keys and update this source."
            ),
            "403 Client Error: Forbidden for url: https://api.virtuoussoftware.com": (
                "Your Virtuous API key doesn't have permission to read this data. Give the key's "
                "permission group read access in Virtuous, or turn off this table."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.virtuous.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: VirtuousSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # The "Last Modified Date" filter has day precision and starts a day early, so an append
        # sync would add the overlapping rows again.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=INCREMENTAL_FIELDS.keys())

    def validate_credentials(
        self,
        config: VirtuousSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_virtuous_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[VirtuousResumeConfig]:
        return ResumableSourceManager[VirtuousResumeConfig](inputs, VirtuousResumeConfig)

    def source_for_pipeline(
        self,
        config: VirtuousSourceConfig,
        resumable_source_manager: ResumableSourceManager[VirtuousResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return virtuous_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.VIRTUOUS,
            category=DataWarehouseSourceCategory.CRM,
            label="Virtuous",
            caption=(
                "Import contacts, gifts, recurring gifts, pledges, projects, campaigns and events from "
                "Virtuous CRM+. Create an API key in Virtuous under Settings > Connectivity > API keys. "
                "The key's permission group decides which tables it can read."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/virtuous",
            iconPath="/static/warehouse-sources/virtuous/icon.png",
            keywords=["virtuous crm", "virtuous crm+", "nonprofit", "donors"],
            releaseStatus=ReleaseStatus.BETA,
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
