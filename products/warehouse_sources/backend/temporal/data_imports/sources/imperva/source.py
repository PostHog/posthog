from typing import cast

from requests import HTTPError

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.imperva import (
    ImpervaSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.imperva.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.imperva.imperva import (
    ImpervaAPIError,
    ImpervaResumeConfig,
    imperva_source,
    make_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.imperva.settings import (
    API_DOCS_URL,
    AUTH_ERROR,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PERMISSION_ERROR,
    PLAN_ERROR,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ImpervaSource(ResumableSource[ImpervaSourceConfig, ImpervaResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.IMPERVA

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": PERMISSION_ERROR,
            AUTH_ERROR: AUTH_ERROR,
            PERMISSION_ERROR: PERMISSION_ERROR,
            PLAN_ERROR: PLAN_ERROR,
            "Imperva returned API error 2.": "Imperva rejected the request. Check your account ID and sync settings.",
            "Imperva returned API error 13001.": "Imperva rejected the time range. Check your sync settings.",
            "Imperva returned API error 13002.": "Imperva rejected the time interval. Contact PostHog support.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ImpervaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=INCREMENTAL_FIELDS)

    def validate_credentials(
        self,
        config: ImpervaSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not config.account_id.isascii() or not config.account_id.isdigit():
            return False, "Enter the numeric account ID from your Imperva account."
        if schema_name is not None and schema_name not in ENDPOINTS:
            return False, f"Unknown Imperva table: {schema_name}"
        try:
            list(
                make_resource(
                    config,
                    schema_name or "sites",
                    api_version=self.resolve_api_version(api_version),
                    team_id=team_id,
                    job_id="credential-validation",
                    probe=True,
                )
            )
        except ImpervaAPIError as error:
            if error.code == 9415 and schema_name is None:
                return True, None
            return False, str(error)
        except HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status == 401:
                return False, AUTH_ERROR
            if status == 403:
                return False, PERMISSION_ERROR
            raise
        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ImpervaResumeConfig]:
        return ResumableSourceManager(inputs, ImpervaResumeConfig)

    def source_for_pipeline(
        self,
        config: ImpervaSourceConfig,
        resumable_source_manager: ResumableSourceManager[ImpervaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return imperva_source(config, inputs, resumable_source_manager, self.resolve_api_version(inputs.api_version))

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.IMPERVA,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Imperva (Thales) Cloud Application Security",
            iconPath="/static/services/imperva.png",
            docsUrl=API_DOCS_URL,
            caption=(
                "In the Imperva Cloud Security Console, open Account > My Profile > API keys. "
                "Click Add API Key. "
                "Enter its API ID, API key, and your account ID. Grant read access to sites and statistics. "
                "Statistics contain daily account totals. Each sync reads up to 90 days of available data."
            ),
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_id",
                        label="API ID",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
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
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="12345",
                        secret=False,
                    ),
                ],
            ),
        )
