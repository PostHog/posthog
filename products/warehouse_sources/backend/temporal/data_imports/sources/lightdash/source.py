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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lightdash import (
    LightdashSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightdash.lightdash import (
    HOST_NOT_ALLOWED_ERROR,
    lightdash_source,
    validate_credentials as validate_lightdash_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightdash.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LightdashSource(SimpleSource[LightdashSourceConfig]):
    # `get_schemas` iterates a static endpoint catalog with no I/O, so the table list is safe to
    # render in public docs without credentials.
    lists_tables_without_credentials = True
    api_docs_url = "https://docs.lightdash.com/api-reference/v1/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LIGHTDASH

    @property
    def connection_host_fields(self) -> list[str]:
        # `instance_url` determines which host the stored personal access token is sent to;
        # retargeting it must force the editor to re-enter the token.
        return ["instance_url"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Lightdash rejected your personal access token. Generate a new token in your user settings and reconnect.",
            "403 Client Error": "Your Lightdash personal access token does not have permission to read this data. Check the token owner's project access and reconnect.",
            HOST_NOT_ALLOWED_ERROR: "The Lightdash instance URL is not allowed. Please use your instance's public URL.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.lightdash.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: LightdashSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: LightdashSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_lightdash_credentials(
            instance_url=config.instance_url,
            api_token=config.api_token,
            team_id=team_id,
            schema_name=schema_name,
        )

    def source_for_pipeline(self, config: LightdashSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return lightdash_source(
            instance_url=config.instance_url,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LIGHTDASH,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Lightdash",
            caption=(
                "Connect Lightdash with a **personal access token**, created under "
                "**Settings → Personal access tokens**. Enter the URL of your Lightdash instance "
                "(Lightdash Cloud, e.g. `https://app.lightdash.cloud`, or your self-hosted domain). "
                "The token inherits its owner's project access, so use a token from a user with "
                "access to every project you want to sync."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/lightdash",
            iconPath="/static/services/lightdash.png",
            keywords=["bi", "dashboards", "analytics"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="instance_url",
                        label="Instance URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://app.lightdash.cloud",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
