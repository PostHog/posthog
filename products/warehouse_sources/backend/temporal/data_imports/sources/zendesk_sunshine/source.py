import re
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zendesksunshine import (
    ZendeskSunshineSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sunshine.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sunshine.zendesk_sunshine import (
    ZendeskSunshineResumeConfig,
    normalize_subdomain,
    validate_credentials as validate_zendesk_sunshine_credentials,
    zendesk_sunshine_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ZendeskSunshineSource(ResumableSource[ZendeskSunshineSourceConfig, ZendeskSunshineResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # The Sunshine API path (`/api/sunshine/`) carries no version token, so the unversioned
    # `supported_versions`/`default_version` defaults apply.
    api_docs_url = "https://developer.zendesk.com/api-reference/custom-data/custom-objects-api/custom-objects-api/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZENDESKSUNSHINE

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sunshine.canonical_descriptions import (  # noqa: PLC0415 — sibling data module, loaded only when descriptions are requested
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": (
                "Zendesk rejected the credentials. Check the subdomain, email address, and API token are correct, "
                "and that token access is enabled for your account."
            ),
            "403 Client Error: Forbidden for url": (
                "Zendesk denied access to the Sunshine API. Check that legacy custom objects are activated for "
                "your account and that the API token has access."
            ),
            "404 Client Error: Not Found for url": (
                "The Zendesk Sunshine (legacy custom objects) API was not found. Check the subdomain is correct "
                "and that legacy custom objects are activated in Admin Center."
            ),
        }

    def get_schemas(
        self,
        config: ZendeskSunshineSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # The query endpoint's `_updated_at.start` filter is inclusive, so boundary rows are
        # re-fetched on every sync; only merge mode dedupes them, hence no append support.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=("object_records",))

    def validate_credentials(
        self,
        config: ZendeskSunshineSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        subdomain = normalize_subdomain(config.subdomain)
        if not re.match(r"^[a-zA-Z0-9-]+$", subdomain):
            return False, "Zendesk subdomain is incorrect"

        return validate_zendesk_sunshine_credentials(config.subdomain, config.api_key, config.email_address)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ZendeskSunshineResumeConfig]:
        return ResumableSourceManager[ZendeskSunshineResumeConfig](inputs, ZendeskSunshineResumeConfig)

    def source_for_pipeline(
        self,
        config: ZendeskSunshineSourceConfig,
        resumable_source_manager: ResumableSourceManager[ZendeskSunshineResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return zendesk_sunshine_source(
            subdomain=config.subdomain,
            api_key=config.api_key,
            email_address=config.email_address,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ZENDESK_SUNSHINE,
            category=DataWarehouseSourceCategory.CRM,
            label="Zendesk Sunshine",
            caption="""Import your legacy Zendesk custom objects (the Sunshine custom data API) into the PostHog Data warehouse: object types, object records, relationships, and limits.

Requires a Zendesk plan with legacy custom objects activated in Admin Center. Note that Zendesk is retiring legacy custom objects in 2026, so this source is mainly useful for keeping a copy of that data. Authenticate with your Zendesk email address and an API token (token access must be enabled for your account).""",
            keywords=["zendesk", "sunshine", "custom objects", "custom data"],
            iconPath="/static/services/zendesk_sunshine.png",
            iconClassName="rounded dark:bg-white p-[2px]",
            docsUrl="https://posthog.com/docs/cdp/sources/zendesk-sunshine",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Zendesk subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="email_address",
                        label="Zendesk email address",
                        type=SourceFieldInputConfigType.EMAIL,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )
