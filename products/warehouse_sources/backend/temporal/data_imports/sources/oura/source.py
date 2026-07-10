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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OuraSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.oura.oura import (
    OuraResumeConfig,
    oura_source,
    probe_endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.oura.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    OURA_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OuraSource(ResumableSource[OuraSourceConfig, OuraResumeConfig]):
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://cloud.ouraring.com/v2/docs"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OURA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OURA,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Oura",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Oura personal access token to automatically pull your Oura Ring health data into the PostHog Data warehouse.

You can create a personal access token in the [Oura developer portal](https://cloud.ouraring.com/personal-access-tokens).
""",
            iconPath="/static/services/oura.png",
            docsUrl="https://posthog.com/docs/cdp/sources/oura",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch_page` calls `raise_for_status()`.
            # Retrying can never satisfy a credential/scope problem, so stop the sync. Match the
            # stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.ouraring.com": "Your Oura access token is invalid or has been revoked. Create a new personal access token in the Oura developer portal, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.ouraring.com": "Your Oura access token is missing the scopes needed to sync this data. Grant the required scopes, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.oura.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: OuraSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = OURA_ENDPOINTS[endpoint]
            # Only endpoints with a server-side date filter can sync incrementally; the others
            # (personal_info, ring_configuration) are full refresh only.
            has_incremental = endpoint_config.date_filter is not None
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
        self, config: OuraSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # Probe the requested endpoint when validating a specific schema, otherwise the cheap
        # single-document personal_info endpoint at source-create.
        path = OURA_ENDPOINTS[schema_name].path if schema_name in OURA_ENDPOINTS else "/usercollection/personal_info"
        status = probe_endpoint(config.access_token, path)

        if status == 200:
            return True, None
        if status == 401:
            return False, "Invalid Oura access token"
        # A valid token can legitimately lack scope for an endpoint the user isn't trying to sync;
        # accept 403 at source-create and only reject it when validating a specific schema.
        if status == 403 and schema_name is None:
            return True, None
        if status == 403:
            return False, f"Your Oura access token is missing the scope required for {schema_name}"

        return False, "Could not validate Oura access token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OuraResumeConfig]:
        return ResumableSourceManager[OuraResumeConfig](inputs, OuraResumeConfig)

    def source_for_pipeline(
        self,
        config: OuraSourceConfig,
        resumable_source_manager: ResumableSourceManager[OuraResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return oura_source(
            token=config.access_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
