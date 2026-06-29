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
from products.warehouse_sources.backend.temporal.data_imports.sources.bugsnag.bugsnag import (
    BugsnagResumeConfig,
    bugsnag_source,
    validate_credentials as validate_bugsnag_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bugsnag.settings import (
    BUGSNAG_ENDPOINTS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BugsnagSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BugsnagSource(ResumableSource[BugsnagSourceConfig, BugsnagResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BUGSNAG

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BUGSNAG,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Bugsnag",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your BugSnag personal auth token to pull your BugSnag error-monitoring data into the PostHog Data warehouse.

You can generate a personal auth token in the **My Account** section of your [BugSnag account settings](https://app.bugsnag.com/settings/my-account/). The token inherits your account's access, so it can read every organization and project you can see.""",
            iconPath="/static/services/bugsnag.png",
            docsUrl="https://posthog.com/docs/cdp/sources/bugsnag",
            unreleasedSource=True,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="auth_token",
                        label="Auth token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Personal auth token",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # 401/403 surface as a requests HTTPError when `_fetch_page` calls `raise_for_status()`.
        # No amount of retrying fixes a bad or under-permissioned token, so stop the sync. Match the
        # stable status text and base host, not the per-request path/query.
        return {
            "401 Client Error: Unauthorized for url: https://api.bugsnag.com": "Your BugSnag auth token is invalid or has been revoked. Generate a new personal auth token in your BugSnag account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.bugsnag.com": "Your BugSnag auth token does not have access to this data. Check the token's account permissions, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.bugsnag.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: BugsnagSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "events":
                return "One row per captured event. Can be very large — full refresh only, off by default."
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = BUGSNAG_ENDPOINTS[endpoint]
            # Full refresh only: BugSnag exposes dashboard-style time filters on errors/events/releases,
            # but the filter+pagination behavior isn't verified against the live API yet, so we don't
            # advertise incremental rather than risk a sync that silently re-walks history.
            return SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
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
        self, config: BugsnagSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_bugsnag_credentials(config.auth_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BugsnagResumeConfig]:
        return ResumableSourceManager[BugsnagResumeConfig](inputs, BugsnagResumeConfig)

    def source_for_pipeline(
        self,
        config: BugsnagSourceConfig,
        resumable_source_manager: ResumableSourceManager[BugsnagResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return bugsnag_source(
            auth_token=config.auth_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
