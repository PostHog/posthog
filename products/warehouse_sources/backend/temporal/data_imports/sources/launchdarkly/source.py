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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LaunchDarklySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.launchdarkly import (
    LaunchDarklyResumeConfig,
    launchdarkly_source,
    validate_credentials as validate_launchdarkly_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LAUNCHDARKLY_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LaunchDarklySource(ResumableSource[LaunchDarklySourceConfig, LaunchDarklyResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LAUNCHDARKLY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LAUNCH_DARKLY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            keywords=["feature flags"],
            label="LaunchDarkly",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your LaunchDarkly access token to pull your projects, environments, feature flags, metrics, members, and audit log into the PostHog Data warehouse.

You can create a personal or service access token in your [LaunchDarkly account settings](https://app.launchdarkly.com/settings/authorization). A token with the **Reader** role grants read access to every resource this source syncs.""",
            iconPath="/static/services/launchdarkly.png",
            docsUrl="https://posthog.com/docs/cdp/sources/launchdarkly",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="api-...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your LaunchDarkly access token is invalid or expired. Please generate a new token and reconnect.",
            "403 Client Error": "Your LaunchDarkly access token does not have permission for this resource. Please check the token's role and try again.",
        }

    def get_schemas(
        self,
        config: LaunchDarklySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # LaunchDarkly's API exposes no server-side timestamp filter on these resources,
        # so every endpoint is full-refresh only (no incremental/append support).
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: LaunchDarklySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # Fan-out endpoints can't be probed without a project key, so confirm scope against
        # /projects (their prerequisite); top-level endpoints probe their own path.
        probe_path = "/caller-identity"
        if schema_name is not None:
            endpoint = LAUNCHDARKLY_ENDPOINTS.get(schema_name)
            if endpoint is not None:
                probe_path = "/projects" if endpoint.requires_project else endpoint.path

        status = validate_launchdarkly_credentials(config.access_token, probe_path)

        if status is None:
            return False, "Could not reach LaunchDarkly. Please try again."
        if status == 401:
            return False, "Invalid LaunchDarkly access token"
        # A valid token may legitimately lack scope for a specific endpoint. Accept 403 at
        # source-create (schema_name is None); only reject it for a specific schema check.
        if status == 403:
            if schema_name is None:
                return True, None
            return False, f"Your access token does not have permission to read '{schema_name}'"
        if status >= 400:
            return False, f"LaunchDarkly returned an unexpected status ({status})"
        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LaunchDarklyResumeConfig]:
        return ResumableSourceManager[LaunchDarklyResumeConfig](inputs, LaunchDarklyResumeConfig)

    def source_for_pipeline(
        self,
        config: LaunchDarklySourceConfig,
        resumable_source_manager: ResumableSourceManager[LaunchDarklyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return launchdarkly_source(
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
