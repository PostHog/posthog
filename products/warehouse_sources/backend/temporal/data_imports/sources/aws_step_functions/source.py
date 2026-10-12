from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_step_functions.aws_step_functions import (
    AwsStepFunctionsResumeConfig,
    aws_step_functions_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_step_functions.settings import (
    API_VERSION,
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    ERROR_MESSAGES,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsstepfunctions import (
    AwsStepFunctionsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsStepFunctionsSource(ResumableSource[AwsStepFunctionsSourceConfig, AwsStepFunctionsResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = "https://docs.aws.amazon.com/step-functions/latest/apireference/Welcome.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSSTEPFUNCTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {f"AWS Step Functions request failed: {code}": message for code, message in ERROR_MESSAGES.items()}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.aws_step_functions.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AwsStepFunctionsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names, descriptions=ENDPOINT_DESCRIPTIONS)

    def validate_credentials(
        self,
        config: AwsStepFunctionsSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, schema_name, self.resolve_api_version(api_version))

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[AwsStepFunctionsResumeConfig]:
        return ResumableSourceManager(inputs, AwsStepFunctionsResumeConfig)

    def source_for_pipeline(
        self,
        config: AwsStepFunctionsSourceConfig,
        resumable_source_manager: ResumableSourceManager[AwsStepFunctionsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aws_step_functions_source(
            config, inputs.schema_name, self.resolve_api_version(inputs.api_version), resumable_source_manager
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSSTEPFUNCTIONS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="AWS Step Functions",
            caption=(
                "Sync state machines, executions, and execution history from one AWS region. "
                "Grant `states:ListStateMachines`, `states:ListExecutions`, and `states:GetExecutionHistory` for the tables you select. "
                "Executions and history cover Standard workflows only. History excludes input and output payloads. "
                "All tables use full refresh because these APIs have no time filter."
            ),
            iconPath="/static/services/aws_step_functions.png",
            docsUrl="https://posthog.com/docs/cdp/sources/aws-step-functions",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="aws_access_key_id",
                        label="AWS access key ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="AKIA...",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="aws_secret_access_key",
                        label="AWS secret access key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="aws_session_token",
                        label="AWS session token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="Only needed for temporary credentials",
                        secret=True,
                        caption="Temporary credentials expire. Update them before the next scheduled sync.",
                    ),
                    SourceFieldInputConfig(
                        name="region",
                        label="AWS region",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="us-east-1",
                        secret=False,
                    ),
                ],
            ),
        )
