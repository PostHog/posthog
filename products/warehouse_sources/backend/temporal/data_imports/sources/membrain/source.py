import re
from typing import Optional, cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.membrain import (
    MembrainSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.membrain.membrain import (
    MembrainResumeConfig,
    membrain_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.membrain.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    MEMBRAIN_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Membrain instance subdomains are DNS labels: alphanumeric with optional internal hyphens.
SUBDOMAIN_REGEX = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$")


@SourceRegistry.register
class MembrainSource(ResumableSource[MembrainSourceConfig, MembrainResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://www.membrain.com/developers/api-documentation"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MEMBRAIN

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored API key is sent to `https://{subdomain}.membrain.com`, so retargeting
        # `subdomain` must force the editor to re-enter the key (prevents credential
        # exfiltration).
        return ["subdomain"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MEMBRAIN,
            category=DataWarehouseSourceCategory.CRM,
            label="Membrain",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Membrain API key and account subdomain to sync your CRM data, including companies, contacts, prospects, sales projects, and tickets, into the PostHog Data warehouse.

A Membrain admin can create an API key under **System Setup → Membrain API**. Your subdomain is the first part of your Membrain URL. For `acme.membrain.com` the subdomain is `acme`.""",
            iconPath="/static/services/membrain.png",
            docsUrl="https://posthog.com/docs/cdp/sources/membrain",
            keywords=["crm", "sales"],
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.membrain.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Membrain hosts are per-account subdomains, so match the stable status prefix rather
        # than a fixed hostname. A bad or revoked API key can never be fixed by retrying.
        return {
            "401 Client Error: Unauthorized for url": "Your Membrain API key is invalid or has been revoked. Ask a Membrain admin to create a new key under System Setup, then reconnect.",
            "403 Client Error: Forbidden for url": "Your Membrain API key does not have access to this data. Ask a Membrain admin to check the key, then reconnect.",
        }

    def get_schemas(
        self,
        config: MembrainSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only until the documented ChangedFromDate/ChangedToDate
        # filters are verified against a live instance (INCREMENTAL_FIELDS is empty, so every
        # schema comes back full-refresh only); see settings.py.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: MembrainSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not SUBDOMAIN_REGEX.match(config.subdomain):
            return False, "Membrain account subdomain is invalid"

        # The API key is instance-wide, so a single probe validates access to every schema.
        return validate_credentials(config.api_key, config.subdomain)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MembrainResumeConfig]:
        return ResumableSourceManager[MembrainResumeConfig](inputs, MembrainResumeConfig)

    def source_for_pipeline(
        self,
        config: MembrainSourceConfig,
        resumable_source_manager: ResumableSourceManager[MembrainResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in MEMBRAIN_ENDPOINTS:
            raise ValueError(f"Unknown Membrain schema '{inputs.schema_name}'")

        return membrain_source(
            api_key=config.api_key,
            subdomain=config.subdomain,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
