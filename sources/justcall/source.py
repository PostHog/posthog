from typing import Optional, cast

from sources.justcall._config import JustCallSourceConfig
from sources.justcall.justcall import (
    JustCallResumeConfig,
    justcall_source,
    validate_credentials as validate_justcall_credentials,
)
from sources.justcall.settings import ENDPOINTS, INCREMENTAL_FIELDS
from sources.sdk import (
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
)


@SourceRegistry.register
class JustCallSource(ResumableSource[JustCallSourceConfig, JustCallResumeConfig]):
    supported_versions = ("v2.1",)
    default_version = "v2.1"
    api_docs_url = "https://developer.justcall.io/reference"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.JUSTCALL

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.justcall.io": "JustCall authentication failed. Please check your API key and secret.",
            "403 Client Error: Forbidden for url: https://api.justcall.io": "JustCall denied access. Please check that your API key has permission for the resources you are syncing.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.JUSTCALL,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="JustCall",
            caption="""Enter your JustCall API credentials to pull your JustCall data into the PostHog Data warehouse.

Generate an API key and secret under **Account Settings → Developers (APIs and Webhooks)** in your [JustCall dashboard](https://app.justcall.io/). The credentials have read access to your account's calls, texts, contacts, and phone numbers.""",
            iconPath="/static/services/justcall.png",
            docsUrl="https://posthog.com/docs/cdp/sources/justcall",
            releaseStatus=ReleaseStatus.ALPHA,
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
                        name="api_secret",
                        label="API secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from sources.justcall.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: JustCallSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: JustCallSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_justcall_credentials(config.api_key, config.api_secret):
            return True, None

        return False, "Invalid JustCall API credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[JustCallResumeConfig]:
        return ResumableSourceManager[JustCallResumeConfig](inputs, JustCallResumeConfig)

    def source_for_pipeline(
        self,
        config: JustCallSourceConfig,
        resumable_source_manager: ResumableSourceManager[JustCallResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return justcall_source(
            api_key=config.api_key,
            api_secret=config.api_secret,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
