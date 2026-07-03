from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.attio.attio import (
    attio_source,
    validate_credentials as validate_attio_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.attio.settings import ATTIO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AttioSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AttioSource(SimpleSource[AttioSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ATTIO

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.attio.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.attio.com": "Your Attio API key is invalid or expired. Please generate a new key and reconnect.",
            "403 Client Error: Forbidden for url: https://api.attio.com": "Your Attio API key does not have the required scopes. Please check the API key permissions and try again.",
            # Attio can return non-retryable 400 responses from object query endpoints under /v2/objects/.
            # The exact cause can vary by object and workspace configuration (e.g. an optional standard object
            # like users/workspaces/deals not being enabled), so avoid implying the object is missing when surfacing
            # the error to users. Our request body is deterministic, so retrying will not recover.
            "400 Client Error: Bad Request for url: https://api.attio.com/v2/objects/": "Attio rejected the request for this object query. Please verify the schema is available in Attio and that the request is valid, then try again.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ATTIO,
            category=DataWarehouseSourceCategory.CRM,
            caption="""Enter your Attio API key to automatically pull your Attio data into the PostHog Data warehouse.

You can generate an API key in your Attio workspace settings. Check out [this guide](https://attio.com/help/apps/other-apps/generating-an-api-key) for more details.

**Required API scopes:**
- `object_configuration:read` - To read object configurations
- `record_permission:read` - To read record permissions
- `record:read` - To read records (companies, people, deals, users, workspaces)
- `list_entry:read` - To read list entries
- `note:read` - To read notes
- `task:read` - To read tasks
- `user_management:read` - To read workspace members
""",
            iconPath="/static/services/attio.png",
            docsUrl="https://posthog.com/docs/cdp/sources/attio",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Enter your Attio API key",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: AttioSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Attio API doesn't support updatedAt filtering, so only full refresh is supported
        schemas = [
            SourceSchema(
                name=endpoint_config.name,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint_config in ATTIO_ENDPOINTS.values()
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: AttioSourceConfig, team_id: int, schema_name: str | None = None
    ) -> tuple[bool, str | None]:
        return validate_attio_credentials(config.api_key)

    def source_for_pipeline(self, config: AttioSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return attio_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
