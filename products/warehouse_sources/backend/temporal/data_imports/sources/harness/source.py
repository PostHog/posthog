from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.harness import (
    HarnessSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.harness.harness import (
    HarnessResumeConfig,
    harness_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.harness.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HarnessSource(ResumableSource[HarnessSourceConfig, HarnessResumeConfig]):
    lists_tables_without_credentials = True
    api_docs_url = "https://apidocs.harness.io/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HARNESS

    @property
    def connection_host_fields(self) -> list[str]:
        return ["region"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {"401 Client Error": AUTH_ERROR, "403 Client Error": PERMISSION_ERROR}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.harness.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: HarnessSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: HarnessSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HarnessResumeConfig]:
        return ResumableSourceManager(inputs, HarnessResumeConfig)

    def source_for_pipeline(
        self,
        config: HarnessSourceConfig,
        resumable_source_manager: ResumableSourceManager[HarnessResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return harness_source(config, inputs.schema_name, inputs.team_id, inputs.job_id, resumable_source_manager)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.HARNESS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Harness",
            iconPath="/static/services/harness.png",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "In Harness, open **My Profile > My API Keys** to create an API key and token. "
                "Paste the token below. Give it view permission for pipelines, executions, services, and environments in your project. "
                "Each connection imports one project. All tables use full refresh."
            ),
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key token",
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
                        placeholder="Your Harness account ID",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="organization_id",
                        label="Organization ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="default",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="project_id",
                        label="Project ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="Your Harness project ID",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        caption="Select the host shown in your Harness account URL.",
                        options=[
                            SourceFieldSelectConfigOption(label="US (app.harness.io)", value="us"),
                            SourceFieldSelectConfigOption(label="US (app3.harness.io)", value="us3"),
                            SourceFieldSelectConfigOption(label="US (accounts.harness.io)", value="us_accounts"),
                            SourceFieldSelectConfigOption(label="EU (accounts.eu.harness.io)", value="eu"),
                        ],
                    ),
                ],
            ),
        )
