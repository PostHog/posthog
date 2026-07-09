from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SurveySparrowSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.surveysparrow.settings import (
    DATA_CENTER_BASE_URLS,
    DEFAULT_DATA_CENTER,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SURVEYSPARROW_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.surveysparrow.surveysparrow import (
    SurveySparrowResumeConfig,
    surveysparrow_source,
    validate_credentials as validate_surveysparrow_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _base_url_for(config: SurveySparrowSourceConfig) -> str:
    data_center = getattr(config, "data_center", None) or DEFAULT_DATA_CENTER
    return DATA_CENTER_BASE_URLS.get(data_center, DATA_CENTER_BASE_URLS[DEFAULT_DATA_CENTER])


@SourceRegistry.register
class SurveySparrowSource(ResumableSource[SurveySparrowSourceConfig, SurveySparrowResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SURVEYSPARROW

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SURVEY_SPARROW,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="SurveySparrow",
            caption="""Enter a SurveySparrow access token to pull your surveys, responses, questions, and contacts into the PostHog Data warehouse.

Create a private app and generate an access token under **Settings → Apps & Integrations** in [SurveySparrow](https://surveysparrow.com). The token is displayed only once, so copy it when it's created.

Pick the data center your SurveySparrow account is hosted in — tokens are only valid against their own region's API host.
""",
            iconPath="/static/services/surveysparrow.png",
            docsUrl="https://posthog.com/docs/cdp/sources/surveysparrow",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="data_center",
                        label="Data center",
                        required=True,
                        defaultValue=DEFAULT_DATA_CENTER,
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.surveysparrow.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (eu-api.surveysparrow.com)", value="eu"),
                            SourceFieldSelectConfigOption(label="Asia-Pacific (ap-api.surveysparrow.com)", value="ap"),
                            SourceFieldSelectConfigOption(label="Middle East (me-api.surveysparrow.com)", value="me"),
                            SourceFieldSelectConfigOption(label="UK (eu-ln-api.surveysparrow.com)", value="uk"),
                            SourceFieldSelectConfigOption(label="Sydney (ap-sy-app.surveysparrow.com)", value="ap-sy"),
                            SourceFieldSelectConfigOption(label="Canada (ca-api.surveysparrow.com)", value="ca"),
                        ],
                    ),
                ],
            ),
            unreleasedSource=True,
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.surveysparrow.canonical_descriptions import (  # noqa: PLC0415 — keeps the descriptions dict off the import path
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Your SurveySparrow access token is invalid or has been revoked. Generate a new token under Settings → Apps & Integrations and check the data center matches your account, then reconnect.",
            "403 Client Error: Forbidden for url": "Your SurveySparrow access token is missing the required scopes. Grant read access for the resources you want to sync, then reconnect.",
        }

    def get_schemas(
        self,
        config: SurveySparrowSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0,
                supports_append=len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: SurveySparrowSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The access token is account-wide, so a single probe validates access for every schema.
        return validate_surveysparrow_credentials(config.access_token, _base_url_for(config))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SurveySparrowResumeConfig]:
        return ResumableSourceManager[SurveySparrowResumeConfig](inputs, SurveySparrowResumeConfig)

    def source_for_pipeline(
        self,
        config: SurveySparrowSourceConfig,
        resumable_source_manager: ResumableSourceManager[SurveySparrowResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in SURVEYSPARROW_ENDPOINTS:
            raise ValueError(f"Unknown SurveySparrow schema '{inputs.schema_name}'")

        return surveysparrow_source(
            access_token=config.access_token,
            base_url=_base_url_for(config),
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
