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
from products.warehouse_sources.backend.temporal.data_imports.sources.chargify.chargify import (
    ChargifyResumeConfig,
    chargify_source,
    validate_credentials as validate_chargify_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chargify.settings import (
    CHARGIFY_ENDPOINTS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ChargifySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Chargify site subdomains are alphanumeric with optional hyphens.
SUBDOMAIN_REGEX = re.compile(r"^[a-zA-Z0-9-]+$")


@SourceRegistry.register
class ChargifySource(ResumableSource[ChargifySourceConfig, ChargifyResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CHARGIFY

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored API key is sent to `https://{subdomain}.chargify.com`, so retargeting
        # `subdomain` must force the editor to re-enter the key (prevents credential exfiltration).
        return ["subdomain"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Chargify hosts are per-site subdomains, so match the stable status prefix rather
        # than a fixed hostname. A bad or under-scoped API key can never be fixed by retrying.
        return {
            "401 Client Error: Unauthorized for url": "Your Chargify API key is invalid or has been revoked. Generate a new key in your Chargify site settings, then reconnect.",
            "403 Client Error: Forbidden for url": "Your Chargify API key is missing the permissions needed to sync this data. Check the key's permissions, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.chargify.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ChargifySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=(fields := INCREMENTAL_FIELDS.get(endpoint)) is not None,
                supports_append=fields is not None,
                incremental_fields=fields or [],
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: ChargifySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if not SUBDOMAIN_REGEX.match(config.subdomain):
            return False, "Chargify site subdomain is invalid"

        if validate_chargify_credentials(config.api_key, config.subdomain):
            return True, None

        return False, "Invalid Chargify credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ChargifyResumeConfig]:
        return ResumableSourceManager[ChargifyResumeConfig](inputs, ChargifyResumeConfig)

    def source_for_pipeline(
        self,
        config: ChargifySourceConfig,
        resumable_source_manager: ResumableSourceManager[ChargifyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        endpoint = CHARGIFY_ENDPOINTS[inputs.schema_name]
        resource = chargify_source(
            api_key=config.api_key,
            subdomain=config.subdomain,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
        return SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=endpoint.primary_key,
            column_hints=resource.column_hints,
            partition_mode="datetime" if endpoint.partition_key else None,
            partition_format="month" if endpoint.partition_key else None,
            partition_keys=[endpoint.partition_key] if endpoint.partition_key else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CHARGIFY,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Chargify",
            keywords=["maxio", "advanced billing"],
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Chargify (Maxio Advanced Billing) API key and site subdomain to pull your billing data into the PostHog Data warehouse.

You can create an API key under **Settings → Integrations → API Access** in your Chargify site. Your subdomain is the first part of your site URL — for `acme.chargify.com` the subdomain is `acme`.""",
            iconPath="/static/services/chargify.png",
            docsUrl="https://posthog.com/docs/cdp/sources/chargify",
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
                        label="Site subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="acme",
                        secret=False,
                    ),
                ],
            ),
        )
