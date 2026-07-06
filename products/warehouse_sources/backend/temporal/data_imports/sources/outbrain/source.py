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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OutbrainSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.outbrain.outbrain import (
    OutbrainResumeConfig,
    outbrain_source,
    validate_credentials as validate_outbrain_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.outbrain.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OutbrainSource(ResumableSource[OutbrainSourceConfig, OutbrainResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OUTBRAIN

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.outbrain.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.outbrain.com/amplify/v0.1/login": "Outbrain authentication failed. Please check your username and password.",
            "403 Client Error: Forbidden for url: https://api.outbrain.com": "Outbrain denied access. Please check that your account has Amplify API access (requested via your account manager).",
            # A 400 on a well-formed, static request is deterministic — retrying can never succeed.
            # It surfaces when one of the marketers returned by /marketers can't be queried through
            # the Amplify API, so match the stable prefix, not the volatile marketer id and query.
            "400 Client Error: Bad Request for url: https://api.outbrain.com": "Outbrain rejected the request (400 Bad Request). One of the marketers on your account may not be accessible via the Amplify API. Please confirm your account's Amplify API access with your Outbrain account manager.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OUTBRAIN,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Outbrain",
            caption="""Connect your Outbrain Amplify account to pull your advertising data into the PostHog Data warehouse.

Uses your Outbrain login credentials. Amplify API access must be enabled for your account — request it through your Outbrain account manager if API calls are rejected.""",
            iconPath="/static/services/outbrain.png",
            docsUrl="https://posthog.com/docs/cdp/sources/outbrain",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="username",
                        label="Username",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="user@company.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="password",
                        label="Password",
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
        config: OutbrainSourceConfig,
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
        self, config: OutbrainSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_outbrain_credentials(config.username, config.password):
            return True, None

        return False, "Invalid Outbrain credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OutbrainResumeConfig]:
        return ResumableSourceManager[OutbrainResumeConfig](inputs, OutbrainResumeConfig)

    def source_for_pipeline(
        self,
        config: OutbrainSourceConfig,
        resumable_source_manager: ResumableSourceManager[OutbrainResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return outbrain_source(
            username=config.username,
            password=config.password,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
