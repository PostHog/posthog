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
from products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.appfollow import (
    AppfollowResumeConfig,
    appfollow_source,
    check_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.settings import (
    APPFOLLOW_ENDPOINTS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AppfollowSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AppfollowSource(ResumableSource[AppfollowSourceConfig, AppfollowResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.APPFOLLOW

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.APPFOLLOW,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="AppFollow",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your AppFollow API token to pull your app reviews and ratings into the PostHog Data warehouse.

An Account Owner or Admin can generate an API token on the [API management page](https://watch.appfollow.io/settings/api) in your AppFollow account. The token authenticates every request via the `X-AppFollow-API-Token` header.

Note that AppFollow bills API usage against a credit balance (reviews and ratings cost more per request) and rate-limits to 1000 requests/hour per token.""",
            iconPath="/static/services/appfollow.png",
            docsUrl="https://posthog.com/docs/cdp/sources/appfollow",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Your AppFollow API token",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # A bad token (401), an exhausted credit balance (402), or a permission problem (403) can't be
        # fixed by retrying. Match the stable status text and base host, not the per-request path/query.
        return {
            "401 Client Error: Unauthorized for url: https://api.appfollow.io": "Your AppFollow API token is invalid. Generate a new token on the API management page in your AppFollow account, then reconnect.",
            "402 Client Error: Payment Required for url: https://api.appfollow.io": "Your AppFollow account is out of API credits. Wait for your credit balance to reset or upgrade your plan, then retry the sync.",
            "403 Client Error: Forbidden for url: https://api.appfollow.io": "Your AppFollow API token does not have access to this data. Check the token's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: AppfollowSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = APPFOLLOW_ENDPOINTS[endpoint]
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
        self, config: AppfollowSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        status = check_credentials(config.api_key)
        if status is None:
            return False, "Could not reach AppFollow. Please try again."
        if status == 401:
            return False, "Invalid AppFollow API token"
        if status == 402:
            return False, "Your AppFollow account is out of API credits"
        if status in (200, 403):
            # A single account-wide token authenticates every endpoint, so a genuine 200 (or a 403 that
            # still proves the token is real) means the credentials are valid.
            return True, None
        return False, f"AppFollow returned status {status}"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AppfollowResumeConfig]:
        return ResumableSourceManager[AppfollowResumeConfig](inputs, AppfollowResumeConfig)

    def source_for_pipeline(
        self,
        config: AppfollowSourceConfig,
        resumable_source_manager: ResumableSourceManager[AppfollowResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return appfollow_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
