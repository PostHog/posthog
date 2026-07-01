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
from products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.appfigures import (
    AppfiguresResumeConfig,
    appfigures_source,
    check_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.settings import (
    APPFIGURES_ENDPOINTS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AppfiguresSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AppfiguresSource(ResumableSource[AppfiguresSourceConfig, AppfiguresResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.APPFIGURES

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.APPFIGURES,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Appfigures",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter an Appfigures Personal Access Token to pull your app-store analytics into the PostHog Data warehouse.

Create an API client and Personal Access Token at [appfigures.com/developers/keys](https://appfigures.com/developers/keys). When creating the client, grant the data sets you want to sync:
- `products:read` — Products
- `public:read` — Reviews
- `private:read` — Sales and Revenue reports
""",
            iconPath="/static/services/appfigures.png",
            docsUrl="https://posthog.com/docs/cdp/sources/appfigures",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="personal_access_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="pat_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # A bad/expired token (401) or a token missing the endpoint's scope (403) can't be fixed by
        # retrying. Match the stable status text and base host, not the per-request path/query.
        return {
            "401 Client Error: Unauthorized for url: https://api.appfigures.com": "Your Appfigures personal access token is invalid or expired. Create a new token in your Appfigures developer settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.appfigures.com": "Your Appfigures personal access token is missing the scope needed to sync this data. Grant the required data sets to your API client, then reconnect.",
        }

    def get_schemas(
        self,
        config: AppfiguresSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = APPFIGURES_ENDPOINTS[endpoint]
            has_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                detected_primary_keys=endpoint_config.primary_keys,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: AppfiguresSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # Probe the endpoint the requested schema actually hits (so per-table scope checks are
        # accurate), or the cheap products catalog at source-create.
        path = "/products/mine"
        if schema_name and schema_name in APPFIGURES_ENDPOINTS:
            path = APPFIGURES_ENDPOINTS[schema_name].path

        status = check_credentials(config.personal_access_token, path)
        if status is None:
            return False, "Could not reach Appfigures. Please try again."
        if status == 401:
            return False, "Invalid Appfigures personal access token"
        if status == 403:
            # A valid token may simply lack this endpoint's scope. Don't block source-create over it;
            # only fail when validating a specific schema the user chose to sync.
            if schema_name:
                return False, f"Your token is missing the scope required to sync '{schema_name}'"
            return True, None
        if status == 200:
            return True, None
        return False, f"Appfigures returned status {status}"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AppfiguresResumeConfig]:
        return ResumableSourceManager[AppfiguresResumeConfig](inputs, AppfiguresResumeConfig)

    def source_for_pipeline(
        self,
        config: AppfiguresSourceConfig,
        resumable_source_manager: ResumableSourceManager[AppfiguresResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return appfigures_source(
            token=config.personal_access_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
