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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SendowlSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sendowl.sendowl import (
    SendowlResumeConfig,
    check_access,
    sendowl_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sendowl.settings import (
    ENDPOINTS,
    SENDOWL_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SendowlSource(ResumableSource[SendowlSourceConfig, SendowlResumeConfig]):
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://www.sendowl.com/developers"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SENDOWL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SENDOWL,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Sendowl",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your SendOwl API credentials to pull your SendOwl data into the PostHog Data warehouse.

You can create an API key and secret under **Settings → API credentials** in the [SendOwl dashboard](https://dashboard.sendowl.com/settings/api_keys). Grant the key the **Manager** permission for read access to products, orders, subscriptions, and discount codes.
""",
            iconPath="/static/services/sendowl.png",
            docsUrl="https://posthog.com/docs/cdp/sources/sendowl",
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
                        name="api_secret",
                        label="API secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.sendowl.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Invalid or revoked credentials surface as a requests HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can never satisfy a credential problem, so stop the sync.
            # Match the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://www.sendowl.com": "Your SendOwl API credentials are invalid or have been revoked. Generate a new key and secret under Settings → API credentials, then reconnect.",
            "403 Client Error: Forbidden for url: https://www.sendowl.com": "Your SendOwl API credentials do not have access to this data. Check the key's permission scope (use Manager for full read access), then reconnect.",
        }

    def get_schemas(
        self,
        config: SendowlSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — SendOwl's list endpoints expose no reliable
        # server-side timestamp filter for a genuine incremental cursor.
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
        self, config: SendowlSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key pair is account-wide, so a single probe validates access to every schema;
        # there is no per-endpoint scope to check.
        status, message = check_access(config.api_key, config.api_secret)
        if status == 200:
            return True, None
        if status in (401, 403):
            return False, "Invalid SendOwl API credentials"
        return False, message or "Could not validate SendOwl API credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SendowlResumeConfig]:
        return ResumableSourceManager[SendowlResumeConfig](inputs, SendowlResumeConfig)

    def source_for_pipeline(
        self,
        config: SendowlSourceConfig,
        resumable_source_manager: ResumableSourceManager[SendowlResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in SENDOWL_ENDPOINTS:
            raise ValueError(f"Unknown SendOwl schema '{inputs.schema_name}'")

        return sendowl_source(
            api_key=config.api_key,
            api_secret=config.api_secret,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
