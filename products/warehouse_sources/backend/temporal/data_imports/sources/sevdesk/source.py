import re
from typing import cast

from requests.exceptions import HTTPError

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sevdesk import (
    SevdeskSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sevdesk.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sevdesk.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sevdesk.sevdesk import (
    SevdeskResumeConfig,
    sevdesk_source,
    validate_credentials as validate_sevdesk_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SevdeskSource(ResumableSource[SevdeskSourceConfig, SevdeskResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://api.sevdesk.de/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SEVDESK

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {"401 Client Error": AUTH_ERROR, "403 Client Error": PERMISSION_ERROR}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SevdeskSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: SevdeskSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if re.fullmatch(r"[0-9a-fA-F]{32}", config.api_token) is None:
            return False, "Enter the 32-character hexadecimal API token from Settings > User > API in sevDesk."
        if schema_name is not None and schema_name not in ENDPOINTS:
            return False, "Unknown sevDesk table. Select a table from the source schema list."
        try:
            validate_sevdesk_credentials(
                config.api_token, schema_name or "Contact", self.resolve_api_version(api_version)
            )
        except HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status == 401:
                return False, AUTH_ERROR
            if status == 403:
                return (True, None) if schema_name is None else (False, PERMISSION_ERROR)
            raise
        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SevdeskResumeConfig]:
        return ResumableSourceManager(inputs, SevdeskResumeConfig)

    def source_for_pipeline(
        self,
        config: SevdeskSourceConfig,
        resumable_source_manager: ResumableSourceManager[SevdeskResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return sevdesk_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SEVDESK,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="sevDesk (sevDesk GmbH)",
            docsUrl="https://posthog.com/docs/cdp/sources/sevdesk",
            iconPath="/static/services/sevdesk.png",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="Import accounting data with an administrator's API token from Settings > User > API in sevDesk.",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        placeholder="",
                        required=True,
                        secret=True,
                    )
                ],
            ),
        )
