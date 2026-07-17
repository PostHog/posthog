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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SwarmiaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.swarmia.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SWARMIA_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.swarmia.swarmia import (
    SwarmiaResumeConfig,
    check_credentials,
    check_endpoint_access,
    swarmia_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SwarmiaSource(ResumableSource[SwarmiaSourceConfig, SwarmiaResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SWARMIA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SWARMIA,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Swarmia",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["dora", "engineering metrics", "developer productivity"],
            caption="""Enter your Swarmia API token to pull your engineering metrics reports (pull requests, DORA, investment balance, software capitalization, and effort) into the PostHog Data warehouse.

You can create an API token in your Swarmia workspace under **Settings** → **API tokens**.

Some reports (investment balance, software capitalization, effort) map to Swarmia features that may not be enabled on every plan — tables your token can't access are flagged in the table picker.
""",
            iconPath="/static/services/swarmia.png",
            docsUrl="https://posthog.com/docs/cdp/sources/swarmia",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.swarmia.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://app.swarmia.com": "Your Swarmia API token is invalid or has been revoked. Create a new token under Settings → API tokens in Swarmia, then reconnect.",
            "403 Client Error: Forbidden for url: https://app.swarmia.com": "Your Swarmia API token can't access this report. It may require a Swarmia plan or feature that isn't enabled for your organization.",
        }

    def get_schemas(
        self,
        config: SwarmiaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = SWARMIA_ENDPOINTS[endpoint]
            has_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                # Incremental runs re-pull a trailing window of restated report data; only merge
                # dedupes those rows on the primary key, append would materialize duplicates.
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description=endpoint_config.description,
                default_incremental_lookback_seconds=endpoint_config.default_incremental_lookback_seconds,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: SwarmiaSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        status = check_credentials(config.api_key)
        if status is not None and status < 400:
            return True, None
        if status == 401:
            return False, "Invalid Swarmia API token"
        if status == 403:
            # A valid token can be denied a specific report by plan gating; only fail when a
            # specific schema was asked for. Per-table access is surfaced by get_endpoint_permissions.
            if schema_name is not None:
                return False, "Your Swarmia API token can't access this report"
            return True, None
        return False, "Could not connect to the Swarmia API"

    def get_endpoint_permissions(
        self, config: SwarmiaSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        return check_endpoint_access(config.api_key, endpoints)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SwarmiaResumeConfig]:
        return ResumableSourceManager[SwarmiaResumeConfig](inputs, SwarmiaResumeConfig)

    def source_for_pipeline(
        self,
        config: SwarmiaSourceConfig,
        resumable_source_manager: ResumableSourceManager[SwarmiaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return swarmia_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
