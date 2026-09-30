from typing import cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.heygen import HeyGenSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.heygen.heygen import (
    INVALID_API_KEY,
    HeyGenResumeConfig,
    heygen_source,
    permission_error,
    probe_endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.heygen.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HeyGenSource(ResumableSource[HeyGenSourceConfig, HeyGenResumeConfig]):
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://developers.heygen.com/endpoint-version-comparison"
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HEYGEN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.HEYGEN,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="HeyGen",
            docsUrl="https://posthog.com/docs/cdp/sources/heygen",
            caption=(
                "Create an API key in [HeyGen settings](https://app.heygen.com/developers/api). "
                "Grant read scopes for the tables you select: `videos:read`, `translations:read`, "
                "`video_agent:read`, `avatars:read`, `voices:read`, `templates:read`, and `account:read`. "
                "Avatar and voice tables include your private resources."
            ),
            iconPath="/static/services/heygen.png",
            keywords=["ai video", "avatar", "video generation", "heygen"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        placeholder="",
                        required=True,
                        secret=True,
                    )
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_schemas(
        self,
        config: HeyGenSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: HeyGenSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in ENDPOINTS:
            return False, f"Unknown HeyGen table: {schema_name}"
        endpoint = schema_name or "account"
        status = probe_endpoint(config.api_key, endpoint, self.resolve_api_version(api_version))
        if status == 401:
            return False, INVALID_API_KEY
        if status == 403 and schema_name is not None:
            return False, permission_error(endpoint)
        return True, None

    def get_endpoint_permissions(
        self, config: HeyGenSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        result: dict[str, str | None] = {}
        for endpoint in endpoints:
            status = probe_endpoint(config.api_key, endpoint, self.resolve_api_version(api_version))
            result[endpoint] = (
                INVALID_API_KEY if status == 401 else permission_error(endpoint) if status == 403 else None
            )
        return result

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": INVALID_API_KEY,
            "403 Client Error": "Your HeyGen API key cannot read this table. Check its read scopes and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.heygen.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HeyGenResumeConfig]:
        return ResumableSourceManager(inputs, HeyGenResumeConfig)

    def source_for_pipeline(
        self,
        config: HeyGenSourceConfig,
        resumable_source_manager: ResumableSourceManager[HeyGenResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return heygen_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
