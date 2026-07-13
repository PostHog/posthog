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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import NoCRMSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.nocrm.nocrm import (
    NoCRMResumeConfig,
    nocrm_source,
    validate_credentials as validate_nocrm_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.nocrm.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    NOCRM_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NoCRMSource(ResumableSource[NoCRMSourceConfig, NoCRMResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NOCRM

    @property
    def connection_host_fields(self) -> list[str]:
        # The API key is sent to `<subdomain>.nocrm.io`, so retargeting the subdomain must force the
        # editor to re-enter the key rather than reusing the stored one against a new host.
        return ["subdomain"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.NO_CRM,
            category=DataWarehouseSourceCategory.CRM,
            label="noCRM.io",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your noCRM.io account subdomain and API key to automatically pull your noCRM.io data into the PostHog Data warehouse.

Your subdomain is the first part of your noCRM.io URL — for `acme.nocrm.io`, enter `acme`.

You can create an API key as an account admin under **Admin panel → API & Webhooks → API keys**. The key is account-level and grants read access to leads, users, teams, pipelines and the other tables listed below.""",
            iconPath="/static/services/nocrm.png",
            docsUrl="https://posthog.com/docs/cdp/sources/nocrm",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="acme",
                        secret=False,
                    ),
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.nocrm.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked API key surfaces as a requests HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Match the stable status text, not the per-account host/path.
            "401 Client Error: Unauthorized": "Your noCRM.io API key is invalid or has been revoked. Create a new API key in your noCRM.io admin panel, then reconnect.",
            "403 Client Error: Forbidden": "Your noCRM.io API key does not have permission to read this data. Check the key's permissions in noCRM.io, then reconnect.",
        }

    def get_schemas(
        self,
        config: NoCRMSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = NOCRM_ENDPOINTS[endpoint]
            has_incremental = endpoint_config.supports_incremental and bool(INCREMENTAL_FIELDS.get(endpoint))
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
        self, config: NoCRMSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_nocrm_credentials(config.api_key, config.subdomain):
            return True, None

        return False, "Invalid noCRM.io subdomain or API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[NoCRMResumeConfig]:
        return ResumableSourceManager[NoCRMResumeConfig](inputs, NoCRMResumeConfig)

    def source_for_pipeline(
        self,
        config: NoCRMSourceConfig,
        resumable_source_manager: ResumableSourceManager[NoCRMResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return nocrm_source(
            api_key=config.api_key,
            subdomain=config.subdomain,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
