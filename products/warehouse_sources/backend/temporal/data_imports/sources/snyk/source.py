from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SnykSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.snyk.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SNYK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.snyk.snyk import (
    SnykResumeConfig,
    snyk_source,
    validate_credentials as validate_snyk_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SnykSource(ResumableSource[SnykSourceConfig, SnykResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SNYK

    @property
    def connection_host_fields(self) -> list[str]:
        # The API token is sent to the host derived from `region`, so changing the region must
        # re-require the secret rather than reusing it against a different host. `organization_id`
        # selects which Snyk tenant the token reads, so retargeting it must also force re-entry —
        # otherwise an editor could point the preserved token at another organization it can access.
        return ["region", "organization_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SNYK,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Snyk",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Connect your Snyk account to sync organizations, projects, targets, and vulnerability issues into the PostHog Data warehouse.

Generate an API token from your [Snyk account settings](https://app.snyk.io/account) (or use a service account token from your organization or group settings). The token is sent as `Authorization: token <token>` and can read every organization it has access to.

Pick the region your Snyk account is hosted on — Snyk's regional stacks are independent and a token only works on its own region.""",
            iconPath="/static/services/snyk.png",
            docsUrl="https://posthog.com/docs/cdp/sources/snyk",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Snyk API token",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.snyk.io)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (api.eu.snyk.io)", value="eu"),
                            SourceFieldSelectConfigOption(label="AU (api.au.snyk.io)", value="au"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="organization_id",
                        label="Organization ID (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="Leave blank to sync every organization the token can access",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # 401/403 surface as a requests HTTPError when `_fetch_page` calls `raise_for_status()`.
        # No amount of retrying fixes a bad or under-permissioned token, so stop the sync.
        return {
            "401 Client Error: Unauthorized for url": "Your Snyk API token is invalid or has been revoked. Generate a new token in your Snyk account settings, then reconnect.",
            "403 Client Error: Forbidden for url": "Your Snyk API token does not have access to this data. Check the token's role and organization access, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.snyk.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SnykSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=SNYK_ENDPOINTS[endpoint].supports_incremental,
                supports_append=SNYK_ENDPOINTS[endpoint].supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: SnykSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        return validate_snyk_credentials(config.region, config.api_token, config.organization_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SnykResumeConfig]:
        return ResumableSourceManager[SnykResumeConfig](inputs, SnykResumeConfig)

    def source_for_pipeline(
        self,
        config: SnykSourceConfig,
        resumable_source_manager: ResumableSourceManager[SnykResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return snyk_source(
            region=config.region,
            api_token=config.api_token,
            organization_id=config.organization_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
