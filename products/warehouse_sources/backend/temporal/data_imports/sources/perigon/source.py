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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.perigon import (
    PerigonSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.perigon.perigon import (
    PerigonResumeConfig,
    perigon_source,
    validate_credentials as validate_perigon_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.perigon.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PERIGON_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PerigonSource(ResumableSource[PerigonSourceConfig, PerigonResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.perigon.io/docs/overview"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PERIGON

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PERIGON,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Perigon",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["news", "media", "goperigon"],
            caption="""Enter your Perigon API key to sync news articles, story clusters, journalists, sources, people, companies, and topics into the PostHog Data warehouse.

You can find your API key on your [Perigon account dashboard](https://www.perigon.io/).

Datasets available to sync depend on your Perigon plan. Perigon caps each search to 10,000 results, so incremental syncs on articles and stories catch up across runs.""",
            iconPath="/static/services/perigon.png",
            docsUrl="https://posthog.com/docs/cdp/sources/perigon",
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
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # An invalid/revoked key (401) or a dataset outside the plan (403) surfaces as a
        # requests HTTPError; match the stable status text and base host, not the
        # per-request path/query.
        return {
            "401 Client Error: Unauthorized for url: https://api.perigon.io": "Your Perigon API key is invalid or has been revoked. Generate a new key on your Perigon account dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.perigon.io": "Your Perigon plan does not include access to this dataset. Deselect the table or upgrade your Perigon plan, then try again.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.perigon.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: PerigonSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Only articles and stories have a documented server-side timestamp filter; the
        # reference datasets are full refresh.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: PerigonSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        endpoint = PERIGON_ENDPOINTS.get(schema_name) if schema_name else None
        ok, status = validate_perigon_credentials(config.api_key, path=endpoint.path if endpoint else None)
        if ok:
            return True, None
        if status == 403:
            if schema_name is None:
                # The key is genuine; a plan may simply not include every dataset. Sync-time
                # 403s on specific tables are handled by get_non_retryable_errors.
                return True, None
            return False, f"Your Perigon plan does not include access to {schema_name}"
        if status == 401:
            return False, "Perigon API key is invalid or has been revoked"
        return False, "Could not validate Perigon credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PerigonResumeConfig]:
        return ResumableSourceManager[PerigonResumeConfig](inputs, PerigonResumeConfig)

    def source_for_pipeline(
        self,
        config: PerigonSourceConfig,
        resumable_source_manager: ResumableSourceManager[PerigonResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return perigon_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            logger=inputs.logger,
        )
