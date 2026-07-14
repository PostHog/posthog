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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SageHRSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sage_hr.sage_hr import (
    SageHRResumeConfig,
    sage_hr_source,
    validate_credentials as validate_sage_hr_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sage_hr.settings import (
    ENDPOINTS,
    SAGE_HR_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SageHRSource(ResumableSource[SageHRSourceConfig, SageHRResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SAGEHR

    @property
    def connection_host_fields(self) -> list[str]:
        # The API key is sent to `<subdomain>.sage.hr`, so changing the subdomain must re-require it.
        return ["subdomain"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SAGE_HR,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Sage HR",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["cakehr", "hris"],
            caption="""Enter your Sage HR company subdomain and API key to pull your HR data into the PostHog Data warehouse.

An admin must first enable API access under **Settings → Integrations → API** in Sage HR, which generates the API key. Requests go to your own subdomain — for `https://yourcompany.sage.hr` the subdomain is `yourcompany`.""",
            iconPath="/static/services/sage_hr.png",
            docsUrl="https://posthog.com/docs/cdp/sources/sage-hr",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Company subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="yourcompany",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.sage_hr.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # The URL carries the per-account subdomain, so match on the status prefix only.
        return {
            "401 Client Error: Unauthorized for url": "Your Sage HR API key is invalid or has been revoked. Regenerate it under Settings → Integrations → API, then reconnect.",
            "403 Client Error: Forbidden for url": "Your Sage HR API key does not have access to this data. Check that API access is enabled under Settings → Integrations → API, then reconnect.",
        }

    def get_schemas(
        self,
        config: SageHRSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — Sage HR exposes no updated-since style server-side
        # filter, so there is no timestamp cursor to advance an incremental sync.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: SageHRSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key is account-wide, so a single probe validates access to every schema.
        return validate_sage_hr_credentials(config.subdomain, config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SageHRResumeConfig]:
        return ResumableSourceManager[SageHRResumeConfig](inputs, SageHRResumeConfig)

    def source_for_pipeline(
        self,
        config: SageHRSourceConfig,
        resumable_source_manager: ResumableSourceManager[SageHRResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in SAGE_HR_ENDPOINTS:
            raise ValueError(f"Unknown Sage HR schema '{inputs.schema_name}'")

        return sage_hr_source(
            subdomain=config.subdomain,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
