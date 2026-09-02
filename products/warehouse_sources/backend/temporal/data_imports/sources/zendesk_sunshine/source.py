import re
import datetime
from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    FieldType,
    ResumableSource,
    VersionDeprecation,
)
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zendesksunshine import (
    ZendeskSunshineSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sunshine.settings import (
    ENDPOINTS_BY_VERSION,
    INCREMENTAL_FIELDS_BY_VERSION,
    MERGE_ONLY_BY_VERSION,
    ZENDESK_SUNSHINE_V1,
    ZENDESK_SUNSHINE_V2,
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

    # v1 is the legacy Sunshine API (`/api/sunshine/`); v2 is the current custom objects API
    # (`/api/v2/custom_objects`). Zendesk is retiring the legacy API, so new sources default to v2
    # while existing v1-pinned sources keep working until a human migrates them.
    supported_versions = (ZENDESK_SUNSHINE_V1, ZENDESK_SUNSHINE_V2)
    default_version = ZENDESK_SUNSHINE_V2
    deprecated_versions = (VersionDeprecation(version=ZENDESK_SUNSHINE_V1, sunset_at=datetime.date(2026, 6, 30)),)
    api_docs_url = "https://developer.zendesk.com/api-reference/custom-data/custom-objects/custom_objects/"

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
                "Zendesk denied access to the custom objects API. Check that custom objects are activated for "
                "your account and that the API token has access."
            ),
            "404 Client Error: Not Found for url": (
                "The Zendesk custom objects API was not found. Check the subdomain is correct and that custom "
                "objects are activated in Admin Center. Sources still pinned to the legacy Sunshine API (v1) will "
                "start returning this once Zendesk removes it; switch the source to v2 to keep syncing."
            ),
            # A pin outside the supported set stops the source from resolving a request path. Retrying
            # the ~6h discovery cadence can never fix a bad pin, so surface it instead of looping.
            "Unsupported Zendesk Sunshine API version": (
                "This source is pinned to a Zendesk Sunshine API version PostHog no longer supports. Switch it to v2."
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
        # The v1 and v2 table sets differ, so a pinned source must discover under its own version —
        # discovery diffs run under the source pin and would orphan tables that don't exist in the
        # other version's catalog.
        version = self.resolve_api_version(api_version)
        if version not in ENDPOINTS_BY_VERSION:
            raise ValueError(f"Unsupported Zendesk Sunshine API version: {version!r}")
        return build_endpoint_schemas(
            ENDPOINTS_BY_VERSION[version],
            INCREMENTAL_FIELDS_BY_VERSION[version],
            names,
            merge_only=MERGE_ONLY_BY_VERSION[version],
        )

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

        # Pre-creation calls pass no pin and resolve to default_version (what new rows are stamped
        # with); a pinned source revalidates against its own version's probe endpoint.
        return validate_zendesk_sunshine_credentials(
            config.subdomain, config.api_key, config.email_address, self.resolve_api_version(api_version)
        )

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
            api_version=self.resolve_api_version(inputs.api_version),
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ZENDESK_SUNSHINE,
            category=DataWarehouseSourceCategory.CRM,
            label="Zendesk Sunshine",
            caption="""Import your Zendesk custom objects into the PostHog Data warehouse: object definitions, their records, and field schemas.

New sources use Zendesk's current custom objects API. The legacy Sunshine API (v1) is still supported for existing sources, but Zendesk is removing it on June 30, 2026. Authenticate with your Zendesk email address and an API token (token access must be enabled for your account).""",
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
