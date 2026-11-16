from typing import Optional, cast

from products.warehouse_sources.sources.planning_center._config import PlanningCenterSourceConfig
from products.warehouse_sources.sources.planning_center.planning_center import (
    PlanningCenterResumeConfig,
    planning_center_source,
    probe_endpoint_status,
    probe_status,
)
from products.warehouse_sources.sources.planning_center.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PLANNING_CENTER_ENDPOINTS,
    PRODUCT_LABELS,
)
from products.warehouse_sources.sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
    detect,
)

_INVALID_CREDENTIALS = (
    "Planning Center rejected the application ID or secret. Check the personal access token, then try again."
)


def _missing_access_message(product: str) -> str:
    label = PRODUCT_LABELS[product]
    return (
        f"Your Planning Center user can't read {label} data. "
        f"Give the user access to {label} in Planning Center, or deselect the {label} tables."
    )


@SourceRegistry.register
class PlanningCenterSource(ResumableSource[PlanningCenterSourceConfig, PlanningCenterResumeConfig]):
    codebase_detection = detect(
        npm=("@planningcenter/api-client",),
        rubygems=("pco_api",),
    )

    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs
    # Every product API lives under `/{product}/v2/`. Each product also takes its own dated
    # `X-PCO-API-Version` header, pinned per product in `settings.PRODUCT_API_VERSIONS`.
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developer.planning.center/docs/#/overview/versioning"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PLANNINGCENTER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PLANNINGCENTER,
            category=DataWarehouseSourceCategory.CRM,
            label="Planning Center",
            keywords=["pco", "church management"],
            caption=(
                "Import your People, Groups, Giving, Check-Ins, Services and Calendar data from Planning Center. "
                "Create a personal access token in your "
                "[Planning Center developer account](https://api.planningcenteronline.com/oauth/applications), "
                "then enter its application ID and secret below.\n\n"
                "The source reads the data that the token's user can see. Giving tables need a user with "
                "Giving permissions."
            ),
            iconPath="/static/services/planning_center.png",
            docsUrl="https://posthog.com/docs/cdp/sources/planning-center",
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="application_id",
                        label="Application ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="secret",
                        label="Secret",
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
            "401 Client Error: Unauthorized for url: https://api.planningcenteronline.com": (
                "Planning Center rejected the personal access token. Create a new token, then reconnect the source."
            ),
            "403 Client Error: Forbidden for url: https://api.planningcenteronline.com": (
                "Your Planning Center user can't read one of the tables you sync. Give the user access to that "
                "product in Planning Center, or deselect the table."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.planning_center.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: PlanningCenterSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            # `where[updated_at][gte]` returns the rows at the watermark again on every sync, so an
            # append sync would store a second copy of them. Merge on the primary key removes the copies.
            merge_only=[name for name, endpoint in PLANNING_CENTER_ENDPOINTS.items() if endpoint.incremental],
        )

    def validate_credentials(
        self,
        config: PlanningCenterSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None:
            if schema_name not in PLANNING_CENTER_ENDPOINTS:
                return False, f"Planning Center has no table named {schema_name}."
            status = probe_endpoint_status(config.application_id, config.secret, schema_name)
            if status == 403:
                return False, _missing_access_message(PLANNING_CENTER_ENDPOINTS[schema_name].product)
        else:
            # Every Planning Center user has a People profile, so the People root is the cheapest
            # request that checks the token. A 403 means the token is valid and the user can't read
            # People. The user can still sync other products, so the source is accepted.
            status = probe_status(config.application_id, config.secret, "/people/v2", "people")
            if status == 403:
                return True, None

        if status == 200:
            return True, None
        if status == 401:
            return False, _INVALID_CREDENTIALS
        return False, "Couldn't reach Planning Center to check the token. Try again in a few minutes."

    def get_endpoint_permissions(
        self,
        config: PlanningCenterSourceConfig,
        team_id: int,
        endpoints: list[str],
        api_version: str | None = None,
    ) -> dict[str, str | None]:
        # Access is granted per product, so one probe per product covers all of its tables.
        status_by_product: dict[str, Optional[int]] = {}
        permissions: dict[str, str | None] = {}
        for endpoint in endpoints:
            endpoint_config = PLANNING_CENTER_ENDPOINTS.get(endpoint)
            if endpoint_config is None:
                permissions[endpoint] = None
                continue
            product = endpoint_config.product
            if product not in status_by_product:
                status_by_product[product] = probe_endpoint_status(config.application_id, config.secret, endpoint)
            permissions[endpoint] = _missing_access_message(product) if status_by_product[product] == 403 else None
        return permissions

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PlanningCenterResumeConfig]:
        return ResumableSourceManager[PlanningCenterResumeConfig](inputs, PlanningCenterResumeConfig)

    def source_for_pipeline(
        self,
        config: PlanningCenterSourceConfig,
        resumable_source_manager: ResumableSourceManager[PlanningCenterResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return planning_center_source(
            application_id=config.application_id,
            secret=config.secret,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
