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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.digitalocean import (
    digitalocean_source,
    validate_credentials as validate_digitalocean_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.settings import (
    DIGITALOCEAN_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DigitalOceanSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DigitalOceanSource(SimpleSource[DigitalOceanSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://docs.digitalocean.com/reference/api/api-reference/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DIGITALOCEAN

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A bad, revoked, or expired token surfaces as an HTTPError when the RESTClient calls
            # `raise_for_status()`. Retrying can never fix a credential problem, so stop the sync.
            # Match the stable status text + base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.digitalocean.com": "Your DigitalOcean API token is invalid or has expired. Generate a new personal access token, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.digitalocean.com": "Your DigitalOcean API token is missing the read scope needed to sync this data. Grant read access to the relevant resources, then reconnect.",
        }

    def get_schemas(
        self,
        config: DigitalOceanSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                # DigitalOcean has no server-side timestamp filter, so no endpoint can be
                # incrementally synced — every table is full refresh.
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: DigitalOceanSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        ok, status_code = validate_digitalocean_credentials(config.api_key)
        if ok:
            return True, None

        if status_code in (401, 403):
            return (
                False,
                "DigitalOcean rejected the API token. Check that the personal access token is correct, has read "
                "scope, and has not expired.",
            )

        # A transient response (429, 5xx) or transport error (status_code is None) is not proof the
        # token is bad, so don't tell the user it is — ask them to retry.
        return (
            False,
            "Couldn't reach DigitalOcean to verify the API token. This is usually temporary — wait a moment and "
            "try again.",
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DIGITAL_OCEAN,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="DigitalOcean",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter a DigitalOcean personal access token to pull your DigitalOcean infrastructure and billing data into the PostHog Data warehouse.

Create a token under [API → Tokens](https://cloud.digitalocean.com/account/api/tokens) with at least **Read** scope.""",
            iconPath="/static/services/digitalocean.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/digitalocean",
            keywords=["cloud", "infrastructure", "droplets", "billing"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="dop_v1_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def source_for_pipeline(self, config: DigitalOceanSourceConfig, inputs: SourceInputs) -> SourceResponse:
        endpoint_config = DIGITALOCEAN_ENDPOINTS[inputs.schema_name]
        resource = digitalocean_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
        )
        response = SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=endpoint_config.primary_keys,
            column_hints=resource.column_hints,
        )

        if endpoint_config.partition_key:
            response.partition_count = 1
            response.partition_size = 1
            response.partition_mode = "datetime"
            response.partition_format = "month"
            response.partition_keys = [endpoint_config.partition_key]

        return response
