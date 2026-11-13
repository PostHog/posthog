from typing import Optional, cast

from requests.exceptions import RequestException

from products.warehouse_sources.sources.sdk import (
    NOT_DETECTABLE,
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
)
from products.warehouse_sources.sources.simpro._config import SimproSourceConfig
from products.warehouse_sources.sources.simpro.settings import ENDPOINTS, INCREMENTAL_FIELDS, SIMPRO_API_VERSION
from products.warehouse_sources.sources.simpro.simpro import (
    SimproBuildURLError,
    SimproResumeConfig,
    SimproUnexpectedResponseError,
    check_credentials,
    normalize_build_host,
    parse_company_id,
    simpro_source,
)

INVALID_BUILD_MESSAGE = (
    "Enter your Simpro build name or URL, for example `acme` or `acme.simprosuite.com`. "
    "Simpro builds are hosted on simprosuite.com or simprocloud.com."
)


@SourceRegistry.register
class SimproSource(ResumableSource[SimproSourceConfig, SimproResumeConfig]):
    codebase_detection = NOT_DETECTABLE

    lists_tables_without_credentials = True
    supported_versions = (SIMPRO_API_VERSION,)
    default_version = SIMPRO_API_VERSION
    api_docs_url = "https://developer.simprogroup.com/apidoc/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SIMPRO

    @property
    def connection_host_fields(self) -> list[str]:
        # The API key is sent to the build's host, so changing the build must re-require the key.
        return ["build"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": (
                "Simpro rejected your API key. Create a new API key application in Simpro, then update the source."
            ),
            "403 Client Error: Forbidden for url": (
                "Your Simpro API key can't read one of the tables you sync. "
                "Check the security group of the API key application in Simpro, then reconnect the source."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.simpro.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SimproSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # The DateModified filter works by day, so each incremental read overlaps the last one.
        # Append would store the overlap twice, so incremental tables only merge.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=tuple(INCREMENTAL_FIELDS))

    def validate_credentials(
        self,
        config: SimproSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            host = normalize_build_host(config.build)
        except SimproBuildURLError:
            return False, INVALID_BUILD_MESSAGE

        try:
            company_id = parse_company_id(config.company_id)
        except ValueError:
            return False, "The company ID must be a number. Leave it blank to sync every company in your build."

        try:
            result = check_credentials(host, config.api_key)
        except SimproUnexpectedResponseError:
            return False, f"{host} didn't answer like a Simpro build. Check the Simpro build and try again."
        except RequestException:
            return False, f"Couldn't reach Simpro at {host}. Check the Simpro build and try again."

        if result.status_code == 401:
            return False, "Simpro rejected the API key. Check that you copied the access token from the key file."
        if result.status_code == 403 and company_id is not None:
            # The key can't list companies, but it can still read the tables of the company the user named.
            return True, None
        if result.status_code == 403:
            return False, (
                "This API key can't list the companies in your build. "
                "Enter the company ID to sync, or give the key access to companies in Simpro."
            )
        if result.status_code == 404:
            return False, f"No Simpro API found at {host}. Check the Simpro build and try again."
        if not result.ok:
            return False, f"Simpro returned an unexpected status ({result.status_code}). Try again later."

        if company_id is not None and result.company_ids and company_id not in result.company_ids:
            return (
                False,
                f"Company {company_id} doesn't exist in this build. Leave the company ID blank to sync every company.",
            )
        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SimproResumeConfig]:
        return ResumableSourceManager[SimproResumeConfig](inputs, SimproResumeConfig)

    def source_for_pipeline(
        self,
        config: SimproSourceConfig,
        resumable_source_manager: ResumableSourceManager[SimproResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return simpro_source(
            build=config.build,
            api_key=config.api_key,
            company_id=config.company_id,
            endpoint=inputs.schema_name,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SIMPRO,
            category=DataWarehouseSourceCategory.CRM,
            label="Simpro",
            caption=(
                "Sync customers, sites, jobs, quotes, leads, invoices and more from your Simpro build.\n\n"
                "To create an API key, a Simpro administrator goes to **System > Setup > API > Applications**, "
                "creates an application with the **API Key** grant type, and downloads the key file. "
                "Paste the access token from the key file below."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/simpro",
            iconPath="/static/warehouse-sources/simpro/icon.png",
            keywords=["simprogroup", "field service"],
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="build",
                        label="Simpro build",
                        caption="The build name or URL you sign in to, such as `acme` or `acme.simprocloud.com`.",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="acme.simprosuite.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="company_id",
                        label="Company ID",
                        caption="Leave blank to sync every company in a multi-company build.",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="0",
                        secret=False,
                    ),
                ],
            ),
        )
