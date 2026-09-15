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

from products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.cal_com import (
    ORGANIZATION_REQUIRED_ERROR,
    CalComResumeConfig,
    cal_com_source,
    check_organization_access,
    resolve_organization_id,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.settings import (
    CAL_COM_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    endpoint_requires_organization,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.calcom import CalComSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CalComSource(ResumableSource[CalComSourceConfig, CalComResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://cal.com/docs/api-reference/v2/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CALCOM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CAL_COM,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Cal.com",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Cal.com API key to pull your scheduling data into the PostHog Data warehouse.

You can create an API key under **Settings → Security → API keys** in [Cal.com](https://app.cal.com/settings/developer/api-keys). The key grants read access to your bookings, attendees, event types, schedules, teams, and webhooks.

The organization tables (memberships, users, and routing forms) need a key from a Cal.com organization admin. If your account isn't in an organization, leave those tables unselected.

Pick the region your Cal.com account lives in. Choose EU if you sign in at cal.eu, since a key from one region is not valid in the other.
""",
            iconPath="/static/services/cal_com.png",
            docsUrl="https://posthog.com/docs/cdp/sources/cal-com",
            keywords=["calcom", "scheduling", "booking"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="cal_live_...",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.cal.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (api.cal.eu)", value="eu"),
                        ],
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Keyed without a host so both the US and EU hosts match.
        return {
            "401 Client Error: Unauthorized": "Your Cal.com API key is invalid, has been revoked, or belongs to Cal.com's other region. Check the selected region, or create a new API key under Settings → Security → API keys in Cal.com, then reconnect.",
            "403 Client Error: Forbidden": "Your Cal.com API key does not have access to this data. Check the key owner's permissions in Cal.com, then reconnect.",
            # Retrying cannot conjure an organization for an account that has none.
            "is not in a Cal.com organization": ORGANIZATION_REQUIRED_ERROR,
        }

    def get_schemas(
        self,
        config: CalComSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def get_endpoint_permissions(
        self, config: CalComSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        # Report a table that can only fail here, rather than letting the user pick it.
        org_endpoints = {
            name for name in endpoints if name in CAL_COM_ENDPOINTS and endpoint_requires_organization(name)
        }
        if not org_endpoints:
            return dict.fromkeys(endpoints)

        try:
            organization_id = resolve_organization_id(config.api_key, config.region)
            reason = (
                ORGANIZATION_REQUIRED_ERROR
                if organization_id is None
                else check_organization_access(config.api_key, organization_id, config.region)
            )
        except Exception:  # noqa: BLE001 — an unreachable probe must not hide the tables
            reason = None

        return {name: reason if name in org_endpoints else None for name in endpoints}

    def validate_credentials(
        self,
        config: CalComSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        # The API key is account-wide, so a single probe validates access to every schema.
        return validate_credentials(config.api_key, config.region)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CalComResumeConfig]:
        return ResumableSourceManager[CalComResumeConfig](inputs, CalComResumeConfig)

    def source_for_pipeline(
        self,
        config: CalComSourceConfig,
        resumable_source_manager: ResumableSourceManager[CalComResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in CAL_COM_ENDPOINTS:
            raise ValueError(f"Unknown Cal.com schema '{inputs.schema_name}'")

        # Resolved in sync source-build context, not from the pipeline's iterator threads.
        organization_id = (
            resolve_organization_id(config.api_key, config.region)
            if endpoint_requires_organization(inputs.schema_name)
            else None
        )

        return cal_com_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            region=config.region,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
            organization_id=organization_id,
        )
