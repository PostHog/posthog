from typing import Optional, cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.strato import StratoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.strato.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.strato.strato import (
    strato_source,
    validate_credentials as validate_strato_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class StratoSource(SimpleSource[StratoSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://scp-api.strato.de/documentation/v1/en/api/documentation.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STRATO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid STRATO API token. Create a token in the STRATO CloudPanel under Management > Users and update the source.",
            "403 Client Error": "Your STRATO API user is not allowed to read this resource. Check the user's role permissions in the STRATO CloudPanel.",
            "406 Client Error": "Your STRATO API user only accepts requests from specific IP addresses. Remove the IP restriction for this API user in the STRATO CloudPanel.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.strato.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: StratoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: StratoSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_strato_credentials(config.api_token)

    def source_for_pipeline(self, config: StratoSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return strato_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.STRATO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="STRATO",
            caption=(
                "Sync your STRATO ServerCloud resources, such as servers, snapshots, images, storage, "
                "networking, and users, into the PostHog Data warehouse.\n\n"
                "This source covers the STRATO ServerCloud product only. To get an API token, open the "
                "STRATO CloudPanel, go to **Management** > **Users**, select or create a user, enable "
                "API access, and copy the API key."
            ),
            iconPath="/static/services/strato.png",
            docsUrl="https://posthog.com/docs/cdp/sources/strato",
            keywords=["hosting", "servercloud", "cloud server"],
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
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
