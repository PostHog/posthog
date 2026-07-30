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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SurveyMonkeySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.surveymonkey.settings import (
    DATA_CENTER_BASE_URLS,
    DEFAULT_DATA_CENTER,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.surveymonkey.surveymonkey import (
    SurveyMonkeyResumeConfig,
    surveymonkey_source,
    validate_credentials as validate_surveymonkey_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _base_url_for(config: SurveyMonkeySourceConfig) -> str:
    data_center = getattr(config, "data_center", None) or DEFAULT_DATA_CENTER
    return DATA_CENTER_BASE_URLS.get(data_center, DATA_CENTER_BASE_URLS[DEFAULT_DATA_CENTER])


@SourceRegistry.register
class SurveyMonkeySource(ResumableSource[SurveyMonkeySourceConfig, SurveyMonkeyResumeConfig]):
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://api.surveymonkey.com/v3/docs"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SURVEYMONKEY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SURVEY_MONKEY,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="SurveyMonkey",
            caption="""Enter a SurveyMonkey access token to pull your surveys, responses, and collectors into the PostHog Data warehouse.

Create a private app and generate an access token in the [SurveyMonkey developer dashboard](https://developer.surveymonkey.com/apps/).

Make sure to grant the following read scopes:
- `surveys_read`
- `responses_read_detail`
- `collectors_read`
""",
            iconPath="/static/services/surveymonkey.png",
            docsUrl="https://posthog.com/docs/cdp/sources/surveymonkey",
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
                            SourceFieldSelectConfigOption(label="US (api.surveymonkey.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (api.eu.surveymonkey.com)", value="eu"),
                            SourceFieldSelectConfigOption(label="Canada (api.surveymonkey.ca)", value="ca"),
                        ],
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.surveymonkey.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Your SurveyMonkey access token is invalid or expired. Please generate a new token and reconnect.",
            "403 Client Error: Forbidden for url": "Your SurveyMonkey access token is missing required scopes. Please grant `surveys_read`, `responses_read_detail`, and `collectors_read`, then reconnect.",
        }

    def get_schemas(
        self,
        config: SurveyMonkeySourceConfig,
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
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: SurveyMonkeySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_surveymonkey_credentials(config.access_token, _base_url_for(config))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SurveyMonkeyResumeConfig]:
        return ResumableSourceManager[SurveyMonkeyResumeConfig](inputs, SurveyMonkeyResumeConfig)

    def source_for_pipeline(
        self,
        config: SurveyMonkeySourceConfig,
        resumable_source_manager: ResumableSourceManager[SurveyMonkeyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return surveymonkey_source(
            access_token=config.access_token,
            base_url=_base_url_for(config),
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
