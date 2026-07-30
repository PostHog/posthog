from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mercury import (
    MercurySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mercury.mercury import (
    MercuryResumeConfig,
    check_credentials,
    mercury_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mercury.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    MERCURY_ENDPOINTS,
    TRANSACTIONS_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MercurySource(ResumableSource[MercurySourceConfig, MercuryResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.mercury.com/reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MERCURY

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.mercury.com": "Your Mercury API token is invalid or has been revoked. Please generate a new token in Mercury under Settings > API tokens and reconnect.",
            "403 Client Error: Forbidden for url: https://api.mercury.com": "Your Mercury API token does not have permission to read this data. Please use a token with Read Only access or grant the missing scope.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.mercury.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: MercurySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)
        for schema in schemas:
            if schema.name == "Transactions":
                # Pending transactions mutate (status, postedAt) after creation; re-read a
                # trailing window so those updates get merged despite the createdAt cursor.
                schema.default_incremental_lookback_seconds = TRANSACTIONS_LOOKBACK_SECONDS
        return schemas

    def validate_credentials(
        self,
        config: MercurySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            status = check_credentials(config.api_key)
        except Exception as e:
            return False, str(e)

        if status == 200:
            return True, None
        if status == 401:
            return False, "Invalid Mercury API token. Generate a token in Mercury under Settings > API tokens."
        if status == 403:
            # A custom-scoped token can be valid without access to /accounts. Accept it at
            # source-create; per-endpoint scope problems surface at sync time.
            if schema_name is None:
                return True, None
            return False, f"Your Mercury API token does not have permission to read {schema_name}."
        return False, f"Mercury API returned an unexpected status ({status}). Please try again."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MercuryResumeConfig]:
        return ResumableSourceManager[MercuryResumeConfig](inputs, MercuryResumeConfig)

    def source_for_pipeline(
        self,
        config: MercurySourceConfig,
        resumable_source_manager: ResumableSourceManager[MercuryResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        endpoint_config = MERCURY_ENDPOINTS[inputs.schema_name]
        resource = mercury_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

        if endpoint_config.partition_key is not None:
            return SourceResponse(
                name=resource.name,
                items=lambda: resource,
                primary_keys=[endpoint_config.primary_key],
                column_hints=resource.column_hints,
                partition_count=1,
                partition_size=1,
                partition_mode="datetime",
                partition_format="month",
                partition_keys=[endpoint_config.partition_key],
                sort_mode="asc",
            )

        return SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=[endpoint_config.primary_key],
            column_hints=resource.column_hints,
            sort_mode="asc",
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MERCURY,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Mercury",
            caption="Sync your Mercury business banking data, including accounts, transactions, cards, and invoices.\n\nCreate an API token with Read Only access in Mercury under [Settings > API tokens](https://app.mercury.com/settings/tokens). Read Only tokens do not require an IP allowlist.",
            docsUrl="https://posthog.com/docs/cdp/sources/mercury",
            iconPath="/static/services/mercury.png",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["banking", "bank"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
