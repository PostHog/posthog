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
from products.warehouse_sources.backend.temporal.data_imports.sources.beamer.beamer import (
    BeamerResumeConfig,
    beamer_source,
    validate_credentials as validate_beamer_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.beamer.settings import (
    BEAMER_ENDPOINTS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BeamerSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BeamerSource(ResumableSource[BeamerSourceConfig, BeamerResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BEAMER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BEAMER,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Beamer",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Beamer API key to sync your changelog posts, feature requests, comments, votes, reactions, and NPS responses into the PostHog Data warehouse.

You can find your API key in your [Beamer account settings](https://app.getbeamer.com/settings#api). Beamer sends it in the `Beamer-Api-Key` header.

Notes:
- The **Users** table requires a Beamer **Scale** plan and is off by default.
- Some post queries need the API key's **Read posts (ignore filters)** permission.""",
            iconPath="/static/services/beamer.png",
            docsUrl="https://posthog.com/docs/cdp/sources/beamer",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.beamer.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch_page` calls `raise_for_status()`.
            # Retrying can never satisfy a credential/permission problem, so fail the sync. Match the
            # stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.getbeamer.com": "Your Beamer API key is invalid or has been revoked. Generate a new key in your Beamer account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.getbeamer.com": "Your Beamer API key is missing the permissions or plan needed to sync this table (e.g. Users needs a Scale plan, and some post queries need the 'Read posts (ignore filters)' permission). Adjust the key in your Beamer account settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: BeamerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "users":
                return "Requires a Beamer Scale plan. Full refresh only"
            if BEAMER_ENDPOINTS[endpoint].parent is not None:
                return "Full refresh only (fanned out over every parent record)"
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = BEAMER_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: BeamerSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_beamer_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BeamerResumeConfig]:
        return ResumableSourceManager[BeamerResumeConfig](inputs, BeamerResumeConfig)

    def source_for_pipeline(
        self,
        config: BeamerSourceConfig,
        resumable_source_manager: ResumableSourceManager[BeamerResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return beamer_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
