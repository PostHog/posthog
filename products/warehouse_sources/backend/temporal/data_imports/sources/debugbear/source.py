from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.debugbear.debugbear import (
    debugbear_source,
    validate_credentials as validate_debugbear_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.debugbear.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.debugbear import (
    DebugbearSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DebugbearSource(SimpleSource[DebugbearSourceConfig]):
    codebase_detection = detect(env=("^DEBUGBEAR_",), script_hosts=("cdn.debugbear.com",), npm=("debugbear",))

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://www.debugbear.com/docs/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DEBUGBEAR

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your DebugBear API key is invalid or expired. Please generate a new key and reconnect.",
            "403 Client Error": "Your DebugBear API key doesn't have permission for this request. Use an Admin API key (Account settings > API Keys) and reconnect.",
            # Raised by `_iter_rum_metrics_for_project` after DebugBear 400s on a project with no
            # RUM data; the raw message already names the project and the likely fix.
            "DebugBear rejected the RUM metrics request": None,
        }

    def get_retryable_errors(self) -> set[str]:
        # `_session`'s `make_tracked_session()` already retries 429/5xx, including the Cloudflare
        # 52x/530 family DebugBear can surface on an edge/origin blip, at the urllib3 layer before
        # `_get_json`'s `raise_for_status()` can even raise (see `DEFAULT_RETRY` in
        # sources/common/http/transport.py). A response that still exhausts that budget is a
        # transient DebugBear/edge issue, not a bug, so Temporal's activity retry recovers once it
        # clears rather than surfacing it as tracked exception noise. `raise_for_status` derives
        # these prefixes from the status code alone, not the vendor's reason text, so they're
        # stable to match on.
        return {"Server Error", "429 Client Error"}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.debugbear.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: DebugbearSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: DebugbearSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_debugbear_credentials(config.api_key)

    def source_for_pipeline(self, config: DebugbearSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return debugbear_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DEBUGBEAR,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="DebugBear",
            caption="Sync DebugBear's monitored projects and synthetic Lighthouse / Core Web Vitals test results into your warehouse.",
            docsUrl="https://posthog.com/docs/cdp/sources/debugbear",
            iconPath="/static/services/debugbear.png",
            releaseStatus=ReleaseStatus.GA,
            keywords=["core web vitals", "lighthouse", "web performance"],
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
                        caption="Use an Admin API key so PostHog can list every monitored project. Generate one from DebugBear's account settings — see the [API docs](https://www.debugbear.com/docs/api).",
                    ),
                ],
            ),
        )
