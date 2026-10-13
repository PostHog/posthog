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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.expo.expo import (
    ExpoResumeConfig,
    expo_source,
    validate_credentials as validate_expo_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.expo.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.expo import ExpoSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ExpoSource(ResumableSource[ExpoSourceConfig, ExpoResumeConfig]):
    api_docs_url = "https://docs.expo.dev/accounts/programmatic-access/"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EXPO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.expo.dev": "Expo rejected this access token. Create a new one at expo.dev under Access tokens and reconnect the source.",
            "Expo API error: Entity not authorized": "This access token cannot read the configured project. Check the project ID and the token's account.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.EXPO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Expo (EAS)",
            caption="""Enter an Expo access token and a project ID to sync your EAS builds and store submissions into the PostHog Data warehouse, including build duration, queue time, and failure reasons.

Create a personal access token at [expo.dev under Access tokens](https://expo.dev/settings/access-tokens), or use a robot user's token for an account-owned integration.

Find the project ID by running `eas project:info`, or in the project's page on expo.dev. One source syncs one project, so add a source per project you want to track.""",
            iconPath="/static/services/expo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/expo",
            keywords=["eas", "react native", "mobile builds"],
            releaseStatus=ReleaseStatus.ALPHA,
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
                        caption="A personal or robot access token, created at expo.dev under Access tokens.",
                    ),
                    SourceFieldInputConfig(
                        name="project_id",
                        label="Project ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="12345678-1234-1234-1234-123456789012",
                        secret=False,
                        caption="Run `eas project:info` to see this, or copy it from the project page on expo.dev.",
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.expo.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ExpoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: ExpoSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_expo_credentials(config.access_token, config.project_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ExpoResumeConfig]:
        return ResumableSourceManager[ExpoResumeConfig](inputs, ExpoResumeConfig)

    def source_for_pipeline(
        self,
        config: ExpoSourceConfig,
        resumable_source_manager: ResumableSourceManager[ExpoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in ENDPOINTS:
            raise ValueError(f"Unknown Expo endpoint: {inputs.schema_name}")

        return expo_source(
            access_token=config.access_token,
            project_id=config.project_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
