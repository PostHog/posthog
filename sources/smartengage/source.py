from typing import Optional, cast

from sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    ReleaseStatus,
    SimpleSource,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
)
from sources.smartengage._config import SmartEngageSourceConfig
from sources.smartengage.settings import ENDPOINTS, INCREMENTAL_FIELDS
from sources.smartengage.smartengage import (
    smartengage_source,
    validate_credentials as validate_smartengage_credentials,
)


@SourceRegistry.register
class SmartEngageSource(SimpleSource[SmartEngageSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://smartengage.com/docs/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SMARTENGAGE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid SmartEngage API key. Please update your key and reconnect.",
            "403 Client Error": "Your SmartEngage API key does not have the required permissions. Please update the key and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from sources.smartengage.canonical_descriptions import CANONICAL_DESCRIPTIONS  # noqa: PLC0415

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SmartEngageSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: SmartEngageSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_smartengage_credentials(config.api_key)

    def source_for_pipeline(self, config: SmartEngageSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return smartengage_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SMARTENGAGE,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="SmartEngage",
            caption="""Enter your SmartEngage API key to sync avatars, tags, custom fields, and sequences.

You can find your API key in your SmartEngage account settings.
""",
            docsUrl="https://posthog.com/docs/cdp/sources/smartengage",
            iconPath="/static/services/smartengage.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="se_...",
                        secret=True,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
