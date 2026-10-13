from typing import cast

from requests import HTTPError

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.microsoftdefendercloudapps import (
    MicrosoftDefenderCloudAppsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_defender_cloud_apps.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_defender_cloud_apps.microsoft_defender_cloud_apps import (
    DefenderClient,
    DefenderResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_defender_cloud_apps.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MicrosoftDefenderCloudAppsSource(ResumableSource[MicrosoftDefenderCloudAppsSourceConfig, DefenderResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://learn.microsoft.com/en-us/defender-cloud-apps/api-introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTDEFENDERCLOUDAPPS

    @property
    def connection_host_fields(self) -> list[str]:
        return ["portal_url"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {"401 Client Error": AUTH_ERROR, "403 Client Error": PERMISSION_ERROR}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: MicrosoftDefenderCloudAppsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: MicrosoftDefenderCloudAppsSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            client = DefenderClient(config, team_id, self.resolve_api_version(api_version))
            client.validate_credentials(schema_name or "alerts")
        except ValueError as error:
            return False, str(error)
        except HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status == 401:
                return False, AUTH_ERROR
            if status == 403:
                return False, PERMISSION_ERROR
            raise
        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DefenderResumeConfig]:
        return ResumableSourceManager(inputs, DefenderResumeConfig)

    def source_for_pipeline(
        self,
        config: MicrosoftDefenderCloudAppsSourceConfig,
        resumable_source_manager: ResumableSourceManager[DefenderResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return DefenderClient(config, inputs.team_id, self.resolve_api_version(inputs.api_version)).source_response(
            inputs, resumable_source_manager
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Defender for Cloud Apps",
            iconPath="/static/services/microsoft_defender_cloud_apps.png",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "Create a token in Microsoft Defender under Settings > Cloud Apps > System > API tokens. "
                "Use a token from a user with permission to read the selected tables. "
                "Find the portal URL under System > About. "
                "Files and entities require Microsoft Defender for Cloud Apps. "
                "Incremental imports collect new alerts. Use a full refresh to update older alert statuses."
            ),
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="portal_url",
                        label="Portal URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        secret=False,
                        placeholder="https://your-tenant.us2.portal.cloudappsecurity.com",
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        secret=True,
                        required=True,
                        placeholder="",
                    ),
                ],
            ),
        )
