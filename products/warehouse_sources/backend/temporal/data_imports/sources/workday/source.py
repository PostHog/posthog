from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.workday import (
    WorkdaySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.workday.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.workday.workday import (
    HOST_NOT_ALLOWED_ERROR,
    TOKEN_ERROR,
    WorkdayResumeConfig,
    validate_credentials as validate_workday_credentials,
    workday_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WorkdaySource(ResumableSource[WorkdaySourceConfig, WorkdayResumeConfig]):
    # Workday versions each REST service separately. The Staffing service carries all but one
    # of the endpoints below, so its version is what a source pins; the Common service that
    # serves `workers` is fixed at the `/ccx/api/v1` path.
    supported_versions = ("v7",)
    default_version = "v7"
    api_docs_url = "https://community.workday.com/sites/default/files/file-hosting/restapi/index.html"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WORKDAY

    @property
    def connection_host_fields(self) -> list[str]:
        # `hostname` is where the stored client secret and refresh token are sent; retargeting
        # it must re-require those secrets.
        return ["hostname"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WORKDAY,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Workday",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Pull your Workday HCM data into the PostHog Data warehouse over the Workday REST API.

Register an API client for integrations in Workday (**Register API Client for Integrations**) with the `staffing` scope, then paste its client ID, client secret and refresh token below.

Your hostname and tenant are the first two parts of your Workday URL — for `https://wd2-impl-services1.workday.com/acme_pt1`, the hostname is `wd2-impl-services1.workday.com` and the tenant is `acme_pt1`.""",
            iconPath="/static/services/workday.png",
            docsUrl="https://posthog.com/docs/cdp/sources/workday",
            keywords=["hcm", "hris"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="hostname",
                        label="Hostname",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="wd2-impl-services1.workday.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="tenant",
                        label="Tenant",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="acme_pt1",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="Client secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="refresh_token",
                        label="Refresh token",
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
            TOKEN_ERROR: "Workday rejected your API client credentials. Please check the client ID, secret and refresh token, then reconnect.",
            "401 Client Error": "Workday rejected the access token. Please reconnect the source with a fresh refresh token.",
            "403 Client Error": "Your Workday API client is not authorized for this resource. Please check its scopes and domain security policies.",
            HOST_NOT_ALLOWED_ERROR: "The Workday hostname is not allowed. Please use your tenant's Workday hostname.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.workday.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: WorkdaySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: WorkdaySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_workday_credentials(
            hostname=config.hostname,
            tenant=config.tenant,
            client_id=config.client_id,
            client_secret=config.client_secret,
            refresh_token=config.refresh_token,
            staffing_version=self.resolve_api_version(api_version),
            schema_name=schema_name,
            team_id=team_id,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[WorkdayResumeConfig]:
        return ResumableSourceManager[WorkdayResumeConfig](inputs, WorkdayResumeConfig)

    def source_for_pipeline(
        self,
        config: WorkdaySourceConfig,
        resumable_source_manager: ResumableSourceManager[WorkdayResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return workday_source(
            hostname=config.hostname,
            tenant=config.tenant,
            client_id=config.client_id,
            client_secret=config.client_secret,
            refresh_token=config.refresh_token,
            endpoint=inputs.schema_name,
            staffing_version=self.resolve_api_version(inputs.api_version),
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
