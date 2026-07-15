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
from products.warehouse_sources.backend.temporal.data_imports.sources.airtable.airtable import (
    airtable_source,
    validate_credentials as validate_airtable_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.airtable.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AirtableSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AirtableSource(SimpleSource[AirtableSourceConfig]):
    supported_versions = ("v0",)
    default_version = "v0"
    api_docs_url = "https://airtable.com/developers/web/api/changelog"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AIRTABLE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.airtable.com": "Airtable authentication failed. Please check your personal access token.",
            "403 Client Error: Forbidden for url: https://api.airtable.com": "Airtable denied access. Please check that your personal access token has the required scopes and base access.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AIRTABLE,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Airtable",
            caption="""Enter your Airtable personal access token to pull your Airtable bases into the PostHog Data warehouse.

Create a personal access token at [airtable.com/create/tokens](https://airtable.com/create/tokens) with the `data.records:read` and `schema.bases:read` scopes, and grant it access to the bases you want to sync. Records are synced from every table of every base the token can access.""",
            iconPath="/static/services/airtable.png",
            docsUrl="https://posthog.com/docs/cdp/sources/airtable",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="personal_access_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="pat...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: AirtableSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: AirtableSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_airtable_credentials(config.personal_access_token):
            return True, None

        return False, "Invalid Airtable personal access token"

    def source_for_pipeline(self, config: AirtableSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return airtable_source(
            personal_access_token=config.personal_access_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
