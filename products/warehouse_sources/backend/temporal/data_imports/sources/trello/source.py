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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TrelloSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.trello.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trello.trello import (
    TrelloResumeConfig,
    trello_source,
    validate_credentials as validate_trello_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TrelloSource(ResumableSource[TrelloSourceConfig, TrelloResumeConfig]):
    supported_versions = ("1",)
    default_version = "1"
    api_docs_url = "https://developer.atlassian.com/cloud/trello/rest/"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TRELLO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TRELLO,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Trello",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Trello API key and token to sync your boards, cards, lists and more into the PostHog Data warehouse.

Get your API key from [trello.com/power-ups/admin](https://trello.com/power-ups/admin) and generate a token with **read** access for your account.""",
            iconPath="/static/services/trello.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Your Trello API key",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Your Trello API token",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.trello.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Trello API key or token. Please check your credentials and reconnect.",
            "403 Client Error": "Your Trello token does not have the required permissions. Please grant read access and reconnect.",
            "invalid key": "Invalid Trello API key. Please check your credentials and reconnect.",
            "invalid token": "Invalid or expired Trello token. Please generate a new token and reconnect.",
        }

    def get_schemas(
        self,
        config: TrelloSourceConfig,
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
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: TrelloSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_trello_credentials(config.api_key, config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TrelloResumeConfig]:
        return ResumableSourceManager[TrelloResumeConfig](inputs, TrelloResumeConfig)

    def source_for_pipeline(
        self,
        config: TrelloSourceConfig,
        resumable_source_manager: ResumableSourceManager[TrelloResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return trello_source(
            api_key=config.api_key,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
