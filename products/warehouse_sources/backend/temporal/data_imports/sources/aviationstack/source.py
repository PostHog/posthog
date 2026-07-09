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
from products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.aviationstack import (
    AviationstackResumeConfig,
    aviationstack_source,
    validate_credentials as validate_aviationstack_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.settings import (
    AVIATIONSTACK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AviationstackSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AviationstackSource(ResumableSource[AviationstackSourceConfig, AviationstackResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AVIATIONSTACK

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Bad/blocked key surfaces as an HTTP 401 (missing or invalid access_key) — retrying can
            # never satisfy a credential problem. Match the stable status text and base host.
            "401 Client Error: Unauthorized for url: https://api.aviationstack.com": "Your aviationstack access key is invalid or has been deactivated. Generate a new key in your aviationstack dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.aviationstack.com": "Your aviationstack plan does not grant access to this data. Upgrade your aviationstack plan or deselect the restricted tables, then reconnect.",
            # aviationstack also returns HTTP 200 with a body-level error envelope; these are raised as
            # AviationstackAPIError with a stable `[code]` token (see aviationstack._fetch_page).
            "aviationstack API error [invalid_access_key]": "Your aviationstack access key is invalid or has been deactivated. Generate a new key in your aviationstack dashboard, then reconnect.",
            "aviationstack API error [missing_access_key]": "No aviationstack access key was supplied. Reconnect the source with a valid access key.",
            "aviationstack API error [inactive_user]": "Your aviationstack account is inactive. Reactivate it in your aviationstack dashboard, then reconnect.",
            "aviationstack API error [function_access_restricted]": "Your aviationstack plan does not grant access to this data. Upgrade your aviationstack plan or deselect the restricted tables, then reconnect.",
            "aviationstack API error [https_access_restricted]": "Your aviationstack plan does not allow HTTPS access. Upgrade your aviationstack plan, then reconnect.",
            "aviationstack API error [usage_limit_reached]": "Your aviationstack monthly request quota has been reached. Upgrade your plan or wait for the quota to reset, then resync.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AviationstackSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # aviationstack has no server-side updated-at cursor, so every table is full refresh only.
        schemas = [
            SourceSchema(
                name=endpoint.name,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                description=endpoint.description,
            )
            for endpoint in AVIATIONSTACK_ENDPOINTS.values()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: AviationstackSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_aviationstack_credentials(config.access_key):
            return True, None

        return False, "Invalid aviationstack access key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AviationstackResumeConfig]:
        return ResumableSourceManager[AviationstackResumeConfig](inputs, AviationstackResumeConfig)

    def source_for_pipeline(
        self,
        config: AviationstackSourceConfig,
        resumable_source_manager: ResumableSourceManager[AviationstackResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aviationstack_source(
            access_key=config.access_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AVIATIONSTACK,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Aviationstack",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your aviationstack access key to pull real-time, scheduled, and historical flight data plus aviation reference tables into the PostHog Data warehouse.

You can find your access key in your [aviationstack dashboard](https://aviationstack.com/dashboard).

Note: aviationstack pricing is a monthly request quota tied to your plan. Some tables (e.g. historical flights and certain filters) require a paid plan.""",
            iconPath="/static/services/aviationstack.png",
            docsUrl="https://posthog.com/docs/cdp/sources/aviationstack",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_key",
                        label="Access key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
