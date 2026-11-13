from typing import cast

from products.warehouse_sources.sources.pennylane._config import PennylaneSourceConfig
from products.warehouse_sources.sources.pennylane.pennylane import (
    PennylaneResumeConfig,
    pennylane_source,
    validate_credentials,
)
from products.warehouse_sources.sources.pennylane.settings import (
    API_DOCS_URL,
    API_VERSION,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    NON_RETRYABLE_ERRORS,
)
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

_SCOPES = ", ".join(f"`{scope}`" for scope in sorted({config.scope for config in ENDPOINTS.values()}))


@SourceRegistry.register
class PennylaneSource(ResumableSource[PennylaneSourceConfig, PennylaneResumeConfig]):
    codebase_detection = detect(env=("^PENNYLANE_",))

    lists_tables_without_credentials = True
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PENNYLANE

    @property
    def credential_auth_type(self) -> str:
        # The scaffolded source had no fields and froze `credentials` in `facade/credential_auth_types.py`.
        # Integration rows store that default, so a single-token source keeps it rather than `token`.
        return "credentials"

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return dict(NON_RETRYABLE_ERRORS)

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.pennylane.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: PennylaneSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # A changelog read returns each changed record again, so append would store one row per change.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=INCREMENTAL_FIELDS)

    def validate_credentials(
        self,
        config: PennylaneSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config.api_key, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PennylaneResumeConfig]:
        return ResumableSourceManager[PennylaneResumeConfig](inputs, PennylaneResumeConfig)

    def source_for_pipeline(
        self,
        config: PennylaneSourceConfig,
        resumable_source_manager: ResumableSourceManager[PennylaneResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return pennylane_source(
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
            name=ExternalDataSourceType.PENNYLANE,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Pennylane",
            iconPath="/static/services/pennylane.png",
            docsUrl="https://posthog.com/docs/cdp/sources/pennylane",
            releaseStatus=ReleaseStatus.BETA,
            caption=(
                "Create a company API token in Pennylane under **Settings > Connectivity > Developers**. "
                "You need admin access and an Essential plan or higher. "
                "Choose **Read only**, then select the scope of each table you want to sync. "
                f"The tables use these scopes: {_SCOPES}.\n\n"
                "Incremental sync reads the Pennylane changelogs, which keep changes for 4 weeks. "
                "If the last sync is older than that, the next sync reads the full table again. "
                "Incremental sync does not remove records that were deleted in Pennylane. "
                "Use a full refresh to remove them."
            ),
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
                ],
            ),
        )
