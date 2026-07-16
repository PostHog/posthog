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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SkyvernSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.skyvern.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SKYVERN_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.skyvern.skyvern import (
    SkyvernResumeConfig,
    skyvern_source,
    validate_credentials as validate_skyvern_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SkyvernSource(ResumableSource[SkyvernSourceConfig, SkyvernResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://docs.skyvern.com/api-reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SKYVERN

    @property
    def connection_host_fields(self) -> list[str]:
        # The API key is sent to whatever host `base_url` points at, so retargeting it must re-require
        # the secret — otherwise an editor could change only `base_url` (the masked key is preserved on
        # edit) and exfiltrate the stored key to a host they control.
        return ["base_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SKYVERN,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Skyvern",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Skyvern API key to automatically pull your Skyvern browser-automation data into the PostHog Data warehouse.

You can find your API key in your [Skyvern settings](https://app.skyvern.com/settings).

If you self-host Skyvern, set the base URL to your deployment (for example `http://localhost:8000`). Leave it blank to use Skyvern Cloud.""",
            iconPath="/static/services/skyvern.png",
            docsUrl="https://posthog.com/docs/cdp/sources/skyvern",
            keywords=["browser automation", "ai agent", "rpa", "workflows"],
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
                        name="base_url",
                        label="Base URL (self-hosted only)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://api.skyvern.com",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.skyvern.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A missing or revoked API key surfaces as a requests HTTPError when a page fetch calls
            # raise_for_status(). Retrying can never satisfy a credential problem, so stop the sync.
            # Matched on the stable status text (host-agnostic since the base URL is configurable).
            "401 Client Error: Unauthorized": "Your Skyvern API key is invalid or has been revoked. Create a new key in your Skyvern settings, then reconnect.",
            "403 Client Error: Forbidden": "Your Skyvern API key does not have permission to access this data. Check the key and reconnect.",
        }

    def get_schemas(
        self,
        config: SkyvernSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "runs":
                return (
                    "Task and workflow run history, pulled per workflow. Incremental sync filters on the "
                    "immutable created_at with a lookback window; a run whose status changes after it falls "
                    "below the watermark is only re-fetched on a full refresh"
                )
            if endpoint == "credentials":
                return "Stored credential metadata only — secret values are never returned by the Skyvern API"
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = SKYVERN_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                detected_primary_keys=endpoint_config.primary_keys,
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: SkyvernSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_skyvern_credentials(config.api_key, config.base_url)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SkyvernResumeConfig]:
        return ResumableSourceManager[SkyvernResumeConfig](inputs, SkyvernResumeConfig)

    def source_for_pipeline(
        self,
        config: SkyvernSourceConfig,
        resumable_source_manager: ResumableSourceManager[SkyvernResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return skyvern_source(
            api_key=config.api_key,
            base_url=config.base_url,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
