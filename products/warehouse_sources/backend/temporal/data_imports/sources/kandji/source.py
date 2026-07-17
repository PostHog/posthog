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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import KandjiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kandji.kandji import (
    kandji_source,
    validate_credentials as validate_kandji_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kandji.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KandjiSource(SimpleSource[KandjiSourceConfig]):
    # `get_schemas` iterates a static endpoint catalog with no I/O, so the table list is safe to
    # render in public docs without credentials.
    lists_tables_without_credentials = True
    api_docs_url = "https://api-docs.kandji.io/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KANDJI

    @property
    def connection_host_fields(self) -> list[str]:
        # `subdomain` and `region` determine which host the stored API token is sent to;
        # retargeting either must force the editor to re-enter the token.
        return ["subdomain", "region"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Your Kandji API token is invalid or expired. Generate a new token in Settings → Access and reconnect.",
            "403 Client Error: Forbidden for url": "Your Kandji API token is missing the scope required to sync this table. Update the token's permissions in Settings → Access and try again.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.kandji.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: KandjiSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: KandjiSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_kandji_credentials(
            api_token=config.api_token,
            subdomain=config.subdomain,
            region=config.region,
            schema_name=schema_name,
        )

    def source_for_pipeline(self, config: KandjiSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return kandji_source(
            api_token=config.api_token,
            subdomain=config.subdomain,
            region=config.region,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.KANDJI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Kandji (Iru Endpoint Management)",
            caption=(
                "Connect Kandji with a tenant-level **API token**, created in Kandji under "
                "**Settings → Access**. Your API URL is shown there too — enter its **subdomain** and pick "
                "the matching **region** (US or EU). The token needs read access to the devices, blueprints, "
                "and device-detail endpoints for the tables you want to sync."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/kandji",
            iconPath="/static/services/kandji.png",
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
                        name="subdomain",
                        label="Subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="accuhive",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.kandji.io)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (api.eu.kandji.io)", value="eu"),
                        ],
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
