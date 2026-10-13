from typing import Optional, cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.skio import SkioSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.skio.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.skio.skio import (
    FIELD_NOT_FOUND_ERROR,
    INVALID_TOKEN_ERROR,
    SkioResumeConfig,
    skio_source,
    validate_credentials as validate_skio_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SkioSource(ResumableSource[SkioSourceConfig, SkioResumeConfig]):
    # Skio's GraphQL API is served from Hasura's fixed /v1/graphql path and exposes no
    # vendor-chosen version token, so the unversioned framework default applies.
    api_docs_url = "https://code.skio.com"

    lists_tables_without_credentials = True  # static endpoint catalog, so safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SKIO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SKIO,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Skio",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Skio API token to pull your Skio subscription data into the PostHog Data warehouse.

You can generate an API token in your Skio dashboard: click **API** in the left navigation bar, set a name, and generate the token.
""",
            iconPath="/static/services/skio.png",
            docsUrl="https://posthog.com/docs/cdp/sources/skio",
            keywords=["subscriptions", "shopify"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.skio.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Skio's Hasura backend answers these with HTTP 200, so they surface as SkioAPIError
        # messages rather than HTTP status errors; both are verbatim live-API strings.
        return {
            INVALID_TOKEN_ERROR: "Your Skio API token is invalid or has been revoked. Generate a new token under API in your Skio dashboard, then reconnect.",
            FIELD_NOT_FOUND_ERROR: "Your Skio API token does not have access to this table. Generate a new token under API in your Skio dashboard, then reconnect.",
        }

    def get_schemas(
        self,
        config: SkioSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint_config.name,
                supports_incremental=True,
                # Every collection is mutable (orders cancel, subscriptions change status), so only
                # merge keeps one row per id; append would materialize each update as a duplicate.
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS[endpoint_config.name],
                description=endpoint_config.description,
            )
            for endpoint_config in ENDPOINTS.values()
        ]
        if names is not None:
            names_set = set(names)
            schemas = [schema for schema in schemas if schema.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: SkioSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_skio_credentials(config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SkioResumeConfig]:
        return ResumableSourceManager[SkioResumeConfig](inputs, SkioResumeConfig)

    def source_for_pipeline(
        self,
        config: SkioSourceConfig,
        resumable_source_manager: ResumableSourceManager[SkioResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in ENDPOINTS:
            raise ValueError(f"Skio schema {inputs.schema_name} does not exist")

        return skio_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
