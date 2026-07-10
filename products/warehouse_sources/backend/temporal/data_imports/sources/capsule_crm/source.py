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
from products.warehouse_sources.backend.temporal.data_imports.sources.capsule_crm.capsule_crm import (
    CapsuleCRMResumeConfig,
    capsule_crm_source,
    validate_credentials as validate_capsule_crm_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.capsule_crm.settings import (
    CAPSULE_CRM_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CapsuleCRMSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CapsuleCRMSource(ResumableSource[CapsuleCRMSourceConfig, CapsuleCRMResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developer.capsulecrm.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CAPSULECRM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CAPSULE_CRM,
            category=DataWarehouseSourceCategory.CRM,
            label="Capsule CRM",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Capsule CRM Personal Access Token to automatically pull your Capsule CRM data into the PostHog Data warehouse.

You can create a Personal Access Token under **My Preferences → API Authentication Tokens** in your Capsule account.

The token inherits your user's permissions, so make sure your user can see the records you want to sync (parties, opportunities, projects, tasks).""",
            iconPath="/static/services/capsule_crm.png",
            docsUrl="https://posthog.com/docs/cdp/sources/capsule-crm",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Personal Access Token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.capsule_crm.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked token surfaces as a requests HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Match the stable status text and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://api.capsulecrm.com": "Your Capsule CRM Personal Access Token is invalid or has been revoked. Create a new token in your Capsule account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.capsulecrm.com": "Your Capsule CRM user does not have permission to read this data. Check the user's permissions in Capsule, then reconnect.",
        }

    def get_schemas(
        self,
        config: CapsuleCRMSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = CAPSULE_CRM_ENDPOINTS[endpoint]
            has_incremental = endpoint_config.supports_since and bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: CapsuleCRMSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_capsule_crm_credentials(config.access_token):
            return True, None

        return False, "Invalid Capsule CRM Personal Access Token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CapsuleCRMResumeConfig]:
        return ResumableSourceManager[CapsuleCRMResumeConfig](inputs, CapsuleCRMResumeConfig)

    def source_for_pipeline(
        self,
        config: CapsuleCRMSourceConfig,
        resumable_source_manager: ResumableSourceManager[CapsuleCRMResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return capsule_crm_source(
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
