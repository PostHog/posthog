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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.onehundredms import (
    OneHundredMsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onehundredms.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onehundredms.onehundredms import (
    OneHundredMsResumeConfig,
    onehundredms_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onehundredms.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PERMISSION_ERROR,
    SESSION_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OneHundredMsSource(ResumableSource[OneHundredMsSourceConfig, OneHundredMsResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://www.100ms.live/docs/server-side/v2/release-notes/release-notes"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ONEHUNDREDMS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {"401 Client Error": AUTH_ERROR, "403 Client Error": PERMISSION_ERROR}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: OneHundredMsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only={"sessions"})
        for schema in schemas:
            if schema.name == "sessions":
                schema.default_incremental_lookback_seconds = SESSION_LOOKBACK_SECONDS
        return schemas

    def validate_credentials(
        self,
        config: OneHundredMsSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            validate_credentials(config, self.resolve_api_version(api_version), schema_name)
        except HTTPError as error:
            if error.response is not None:
                if error.response.status_code == 401:
                    return False, AUTH_ERROR
                if error.response.status_code == 403:
                    return False, PERMISSION_ERROR
            raise
        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OneHundredMsResumeConfig]:
        return ResumableSourceManager(inputs, OneHundredMsResumeConfig)

    def source_for_pipeline(
        self,
        config: OneHundredMsSourceConfig,
        resumable_source_manager: ResumableSourceManager[OneHundredMsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return onehundredms_source(
            config, inputs, resumable_source_manager, self.resolve_api_version(inputs.api_version)
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ONEHUNDREDMS,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="100ms",
            caption=(
                "Find your app access key and app secret in the Developer section of your "
                "[100ms dashboard](https://dashboard.100ms.live/). Only completed sessions are imported."
            ),
            iconPath="/static/services/onehundredms.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="app_access_key",
                        label="App access key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="app_secret",
                        label="App secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
