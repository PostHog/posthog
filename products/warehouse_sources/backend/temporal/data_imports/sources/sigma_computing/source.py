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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sigmacomputing import (
    SigmaComputingSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sigma_computing.settings import (
    DEFAULT_REGION,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sigma_computing.sigma_computing import (
    SigmaComputingResumeConfig,
    sigma_computing_source,
    validate_credentials as validate_sigma_computing_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

REGION_OPTIONS = [
    SourceFieldSelectConfigOption(label="GCP - United States (Iowa)", value="gcp_us"),
    SourceFieldSelectConfigOption(label="GCP - Saudi Arabia (Dammam)", value="gcp_sa"),
    SourceFieldSelectConfigOption(label="AWS - United States West (Oregon)", value="aws_us_west"),
    SourceFieldSelectConfigOption(label="AWS - United States East (N. Virginia)", value="aws_us_east"),
    SourceFieldSelectConfigOption(label="AWS - Canada (Central)", value="aws_ca"),
    SourceFieldSelectConfigOption(label="AWS - Europe (Frankfurt)", value="aws_eu"),
    SourceFieldSelectConfigOption(label="AWS - Asia Pacific (Sydney)", value="aws_au"),
    SourceFieldSelectConfigOption(label="AWS - United Kingdom (London)", value="aws_uk"),
    SourceFieldSelectConfigOption(label="Azure - United States (Virginia)", value="azure_us"),
    SourceFieldSelectConfigOption(label="Azure - Europe (Netherlands)", value="azure_eu"),
    SourceFieldSelectConfigOption(label="Azure - Canada (Toronto)", value="azure_ca"),
    SourceFieldSelectConfigOption(label="Azure - United Kingdom (London)", value="azure_uk"),
    SourceFieldSelectConfigOption(label="Azure - Australia (New South Wales)", value="azure_au"),
]


@SourceRegistry.register
class SigmaComputingSource(ResumableSource[SigmaComputingSourceConfig, SigmaComputingResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://help.sigmacomputing.com/reference/get-started-sigma-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SIGMACOMPUTING

    @property
    def connection_host_fields(self) -> list[str]:
        # `region` picks the host the client ID/secret are sent to; retargeting it must
        # re-require those secrets.
        return ["region"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "Sigma rejected the API client credentials": "Sigma rejected your API client credentials. Please check the client ID and secret and reconnect.",
            "401 Client Error": "Sigma rejected the access token. Please check the client ID and secret, then reconnect.",
            "403 Client Error": "Your Sigma API client does not have permission for this resource.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.sigma_computing.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SigmaComputingSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: SigmaComputingSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_sigma_computing_credentials(
            region=config.region,
            client_id=config.client_id,
            client_secret=config.client_secret,
            schema_name=schema_name,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SigmaComputingResumeConfig]:
        return ResumableSourceManager[SigmaComputingResumeConfig](inputs, SigmaComputingResumeConfig)

    def source_for_pipeline(
        self,
        config: SigmaComputingSourceConfig,
        resumable_source_manager: ResumableSourceManager[SigmaComputingResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return sigma_computing_source(
            region=config.region,
            client_id=config.client_id,
            client_secret=config.client_secret,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SIGMA_COMPUTING,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Sigma Computing",
            caption="""Connect Sigma Computing to pull your workbook, data model, connection, and membership metadata into the PostHog Data warehouse.

Generate a client ID and secret from **Administration > Developer Access** in Sigma, then pick the deployment region shown on that same page (or under **Account > General Settings**).""",
            iconPath="/static/services/sigma_computing.png",
            docsUrl="https://posthog.com/docs/cdp/sources/sigma-computing",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["bi", "business intelligence"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="region",
                        label="Deployment region",
                        required=True,
                        defaultValue=DEFAULT_REGION,
                        options=REGION_OPTIONS,
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
                ],
            ),
        )
