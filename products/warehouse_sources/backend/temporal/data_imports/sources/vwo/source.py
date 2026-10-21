from typing import cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.vwo import VWOSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vwo.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.vwo.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.vwo.vwo import (
    VWOResumeConfig,
    validate_credentials,
    vwo_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class VWOSource(ResumableSource[VWOSourceConfig, VWOResumeConfig]):
    codebase_detection = detect(
        script_hosts=("dev.visualwebsiteoptimizer.com",),
        npm=("vwo-node-sdk", "vwo-fme-node-sdk", "vwo-fme-react-sdk"),
        pypi=("vwo-python-sdk", "vwo-fme-python-sdk"),
        cocoapods=("VWO",),
        composer=("vwo/vwo-php-sdk", "vwo/vwo-fme-php-sdk"),
        go=(
            "github.com/wingify/vwo-go-sdk",
            "github.com/wingify/vwo-fme-go-sdk",
            "github.com/wingify/wingify-fme-go-sdk",
        ),
        maven=("com.vwo.sdk:vwo-java-sdk", "com.vwo.sdk:vwo-fme-java-sdk"),
        pub=("vwo_fme_flutter_sdk",),
        rubygems=("vwo-sdk", "vwo-fme-ruby-sdk", "wingify-fme-ruby-sdk"),
        swiftpm=("github.com/wingify/wingify-mobile-insights-ios-artifacts",),
    )

    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developers.wingify.com/v2/reference/introduction-1"
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.VWO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.VWO,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="VWO (Wingify)",
            keywords=["visual website optimizer", "wingify"],
            iconPath="/static/services/vwo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/vwo",
            releaseStatus=ReleaseStatus.BETA,
            caption=(
                "Create an API token in [VWO developer settings](https://app.wingify.com/#/developers/tokens). "
                "Select Browse permissions for the workspace and tables you want to import. "
                "Enter the numeric workspace ID from VWO settings. All tables use full refresh."
            ),
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
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Workspace ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: VWOSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            descriptions={name: description["description"] for name, description in CANONICAL_DESCRIPTIONS.items()},
        )
        for schema in schemas:
            schema.detected_primary_keys = list(ENDPOINTS[schema.name].primary_keys)
        return schemas

    def validate_credentials(
        self,
        config: VWOSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not config.account_id.isascii() or not config.account_id.isdecimal() or int(config.account_id) <= 0:
            return False, "Enter a positive numeric VWO workspace ID."
        if (
            not config.api_token
            or not config.api_token.isascii()
            or not config.api_token.isprintable()
            or any(c.isspace() for c in config.api_token)
        ):
            return False, "Enter a VWO API token without spaces or unsupported characters."
        if schema_name is not None and schema_name not in ENDPOINTS:
            return False, "This VWO table is not supported. Select a supported table."
        return validate_credentials(config.api_token, config.account_id, self.resolve_api_version(api_version))

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://app.wingify.com/api/": (
                "VWO rejected the API token. Generate a new token and reconnect."
            ),
            "403 Client Error: Forbidden for url: https://app.wingify.com/api/": (
                "The VWO token cannot read this table. Check the token permissions."
            ),
            "Authentication Failed": "VWO rejected the API token. Generate a new token and reconnect.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[VWOResumeConfig]:
        return ResumableSourceManager(inputs, VWOResumeConfig)

    def source_for_pipeline(
        self,
        config: VWOSourceConfig,
        resumable_source_manager: ResumableSourceManager[VWOResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return vwo_source(
            api_token=config.api_token,
            account_id=config.account_id,
            endpoint=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
