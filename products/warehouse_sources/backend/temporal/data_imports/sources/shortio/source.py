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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ShortioSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.shortio.settings import (
    ENDPOINTS,
    SHORTIO_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shortio.shortio import (
    check_access,
    shortio_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ShortioSource(SimpleSource[ShortioSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SHORTIO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SHORTIO,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Shortio",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Short.io API key to pull your branded-link domains into the PostHog Data warehouse.

Create an API key under **Integrations & API** in your [Short.io dashboard](https://app.short.io/settings/integrations/api-key). Paste the secret key value.

This version syncs your top-level list of **domains** only. Per-domain links and click statistics are not synced yet.
""",
            iconPath="/static/services/shortio.png",
            docsUrl="https://posthog.com/docs/cdp/sources/shortio",
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
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.shortio.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.short.io": "Your Short.io API key is invalid or has been revoked. Generate a new key under Integrations & API, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.short.io": "Your Short.io API key does not have access to this data. Check the key's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: ShortioSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Full refresh only — the domain list exposes no reliably ordered server-side timestamp
        # filter, so there is no incremental cursor to advance.
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
        self, config: ShortioSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key is account-wide, so a single probe validates access to the domain list.
        status, message = check_access(config.api_key)
        if status == 200:
            return True, None
        if status in (401, 403):
            return False, "Invalid Short.io API key"
        return False, message or "Could not validate Short.io API key"

    def source_for_pipeline(self, config: ShortioSourceConfig, inputs: SourceInputs) -> SourceResponse:
        if inputs.schema_name not in SHORTIO_ENDPOINTS:
            raise ValueError(f"Unknown Short.io schema '{inputs.schema_name}'")

        return shortio_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
