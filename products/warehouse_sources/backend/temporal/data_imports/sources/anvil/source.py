from typing import Optional, cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.anvil.anvil import (
    AnvilResumeConfig,
    anvil_source,
    validate_credentials as validate_anvil_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.anvil.settings import (
    ANVIL_ENDPOINTS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.anvil import AnvilSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SCHEMA_DESCRIPTIONS: dict[str, str] = {
    name: config.description for name, config in ANVIL_ENDPOINTS.items() if config.description
}


@SourceRegistry.register
class AnvilSource(ResumableSource[AnvilSourceConfig, AnvilResumeConfig]):
    # Anvil's GraphQL API is unversioned; the REST-only fill/generate endpoints carry the
    # /v1 path segment, but this source never calls them.
    api_docs_url = "https://www.useanvil.com/docs/api/graphql/reference/"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ANVIL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ANVIL,
            category=DataWarehouseSourceCategory.SALES,
            label="Anvil",
            keywords=["useanvil.com", "e-signature", "pdf"],
            caption="""Sync metadata about your Anvil documents into the PostHog Data warehouse: organizations, PDF templates (casts), workflows (welds), workflow submissions, and e-signature packets with their signer status.

Create an API key in your Anvil organization settings, under API settings. Development keys are rate limited to 4 requests per second, so large accounts sync faster with a production key.

Only metadata is synced. Filled PDFs, signed documents, and submission form data never leave Anvil.""",
            iconPath="/static/services/anvil.png",
            docsUrl="https://posthog.com/docs/cdp/sources/anvil",
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
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.anvil.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # An invalid or revoked key surfaces as a requests HTTPError once the transport's
        # retries are exhausted; match the stable status text and host, not the per-request
        # detail.
        return {
            "401 Client Error: Unauthorized for url: https://graphql.useanvil.com": "Your Anvil API key is invalid or has been revoked. Create a new API key in your Anvil organization's API settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://graphql.useanvil.com": "Your Anvil API key does not have access to this data. Check the key's organization in your Anvil API settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: AnvilSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, descriptions=_SCHEMA_DESCRIPTIONS)

    def validate_credentials(
        self,
        config: AnvilSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        is_valid, error = validate_anvil_credentials(config.api_key)
        if is_valid:
            return True, None

        return False, error or "Invalid Anvil API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AnvilResumeConfig]:
        return ResumableSourceManager[AnvilResumeConfig](inputs, AnvilResumeConfig)

    def source_for_pipeline(
        self,
        config: AnvilSourceConfig,
        resumable_source_manager: ResumableSourceManager[AnvilResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return anvil_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
