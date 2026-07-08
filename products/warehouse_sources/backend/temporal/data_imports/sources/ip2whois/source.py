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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import IP2WhoisSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ip2whois.ip2whois import (
    ip2whois_source,
    validate_credentials as validate_ip2whois_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ip2whois.settings import (
    ENDPOINTS,
    IP2WHOIS_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class IP2WhoisSource(SimpleSource[IP2WhoisSourceConfig]):
    # `get_schemas` iterates a static endpoint catalog with no I/O, so the table list is safe to render
    # in public docs without credentials.
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.IP2WHOIS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.IP2_WHOIS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="IP2WHOIS",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your IP2WHOIS API key and the domains you want to look up to pull WHOIS registration data into the PostHog Data warehouse.

IP2WHOIS (by IP2Location) is a domain WHOIS lookup API. Create an API key in your [IP2WHOIS dashboard](https://www.ip2whois.com/) — the free tier includes 500 lookups per month.

There is no list endpoint — every request looks up a single domain — so enter one domain per line (commas and spaces also work). For example:

```
example.com
posthog.com
```

Each sync looks up every configured domain once and replaces the table with the current WHOIS record. Every domain costs one lookup against your monthly quota.
""",
            iconPath="/static/services/ip2whois.png",
            docsUrl="https://posthog.com/docs/cdp/sources/ip2whois",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Your IP2WHOIS API key",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="domains",
                        label="Domains",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="example.com\nposthog.com",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.ip2whois.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A bad/disabled key surfaces as an HTTP 401 (code 10001, "API key not found") or 403 via
            # `_fetch_domain`. Retrying can never satisfy a credential problem. Match the stable status
            # text and base host (the `key` query param is never included in the message).
            "401 Client Error: Unauthorized for url: https://api.ip2whois.com": "Your IP2WHOIS API key is invalid or has been disabled. Generate a new key in your IP2WHOIS dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.ip2whois.com": "Your IP2WHOIS API key does not have access to this data. Check the key in your IP2WHOIS dashboard, then reconnect.",
            # Account-level API errors returned in the JSON error envelope (exhausted monthly quota,
            # disabled account, and anything else that isn't specific to a single domain) are raised as
            # IP2WhoisAPIError. These are deterministic within a run, so fail fast rather than retry.
            "IP2WHOIS API error": "Your IP2WHOIS request was rejected by the API — the account may be disabled or the monthly lookup quota exhausted. Check your IP2WHOIS dashboard, then reconnect or resync.",
        }

    def get_schemas(
        self,
        config: IP2WhoisSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # IP2WHOIS has no server-side change cursor, so the single table is full refresh only.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                description=IP2WHOIS_ENDPOINTS[endpoint].description,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: IP2WhoisSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_ip2whois_credentials(config.api_key, config.domains)

    def source_for_pipeline(self, config: IP2WhoisSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return ip2whois_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            domains_raw=config.domains,
            logger=inputs.logger,
        )
