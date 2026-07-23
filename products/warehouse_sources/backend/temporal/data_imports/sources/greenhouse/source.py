from datetime import date
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    FieldType,
    ResumableSource,
    VersionDeprecation,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAUTH2_PERMANENT_ERROR_MARKER,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.greenhouse import (
    GreenhouseSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.greenhouse import (
    MISSING_V3_CREDENTIALS_ERROR,
    GreenhouseResumeConfig,
    greenhouse_source,
    validate_credentials as validate_greenhouse_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.settings import (
    ENDPOINTS,
    GREENHOUSE_ENDPOINTS,
    GREENHOUSE_V1,
    GREENHOUSE_V3,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GreenhouseSource(ResumableSource[GreenhouseSourceConfig, GreenhouseResumeConfig]):
    supported_versions = (GREENHOUSE_V1, GREENHOUSE_V3)
    default_version = GREENHOUSE_V3
    api_docs_url = "https://harvestdocs.greenhouse.io"
    # Greenhouse removes the v1/v2 Harvest API on 2026-08-31 in favour of v3.
    deprecated_versions = (VersionDeprecation(version=GREENHOUSE_V1, sunset_at=date(2026, 8, 31)),)

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GREENHOUSE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GREENHOUSE,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Greenhouse",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Greenhouse Harvest credentials to automatically pull your Greenhouse recruiting data into the PostHog Data warehouse.

Create credentials in Greenhouse under **Configure → Dev Center → API Credential Management**.

New connections use Harvest v3, which needs a **Harvest V3 (OAuth)** credential — enter its client ID and client secret. Grant it the list scopes for the resources you want to sync (for example `harvest:candidates:list`), and make sure the authorizing user is a site admin, since every list endpoint requires one.

The API key field is only for connections still on Harvest v1, which Greenhouse removes on 31 August 2026.""",
            iconPath="/static/services/greenhouse.png",
            docsUrl="https://posthog.com/docs/cdp/sources/greenhouse",
            fields=cast(
                list[FieldType],
                # No field is required at the form level because the two versions take different
                # secrets — v3 the OAuth client pair, v1 the API key. `validate_credentials`
                # enforces the pair the resolved version actually needs.
                [
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID (Harvest v3)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="Client secret (Harvest v3)",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key (Harvest v1)",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: GreenhouseSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: GreenhouseSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        # The probe differs by version (path segment, and Basic vs Bearer), so a v1-pinned source
        # must be probed on v1 even though new sources default to v3.
        version = self.resolve_api_version(api_version)

        # At source-create (`schema_name is None`) accept a 403 — the credential may legitimately
        # be scoped only to the endpoints the user wants. For a per-schema check, probe that
        # endpoint and surface a missing-scope error.
        if schema_name is not None and schema_name in GREENHOUSE_ENDPOINTS:
            return validate_greenhouse_credentials(
                version,
                api_key=config.api_key,
                client_id=config.client_id,
                client_secret=config.client_secret,
                path=GREENHOUSE_ENDPOINTS[schema_name].path_for_version(version),
                accept_forbidden=False,
            )

        return validate_greenhouse_credentials(
            version,
            api_key=config.api_key,
            client_id=config.client_id,
            client_secret=config.client_secret,
            accept_forbidden=True,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://harvest.greenhouse.io": "Your Greenhouse credentials are invalid or expired. Please generate new credentials and reconnect.",
            "403 Client Error: Forbidden for url: https://harvest.greenhouse.io": "Your Greenhouse credentials do not have the required permissions. Please grant read access to this resource and try again. Harvest v3 list endpoints also require the authorizing user to be a site admin.",
            OAUTH2_PERMANENT_ERROR_MARKER: "Greenhouse authentication failed. Please check the client ID and client secret of your Harvest V3 (OAuth) credential.",
            MISSING_V3_CREDENTIALS_ERROR: None,
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GreenhouseResumeConfig]:
        return ResumableSourceManager[GreenhouseResumeConfig](inputs, GreenhouseResumeConfig)

    def source_for_pipeline(
        self,
        config: GreenhouseSourceConfig,
        resumable_source_manager: ResumableSourceManager[GreenhouseResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return greenhouse_source(
            api_key=config.api_key,
            client_id=config.client_id,
            client_secret=config.client_secret,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
