from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.singlestore import (
    SinglestoreSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.singlestore.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.singlestore.singlestore import (
    singlestore_source,
    validate_credentials as validate_singlestore_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SinglestoreSource(SimpleSource[SinglestoreSourceConfig]):
    # get_schemas below just iterates the static ENDPOINTS catalog — no network call.
    lists_tables_without_credentials = True
    api_docs_url = "https://docs.singlestore.com/cloud/reference/management-api/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SINGLESTORE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your SingleStore API key is invalid or has been revoked. Generate a new "
            "organization API key in the Cloud Portal and reconnect.",
            "403 Client Error": "Your SingleStore API key does not have permission to access this resource.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.singlestore.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SinglestoreSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: SinglestoreSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_singlestore_credentials(config.api_key)

    def source_for_pipeline(self, config: SinglestoreSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return singlestore_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SINGLESTORE,
            category=DataWarehouseSourceCategory.DATABASES,
            keywords=["database", "usage", "billing"],
            label="SingleStore, Inc.",
            iconPath="/static/services/singlestore.png",
            docsUrl="https://posthog.com/docs/cdp/sources/singlestore",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                        caption="Generate an organization API key from the SingleStore Cloud Portal "
                        "(Org name -> API Keys).",
                    ),
                ],
            ),
        )
