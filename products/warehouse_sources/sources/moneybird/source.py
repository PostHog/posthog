import re
from typing import Optional, cast

from requests.exceptions import HTTPError

from products.warehouse_sources.sources.moneybird._config import MoneybirdSourceConfig
from products.warehouse_sources.sources.moneybird.moneybird import (
    MoneybirdResumeConfig,
    list_administration_ids,
    moneybird_source,
)
from products.warehouse_sources.sources.moneybird.settings import API_VERSION, ENDPOINTS, INCREMENTAL_FIELDS
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

# The administration id goes into the request path, so it must be the bare number.
_ADMINISTRATION_ID_RE = re.compile(r"^\d+$")

_INVALID_TOKEN_MESSAGE = (
    "Moneybird rejected your API token. Create a new personal API token in Moneybird, then reconnect the source."
)


@SourceRegistry.register
class MoneybirdSource(ResumableSource[MoneybirdSourceConfig, MoneybirdResumeConfig]):
    codebase_detection = detect(
        env=("^MONEYBIRD_",),
        npm=("@print-one/moneybird-js", "moneybird"),
        pypi=("moneybird",),
        composer=("picqer/moneybird-php-client",),
        rubygems=("moneybird",),
    )

    lists_tables_without_credentials = True
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = "https://developer.moneybird.com/changelog"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MONEYBIRD

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://moneybird.com": _INVALID_TOKEN_MESSAGE,
            "402 Client Error": "Your Moneybird account has reached a limit of its subscription. Check your plan in Moneybird, then sync again.",
            "403 Client Error: Forbidden for url: https://moneybird.com": "Moneybird refused access to this table. Give your API token the scope this table needs, then reconnect the source.",
            "404 Client Error: Not Found for url: https://moneybird.com/api/v2/": "Moneybird can't find this administration. Check the administration ID, then reconnect the source.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.moneybird.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: MoneybirdSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: MoneybirdSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        administration_id = config.administration_id.strip()
        if not _ADMINISTRATION_ID_RE.match(administration_id):
            return (
                False,
                "Enter the administration ID as a number. It is the number after moneybird.com/ in the address bar.",
            )

        try:
            administration_ids = list_administration_ids(config.api_token)
        except HTTPError as error:
            if error.response is not None and error.response.status_code == 401:
                return False, _INVALID_TOKEN_MESSAGE
            # Moneybird answers 403 when it blocks API requests from an IP address after too many requests.
            if error.response is not None and error.response.status_code == 403:
                return False, "Moneybird refused the request. Wait a few minutes, then try again."
            raise

        if administration_id not in administration_ids:
            return (
                False,
                "Your API token can't access this administration. Check the administration ID, or create the token as a user of that administration.",
            )
        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MoneybirdResumeConfig]:
        return ResumableSourceManager[MoneybirdResumeConfig](inputs, MoneybirdResumeConfig)

    def source_for_pipeline(
        self,
        config: MoneybirdSourceConfig,
        resumable_source_manager: ResumableSourceManager[MoneybirdResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return moneybird_source(
            api_token=config.api_token,
            administration_id=config.administration_id.strip(),
            inputs=inputs,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MONEYBIRD,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Moneybird",
            caption=(
                "Import your contacts, invoices, documents and bookkeeping data from Moneybird. "
                "Create a personal API token at [moneybird.com/user/applications/new](https://moneybird.com/user/applications/new). "
                "Select the scopes of the tables you want to sync: `sales_invoices`, `documents`, `estimates`, "
                "`bank`, `time_entries` and `settings`."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/moneybird",
            iconPath="/static/warehouse-sources/moneybird/icon.png",
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="administration_id",
                        label="Administration ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="123456789012345678",
                        secret=False,
                        caption="The number after moneybird.com/ in the address bar when you open the administration.",
                    ),
                ],
            ),
        )
