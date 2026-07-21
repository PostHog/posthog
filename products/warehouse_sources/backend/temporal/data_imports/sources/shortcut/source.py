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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ShortcutSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.shortcut import (
    shortcut_source,
    validate_credentials as validate_shortcut_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ShortcutSource(SimpleSource[ShortcutSourceConfig]):
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://developer.shortcut.com/api/rest/v3"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SHORTCUT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SHORTCUT,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Shortcut",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Shortcut API token to sync your Shortcut data into the PostHog Data warehouse.

You can create an API token in your [Shortcut account settings](https://app.shortcut.com/settings/account/api-tokens). The token grants access to the whole workspace it belongs to and becomes invalid if you're removed from that workspace.""",
            iconPath="/static/services/shortcut.png",
            docsUrl="https://posthog.com/docs/cdp/sources/shortcut",
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

    def get_schemas(
        self,
        config: ShortcutSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid or expired Shortcut API token. Please generate a new token and reconnect.",
            "403 Client Error": "Your Shortcut API token does not have access to this workspace. Please check its permissions.",
        }

    def validate_credentials(
        self, config: ShortcutSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_shortcut_credentials(config.api_token)

    def source_for_pipeline(self, config: ShortcutSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return shortcut_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
