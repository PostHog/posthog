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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAUTH2_PERMANENT_ERROR_MARKER,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.personio import (
    PersonioSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.personio.personio import (
    PersonioResumeConfig,
    personio_source,
    validate_credentials as validate_personio_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.personio.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PersonioSource(ResumableSource[PersonioSourceConfig, PersonioResumeConfig]):
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developer.personio.de"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PERSONIO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Permanent token-exchange failures (invalid_client, bad request, missing scopes, …)
            # all carry the framework's stable marker; transient 429/5xx token errors don't.
            OAUTH2_PERMANENT_ERROR_MARKER: "Personio authentication failed. Please check your client ID and client secret.",
            "403 Client Error: Forbidden for url: https://api.personio.de": "Personio denied access. Please check that your API credential has the required scope for this dataset.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PERSONIO,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Personio",
            caption="""Enter your Personio API credentials to pull your Personio HR data into the PostHog Data warehouse.

An admin can create API credentials in Personio under Settings > Integrations > API credentials. Grant the read scopes for the datasets you want to sync (`personio:persons:read`, `personio:absences:read`, `personio:attendances:read`) and whitelist the employee attributes you need — attributes that aren't whitelisted are silently omitted from responses.""",
            iconPath="/static/services/personio.png",
            docsUrl="https://posthog.com/docs/cdp/sources/personio",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="Client secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.personio.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: PersonioSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: PersonioSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_personio_credentials(config.client_id, config.client_secret):
            return True, None

        return False, "Invalid Personio API credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PersonioResumeConfig]:
        return ResumableSourceManager[PersonioResumeConfig](inputs, PersonioResumeConfig)

    def source_for_pipeline(
        self,
        config: PersonioSourceConfig,
        resumable_source_manager: ResumableSourceManager[PersonioResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return personio_source(
            client_id=config.client_id,
            client_secret=config.client_secret,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
