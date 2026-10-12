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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kestra import KestraSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kestra.kestra import (
    KestraResumeState,
    kestra_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kestra.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    EXECUTION_LOOKBACK_SECONDS,
    INCREMENTAL_FIELDS,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KestraSource(ResumableSource[KestraSourceConfig, KestraResumeState]):
    lists_tables_without_credentials = True
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://kestra.io/docs/api-reference/open-source"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KESTRA

    @property
    def connection_host_fields(self) -> list[str]:
        return ["host"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": PERMISSION_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.kestra.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: KestraSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only={"executions"})
        for schema in schemas:
            if schema.name == "executions":
                schema.default_incremental_lookback_seconds = EXECUTION_LOOKBACK_SECONDS
        return schemas

    def validate_credentials(
        self,
        config: KestraSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, team_id, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[KestraResumeState]:
        return ResumableSourceManager(inputs, KestraResumeState)

    def source_for_pipeline(
        self,
        config: KestraSourceConfig,
        resumable_source_manager: ResumableSourceManager[KestraResumeState],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return kestra_source(config, inputs, resumable_source_manager)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.KESTRA,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Kestra",
            iconPath="/static/services/kestra.png",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "For Kestra Cloud or Enterprise, create a token in Settings → API Tokens. "
                "Grant read access to flows, executions, and triggers in your tenant. "
                "For self-hosted Kestra, you can use Basic authentication. "
                "Your instance must be publicly reachable over HTTPS. "
                "Execution syncs read the previous seven days again to update recent runs. "
                "Use a full refresh to update older runs."
            ),
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Instance URL",
                        type=SourceFieldInputConfigType.URL,
                        required=True,
                        secret=False,
                        placeholder="https://kestra.example.com",
                    ),
                    SourceFieldInputConfig(
                        name="tenant",
                        label="Tenant ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        secret=False,
                        placeholder="main",
                        caption="Use main for Open Source, or your Cloud or Enterprise tenant ID.",
                    ),
                    SourceFieldSelectConfig(
                        name="auth_method",
                        label="Authentication",
                        required=True,
                        defaultValue="token",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="API token",
                                value="token",
                                fields=[
                                    SourceFieldInputConfig(
                                        name="api_token",
                                        label="API token",
                                        type=SourceFieldInputConfigType.PASSWORD,
                                        required=False,
                                        secret=True,
                                        placeholder="",
                                    ),
                                ],
                            ),
                            SourceFieldSelectConfigOption(
                                label="Basic authentication",
                                value="basic",
                                fields=[
                                    SourceFieldInputConfig(
                                        name="username",
                                        label="Username",
                                        type=SourceFieldInputConfigType.TEXT,
                                        required=False,
                                        secret=False,
                                        placeholder="user@example.com",
                                    ),
                                    SourceFieldInputConfig(
                                        name="password",
                                        label="Password",
                                        type=SourceFieldInputConfigType.PASSWORD,
                                        required=False,
                                        secret=True,
                                        placeholder="",
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        )
