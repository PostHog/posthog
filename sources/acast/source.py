from typing import cast

from sources.acast._config import AcastSourceConfig
from sources.acast.acast import (
    acast_source,
    validate_credentials as validate_acast_credentials,
)
from sources.acast.canonical_descriptions import CANONICAL_DESCRIPTIONS
from sources.acast.settings import AUTH_ERROR, ENDPOINTS, PERMISSION_ERROR
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


@SourceRegistry.register
class AcastSource(SimpleSource[AcastSourceConfig]):
    lists_tables_without_credentials = True
    api_docs_url = "https://developers.acast.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ACAST

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ACAST,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Acast",
            iconPath="/static/services/acast.png",
            caption=(
                "Request an API key from Acast Customer Success through the Acast chat box. "
                "API access requires the Pro plan or Creator Network membership. "
                "The key can read shows assigned to its user."
            ),
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
                    )
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {"401 Client Error": AUTH_ERROR, "403 Client Error": PERMISSION_ERROR}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AcastSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: AcastSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_acast_credentials(config.api_key, team_id)

    def source_for_pipeline(self, config: AcastSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return acast_source(config.api_key, inputs.schema_name, inputs.team_id, inputs.job_id)
