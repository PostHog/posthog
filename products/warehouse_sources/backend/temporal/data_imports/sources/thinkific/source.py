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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ThinkificSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific.settings import (
    ENDPOINTS,
    THINKIFIC_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific.thinkific import (
    ThinkificResumeConfig,
    is_valid_subdomain,
    thinkific_source,
    validate_credentials as validate_thinkific_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ThinkificSource(ResumableSource[ThinkificSourceConfig, ThinkificResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.THINKIFIC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.THINKIFIC,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Thinkific",
            caption="""Enter your Thinkific API key and account subdomain to pull your Thinkific course, enrollment, and order data into the PostHog Data warehouse.

You can create an API key under **Settings → Code & analytics → API** in your Thinkific admin. The subdomain is the `<subdomain>` part of your `<subdomain>.thinkific.com` admin URL.""",
            iconPath="/static/services/thinkific.png",
            docsUrl="https://posthog.com/docs/cdp/sources/thinkific",
            keywords=["lms", "elearning", "e-learning", "courses"],
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
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
                        name="subdomain",
                        label="Subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="mycompany",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid/revoked API key or wrong subdomain surfaces as an HTTPError when `_fetch_page`
            # calls `raise_for_status()`. Retrying can never fix a credential problem, so stop the sync.
            "401 Client Error: Unauthorized for url: https://api.thinkific.com": "Your Thinkific API key or subdomain is invalid. Create a new API key in your Thinkific admin (Settings → Code & analytics → API) and confirm the subdomain, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.thinkific.com": "Your Thinkific API key does not have permission to access this data. Check the key in your Thinkific admin, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ThinkificSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=THINKIFIC_ENDPOINTS[endpoint].supports_incremental,
                supports_append=THINKIFIC_ENDPOINTS[endpoint].supports_incremental,
                incremental_fields=THINKIFIC_ENDPOINTS[endpoint].incremental_fields,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: ThinkificSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if not is_valid_subdomain(config.subdomain):
            return False, "Thinkific subdomain is invalid"

        endpoint_path = THINKIFIC_ENDPOINTS[schema_name].path if schema_name in THINKIFIC_ENDPOINTS else "/courses"
        is_valid, status_code = validate_thinkific_credentials(config.api_key, config.subdomain, endpoint_path)
        if is_valid:
            return True, None

        # Accept a 403 at source-create (schema_name is None): the key is genuine but lacks access to
        # the probed endpoint, which is fine when the user only wants to sync endpoints they can read.
        # Per-schema checks (schema_name set) still surface the 403.
        if status_code == 403 and schema_name is None:
            return True, None

        return False, "Invalid Thinkific API key or subdomain"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ThinkificResumeConfig]:
        return ResumableSourceManager[ThinkificResumeConfig](inputs, ThinkificResumeConfig)

    def source_for_pipeline(
        self,
        config: ThinkificSourceConfig,
        resumable_source_manager: ResumableSourceManager[ThinkificResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return thinkific_source(
            api_key=config.api_key,
            subdomain=config.subdomain,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
