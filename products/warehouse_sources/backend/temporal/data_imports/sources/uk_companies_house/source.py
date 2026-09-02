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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ukcompanieshouse import (
    UkCompaniesHouseSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.uk_companies_house.settings import (
    DESCRIPTIONS,
    ENDPOINT_SPECS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.uk_companies_house.uk_companies_house import (
    UkCompaniesHouseResumeConfig,
    invalid_company_numbers,
    parse_company_numbers,
    uk_companies_house_source,
    validate_credentials as validate_companies_house_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

NO_COMPANY_NUMBERS_ERROR = "Add at least one company number to sync from Companies House."


def _invalid_company_numbers_error(invalid: list[str]) -> str:
    shown = ", ".join(invalid[:5])
    suffix = " and others" if len(invalid) > 5 else ""
    return (
        f"These are not valid Companies House company numbers: {shown}{suffix}. "
        "Company numbers are eight characters, so pad shorter numbers with leading zeros."
    )


@SourceRegistry.register
class UkCompaniesHouseSource(ResumableSource[UkCompaniesHouseSourceConfig, UkCompaniesHouseResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # The Public Data API has no version segment, header or param to pin, so the framework
    # default (unversioned) applies.
    api_docs_url = (
        "https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/reference"
    )

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.UKCOMPANIESHOUSE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Companies House rejected the API key. Check that it is a live Public Data API key.",
            "403 Client Error: Forbidden for url": "This Companies House API key cannot read the Public Data API. Check the application type in the developer hub.",
            NO_COMPANY_NUMBERS_ERROR: NO_COMPANY_NUMBERS_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.uk_companies_house.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: UkCompaniesHouseSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, descriptions=DESCRIPTIONS)

    def validate_credentials(
        self,
        config: UkCompaniesHouseSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        company_numbers = parse_company_numbers(config.company_numbers)
        if not company_numbers:
            return False, NO_COMPANY_NUMBERS_ERROR

        invalid = invalid_company_numbers(company_numbers)
        if invalid:
            return False, _invalid_company_numbers_error(invalid)

        # One profile lookup proves the key works and that the first company number resolves,
        # which is the typo most likely to turn a whole sync into 404s.
        return validate_companies_house_credentials(config.api_key, company_numbers[0])

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[UkCompaniesHouseResumeConfig]:
        return ResumableSourceManager[UkCompaniesHouseResumeConfig](inputs, UkCompaniesHouseResumeConfig)

    def source_for_pipeline(
        self,
        config: UkCompaniesHouseSourceConfig,
        resumable_source_manager: ResumableSourceManager[UkCompaniesHouseResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        endpoint = inputs.schema_name
        if endpoint not in ENDPOINT_SPECS:
            raise ValueError(f"Unknown Companies House endpoint: {endpoint}")

        company_numbers = parse_company_numbers(config.company_numbers)
        if not company_numbers:
            raise ValueError(NO_COMPANY_NUMBERS_ERROR)

        items = uk_companies_house_source(
            api_key=config.api_key,
            endpoint=endpoint,
            company_numbers=company_numbers,
            resumable_source_manager=resumable_source_manager,
            logger=inputs.logger,
        )

        return SourceResponse(
            name=endpoint,
            items=lambda: items,
            primary_keys=ENDPOINT_SPECS[endpoint].primary_key,
            # Companies House documents no ordering for its list endpoints, and rows arrive
            # grouped by the configured company numbers rather than by time.
            sort_mode=None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.UK_COMPANIES_HOUSE,
            category=DataWarehouseSourceCategory.CRM,
            label="Companies House (UK government)",
            caption="""Sync UK company registry data for the companies you care about, keyed by company number.

Get a free API key by registering an application on the [Companies House developer hub](https://developer.company-information.service.gov.uk/), then create a live key for the Public Data API.

Every table is fetched per company number, so start with the companies you want to enrich rather than the whole register. Companies House allows 600 requests every five minutes.""",
            docsUrl="https://posthog.com/docs/cdp/sources/uk-companies-house",
            iconPath="/static/services/uk_companies_house.png",
            keywords=["kyb", "firmographics", "uk company registry"],
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
                    SourceFieldInputConfig(
                        name="company_numbers",
                        label="Company numbers",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="00006400, SC123456",
                        secret=False,
                        caption="One company number per line, or separated by commas. Numbers shorter than eight digits are padded with leading zeros.",
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
