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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HoneybadgerSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.honeybadger.honeybadger import (
    HoneybadgerResumeConfig,
    honeybadger_source,
    validate_credentials as validate_honeybadger_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.honeybadger.settings import (
    ENDPOINTS,
    HONEYBADGER_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HoneybadgerSource(ResumableSource[HoneybadgerSourceConfig, HoneybadgerResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HONEYBADGER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HONEYBADGER,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Honeybadger",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Honeybadger personal authentication token to pull your error monitoring data (projects, errors, occurrences, deployments, and uptime checks) into the PostHog Data warehouse.

You can find your personal authentication token on your [Honeybadger profile page](https://app.honeybadger.io/users/edit).

Note that Honeybadger's API is limited to 360 requests per hour, so large backfills (especially of the notices table) can take a while.""",
            iconPath="/static/services/honeybadger.png",
            docsUrl="https://posthog.com/docs/cdp/sources/honeybadger",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Personal authentication token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.honeybadger.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Honeybadger also answers rate-limited requests with a 403, but those are converted to
        # a retryable error before raise_for_status runs (see honeybadger.py), so a 403
        # HTTPError here can only be a credential/permission problem.
        return {
            "401 Client Error: Unauthorized for url: https://app.honeybadger.io": "Your Honeybadger authentication token is invalid or has been revoked. Copy a valid personal authentication token from your Honeybadger profile page, then reconnect.",
            "403 Client Error: Forbidden for url: https://app.honeybadger.io": "Honeybadger denied access with this authentication token. Copy a valid personal authentication token from your Honeybadger profile page, then reconnect.",
        }

    def get_schemas(
        self,
        config: HoneybadgerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "notices":
                return (
                    "One row per error occurrence. Fetched per fault, so syncing large accounts is slow "
                    "against Honeybadger's 360 requests/hour limit — prefer incremental sync"
                )
            return None

        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0,
                supports_append=len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=HONEYBADGER_ENDPOINTS[endpoint].should_sync_default,
                description=_description(endpoint),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: HoneybadgerSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_honeybadger_credentials(config.api_key):
            return True, None

        return False, "Invalid Honeybadger authentication token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HoneybadgerResumeConfig]:
        return ResumableSourceManager[HoneybadgerResumeConfig](inputs, HoneybadgerResumeConfig)

    def source_for_pipeline(
        self,
        config: HoneybadgerSourceConfig,
        resumable_source_manager: ResumableSourceManager[HoneybadgerResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return honeybadger_source(
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
