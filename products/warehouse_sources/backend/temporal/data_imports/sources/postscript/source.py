from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.postscript import (
    PostscriptSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postscript.postscript import (
    PostscriptResumeConfig,
    postscript_source,
    validate_credentials as validate_postscript_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postscript.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PostscriptSource(ResumableSource[PostscriptSourceConfig, PostscriptResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # `v2` is the `/api/v2/` path segment every request uses, and the version Postscript took
    # out of beta as its current API.
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developers.postscript.io/reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.POSTSCRIPT

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Invalid Postscript API key. Create a new Private API Key in your Postscript account and reconnect.",
            "403 Client Error: Forbidden for url": "Postscript rejected the API key. Use a shop Private API Key rather than a partner key, and check that the key is still active.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.postscript.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: PostscriptSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: PostscriptSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_postscript_credentials(config.api_key, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PostscriptResumeConfig]:
        return ResumableSourceManager[PostscriptResumeConfig](inputs, PostscriptResumeConfig)

    def source_for_pipeline(
        self,
        config: PostscriptSourceConfig,
        resumable_source_manager: ResumableSourceManager[PostscriptResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return postscript_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.POSTSCRIPT,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Postscript",
            caption=(
                "Import SMS subscribers and keywords from your Postscript shop.\n\n"
                "Create a Private API Key in your Postscript account under Settings > "
                "Integrations > API. Partner API keys are not supported."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/postscript",
            iconPath="/static/services/postscript.png",
            keywords=["sms", "text messaging"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Private API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
