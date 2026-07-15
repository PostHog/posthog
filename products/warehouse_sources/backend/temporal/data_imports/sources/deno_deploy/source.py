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
from products.warehouse_sources.backend.temporal.data_imports.sources.deno_deploy.deno_deploy import (
    DenoDeployResumeConfig,
    deno_deploy_source,
    validate_credentials as validate_deno_deploy_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deno_deploy.settings import (
    DENO_DEPLOY_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DenoDeploySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DenoDeploySource(ResumableSource[DenoDeploySourceConfig, DenoDeployResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DENODEPLOY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DENO_DEPLOY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Deno Deploy",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter a Deno Deploy organization access token to sync your apps, revisions, domains, analytics, and runtime logs into the PostHog Data warehouse.

Create an organization access token in your [Deno Deploy dashboard](https://app.deno.com) under **Settings > Access Tokens**. The token is scoped to a single organization, so one connection syncs one Deno Deploy organization.""",
            iconPath="/static/services/deno_deploy.png",
            docsUrl="https://posthog.com/docs/cdp/sources/deno-deploy",
            keywords=["deno", "deploy", "serverless", "edge"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="ddo_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.deno_deploy.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid, revoked, or expired token surfaces as a requests HTTPError when `_fetch`
            # calls `raise_for_status()`. Retrying can never satisfy a credential problem, so stop the
            # sync. Match the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.deno.com": "Your Deno Deploy access token is invalid or has been revoked. Create a new organization access token in your Deno Deploy dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.deno.com": "Your Deno Deploy access token does not have permission to read this organization's data. Check the token's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: DenoDeploySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = DENO_DEPLOY_ENDPOINTS[endpoint]
            has_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: DenoDeploySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_deno_deploy_credentials(config.access_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DenoDeployResumeConfig]:
        return ResumableSourceManager[DenoDeployResumeConfig](inputs, DenoDeployResumeConfig)

    def source_for_pipeline(
        self,
        config: DenoDeploySourceConfig,
        resumable_source_manager: ResumableSourceManager[DenoDeployResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return deno_deploy_source(
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
