from typing import cast

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.facade.codebase_detection import detect
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAUTH2_PERMANENT_ERROR_MARKER,
    OAuth2AuthRequestError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
    schema_for_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sageintacct import (
    SageIntacctSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sage_intacct.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sage_intacct.sage_intacct import (
    SageIntacctResumeConfig,
    probe_credentials,
    sage_intacct_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sage_intacct.settings import ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SageIntacctSource(ResumableSource[SageIntacctSourceConfig, SageIntacctResumeConfig]):
    codebase_detection = detect(
        env=("^(SAGE_INTACCT|SAGEINTACCT)_", "^INTACCT_"),
        pypi=("sageintacctsdk",),
        composer=("intacct/intacct-sdk-php",),
    )

    lists_tables_without_credentials = True
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://developer.sage.com/intacct/apis/intacct/1/intacct-openapi"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SAGEINTACCT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SAGEINTACCT,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Sage Intacct",
            docsUrl="https://posthog.com/docs/cdp/sources/sage-intacct",
            iconPath="/static/services/sage_intacct.png",
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
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
                        name="username",
                        label="Web services username",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="UserId@CompanyId",
                        caption="Enter UserId@CompanyId or UserId@CompanyId|entityId for access to one entity.",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SageIntacctSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            OAUTH2_PERMANENT_ERROR_MARKER: "Check your Sage Intacct client credentials and web services username.",
            "401 Client Error": "Reconnect Sage Intacct with valid credentials.",
            "403 Client Error": "Give the Sage Intacct user read access to the selected tables.",
        }

    def validate_credentials(
        self,
        config: SageIntacctSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        object_name = schema_for_resource(ENDPOINTS, schema_name or "Customers")
        try:
            probe_credentials(config, object_name)
        except OAuth2AuthRequestError as error:
            if not error.is_permanent:
                raise
            return False, "Check your Sage Intacct client credentials and web services username."
        except HTTPError as error:
            if error.response is None or error.response.status_code not in (400, 401, 403):
                raise
            return False, "Check your Sage Intacct credentials and read access to this table."
        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SageIntacctResumeConfig]:
        return ResumableSourceManager(inputs, SageIntacctResumeConfig)

    def source_for_pipeline(
        self,
        config: SageIntacctSourceConfig,
        resumable_source_manager: ResumableSourceManager[SageIntacctResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        object_name = schema_for_resource(ENDPOINTS, inputs.schema_name)
        if inputs.should_use_incremental_field:
            raise ValueError("Sage Intacct tables require full refresh")
        return SourceResponse(
            name=inputs.schema_name,
            items=lambda: sage_intacct_rows(config, object_name, resumable_source_manager),
            primary_keys=["key"],
        )
