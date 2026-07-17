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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MonteCarloSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.monte_carlo.monte_carlo import (
    MonteCarloResumeConfig,
    monte_carlo_source,
    validate_credentials as validate_monte_carlo_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.monte_carlo.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MonteCarloSource(ResumableSource[MonteCarloSourceConfig, MonteCarloResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MONTECARLO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MONTE_CARLO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Monte Carlo",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["montecarlo", "data observability"],
            caption="""Enter your Monte Carlo API key to pull your data observability history into the PostHog Data warehouse.

You can create an API key from **Settings → API → Keys** in your Monte Carlo dashboard. Keys are created with an expiration date, so you will need to reconnect with a new key when it expires.
""",
            iconPath="/static/services/monte_carlo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/monte-carlo",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key_id",
                        label="API key ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key_secret",
                        label="API key secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.monte_carlo.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # An invalid or expired Monte Carlo API key surfaces as a requests HTTPError when
        # `_execute_query` calls `raise_for_status()`. Retrying can never fix a credential
        # problem, so stop the sync.
        return {
            "401 Client Error: Unauthorized for url: https://api.getmontecarlo.com": "Your Monte Carlo API key is invalid or has expired. Create a new API key in your Monte Carlo settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.getmontecarlo.com": "Your Monte Carlo API key does not have permission to read this data. Check the key's permissions in your Monte Carlo settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: MonteCarloSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "alerts":
                return "Only syncs the last 365 days on initial sync"
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            incremental_fields = INCREMENTAL_FIELDS.get(endpoint, [])
            has_incremental = len(incremental_fields) > 0
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                # Alerts mutate in place (status, severity, comments), so merge is the only
                # sync mode that keeps rows current; append would materialize stale versions.
                supports_append=False,
                incremental_fields=incremental_fields,
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: MonteCarloSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_monte_carlo_credentials(config.api_key_id, config.api_key_secret):
            return True, None

        return False, "Invalid Monte Carlo API key ID or secret"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MonteCarloResumeConfig]:
        return ResumableSourceManager[MonteCarloResumeConfig](inputs, MonteCarloResumeConfig)

    def source_for_pipeline(
        self,
        config: MonteCarloSourceConfig,
        resumable_source_manager: ResumableSourceManager[MonteCarloResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return monte_carlo_source(
            api_key_id=config.api_key_id,
            api_key_secret=config.api_key_secret,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
