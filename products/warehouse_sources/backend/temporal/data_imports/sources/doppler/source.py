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
from products.warehouse_sources.backend.temporal.data_imports.sources.doppler.doppler import (
    DopplerResumeConfig,
    doppler_source,
    validate_credentials as validate_doppler_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.doppler.settings import (
    DOPPLER_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DopplerSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DopplerSource(ResumableSource[DopplerSourceConfig, DopplerResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DOPPLER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DOPPLER,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Doppler",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter a Doppler API token to pull your Doppler projects, configs, and activity logs into the PostHog Data warehouse for audit and change tracking. Secret values are never synced.

Use a [personal token](https://docs.doppler.com/docs/personal-tokens) or a [service account token](https://docs.doppler.com/docs/service-accounts) with read access to the workplace and the projects you want to sync.""",
            iconPath="/static/services/doppler.png",
            docsUrl="https://posthog.com/docs/cdp/sources/doppler",
            keywords=["secrets"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="dp.pt....",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.doppler.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch_page` calls `raise_for_status()`.
            # Retrying can never fix a credential/permission problem, so fail the sync. Match the
            # stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.doppler.com": "Your Doppler API token is invalid or has been revoked. Create a new token in your Doppler dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.doppler.com": "Your Doppler API token is missing the read access needed to sync this data. Check the token's workplace and project access, then reconnect.",
        }

    def get_schemas(
        self,
        config: DopplerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = DOPPLER_ENDPOINTS[endpoint]
            has_incremental = bool(endpoint_config.incremental_fields)
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                # Crash-resume can re-yield the last batch (resume state saves after yield), so
                # only merge — which dedupes on the primary key — is safe; append would duplicate.
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                description=(
                    "Workplace activity log of project, config, and access changes. Incremental syncs "
                    "stop paging once they reach already-synced entries."
                    if endpoint == "activity_logs"
                    else None
                ),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: DopplerSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        ok, status_code = validate_doppler_credentials(config.api_token)

        if ok:
            return True, None
        if status_code == 401:
            return False, "Invalid Doppler API token"
        return False, "Could not connect to Doppler with the provided API token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DopplerResumeConfig]:
        return ResumableSourceManager[DopplerResumeConfig](inputs, DopplerResumeConfig)

    def source_for_pipeline(
        self,
        config: DopplerSourceConfig,
        resumable_source_manager: ResumableSourceManager[DopplerResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return doppler_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
