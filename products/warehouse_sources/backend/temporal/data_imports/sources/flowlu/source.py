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
from products.warehouse_sources.backend.temporal.data_imports.sources.flowlu.flowlu import (
    FlowluResumeConfig,
    flowlu_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flowlu.settings import (
    ENDPOINTS,
    FLOWLU_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FlowluSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Flowlu account subdomains are alphanumeric with optional internal hyphens (a valid DNS label:
# no leading or trailing hyphen).
SUBDOMAIN_REGEX = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$")


@SourceRegistry.register
class FlowluSource(ResumableSource[FlowluSourceConfig, FlowluResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FLOWLU

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored API key is sent to `https://{subdomain}.flowlu.com`, so retargeting
        # `subdomain` must force the editor to re-enter the key (prevents credential exfiltration).
        return ["subdomain"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FLOWLU,
            category=DataWarehouseSourceCategory.CRM,
            label="Flowlu",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Flowlu API key and account subdomain to pull your CRM, project, task, and finance data into the PostHog Data warehouse.

You can create an API key under **Portal Settings → API Settings** in Flowlu. Your subdomain is the first part of your portal URL — for `acme.flowlu.com` the subdomain is `acme`.""",
            iconPath="/static/services/flowlu.png",
            docsUrl="https://posthog.com/docs/cdp/sources/flowlu",
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
                        name="subdomain",
                        label="Account subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="acme",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.flowlu.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Flowlu hosts are per-account subdomains, so match the stable status prefix rather than a
        # fixed hostname. A bad or revoked API key can never be fixed by retrying.
        return {
            "401 Client Error: Unauthorized for url": "Your Flowlu API key is invalid or has been revoked. Generate a new key under Portal Settings → API Settings, then reconnect.",
            "403 Client Error: Forbidden for url": "Your Flowlu API key does not have access to this data. Check the key's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: FlowluSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — Flowlu's list endpoints expose no documented
        # server-side timestamp filter, so there is no incremental cursor to advance
        # (INCREMENTAL_FIELDS is empty, so every schema comes back full-refresh only).
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self, config: FlowluSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if not SUBDOMAIN_REGEX.match(config.subdomain):
            return False, "Flowlu account subdomain is invalid"

        # The API key is account-wide, so a single probe validates access to every schema.
        return validate_credentials(config.api_key, config.subdomain)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FlowluResumeConfig]:
        return ResumableSourceManager[FlowluResumeConfig](inputs, FlowluResumeConfig)

    def source_for_pipeline(
        self,
        config: FlowluSourceConfig,
        resumable_source_manager: ResumableSourceManager[FlowluResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in FLOWLU_ENDPOINTS:
            raise ValueError(f"Unknown Flowlu schema '{inputs.schema_name}'")

        return flowlu_source(
            api_key=config.api_key,
            subdomain=config.subdomain,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
