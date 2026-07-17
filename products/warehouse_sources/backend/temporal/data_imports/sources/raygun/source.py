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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RaygunSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.raygun.raygun import (
    RaygunResumeConfig,
    raygun_source,
    validate_token,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.raygun.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

RAYGUN_CAPTION = """Enter a Raygun [personal access token](https://raygun.com/documentation/product-guides/apis/personal-access-tokens/) to pull your Raygun crash reporting and real user monitoring data into the PostHog Data warehouse.

Grant the token these read scopes for the tables you want to sync:
- `applications:read` — Applications
- `cr.errors:read` — Error groups
- `deployments:read` — Deployments
- `customers:read` — Customers
- `rum.sessions:read` — Sessions
- `rum.pages:read` — Pages
"""


@SourceRegistry.register
class RaygunSource(ResumableSource[RaygunSourceConfig, RaygunResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RAYGUN

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.raygun.com": "Your Raygun personal access token is invalid or has been revoked. Create a new token in your Raygun account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.raygun.com": "Your Raygun personal access token is missing a read scope needed to sync this data. Grant the required scope to the token, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.raygun.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: RaygunSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Raygun exposes no server-side "updated since" filter, so every endpoint is full refresh —
        # no endpoint declares incremental fields, so none support incremental/append sync.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self, config: RaygunSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        is_valid, status_code = validate_token(config.personal_access_token)
        if is_valid:
            return True, None

        # A valid token may legitimately lack a scope for endpoints the user won't sync. Accept 403
        # at source-create (schema_name is None); only reject it for a specific schema probe.
        if status_code == 403 and schema_name is None:
            return True, None

        if status_code == 401:
            return False, "Invalid Raygun personal access token"
        if status_code == 403:
            return False, "Your Raygun personal access token is missing the read scope for this table"

        return False, "Could not validate Raygun personal access token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RaygunResumeConfig]:
        return ResumableSourceManager[RaygunResumeConfig](inputs, RaygunResumeConfig)

    def source_for_pipeline(
        self,
        config: RaygunSourceConfig,
        resumable_source_manager: ResumableSourceManager[RaygunResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return raygun_source(
            personal_access_token=config.personal_access_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=None,  # every Raygun endpoint is full refresh
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RAYGUN,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Raygun",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=RAYGUN_CAPTION,
            iconPath="/static/services/raygun.png",
            docsUrl="https://posthog.com/docs/cdp/sources/raygun",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="personal_access_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
