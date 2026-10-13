from typing import cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.testdino import (
    TestDinoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.testdino.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.testdino.settings import (
    API_VERSION,
    CASE_LIMIT_ERROR,
    ENDPOINTS,
    HTTP_ERRORS,
    INVALID_PROJECT,
    INVALID_TOKEN,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.testdino.testdino import (
    TestDinoResumeConfig,
    testdino_source,
    validate_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TestDinoSource(ResumableSource[TestDinoSourceConfig, TestDinoResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = "https://docs.testdino.com/api-reference/conventions"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TESTDINO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TESTDINO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="TestDino",
            keywords=["playwright"],
            iconPath="/static/services/testdino.png",
            caption=(
                "Create a personal access token in TestDino under User Settings > Personal Access Tokens. "
                "Give the token access to your project. "
                "Manual case imports require fewer than 1,000 cases in the project."
            ),
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="personal_access_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="td_pat_...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="project_id",
                        label="Project ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="project_abc123",
                        secret=False,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            **{f"{status} Client Error": message for status, message in HTTP_ERRORS.items()},
            "UNAUTHORIZED": INVALID_TOKEN,
            "TOKEN_EXPIRED": INVALID_TOKEN,
            "TOKEN_REVOKED": INVALID_TOKEN,
            INVALID_PROJECT: INVALID_PROJECT,
            CASE_LIMIT_ERROR: CASE_LIMIT_ERROR,
            "TestDino did not return pagination.hasNext.": "TestDino returned unexpected pagination. Contact PostHog support.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: TestDinoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: TestDinoSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TestDinoResumeConfig]:
        return ResumableSourceManager(inputs, TestDinoResumeConfig)

    def source_for_pipeline(
        self,
        config: TestDinoSourceConfig,
        resumable_source_manager: ResumableSourceManager[TestDinoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return testdino_source(config, inputs, resumable_source_manager)
