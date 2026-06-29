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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.freshsales import (
    FreshsalesResumeConfig,
    check_credentials,
    freshsales_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FreshsalesSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FreshsalesSource(ResumableSource[FreshsalesSourceConfig, FreshsalesResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FRESHSALES

    @property
    def connection_host_fields(self) -> list[str]:
        # The API key is sent to the host derived from `domain`; retargeting it must re-require the key.
        return ["domain"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FRESHSALES,
            category=DataWarehouseSourceCategory.CRM,
            label="Freshsales",
            caption="""Enter your Freshsales domain and API key to pull your Freshsales (Freshworks CRM) data into the PostHog Data warehouse.

Both are available under **Profile settings → API settings** in Freshsales.

- **Domain** is your bundle alias — the subdomain of your Freshsales URL (e.g. `yourcompany` for `yourcompany.myfreshworks.com`).
- **API key** is sent as `Token token=<key>`. The key only exposes data the associated user can access, so make sure that user can read the objects you want to sync.
""",
            iconPath="/static/services/freshsales.png",
            docsUrl="https://posthog.com/docs/cdp/sources/freshsales",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="domain",
                        label="Freshsales domain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="yourcompany",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: FreshsalesSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: FreshsalesSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        ok, error, status = check_credentials(config.api_key, config.domain, schema_name)
        if ok:
            return True, None
        # A 403 at source-create means a valid key without scope for the probed endpoint — accept it,
        # since the user may only sync endpoints they can access. Sync-time 403s fail via get_non_retryable_errors.
        if status == 403 and schema_name is None:
            return True, None
        return False, error

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Freshsales API key is invalid or expired. Please generate a new key and reconnect.",
            "403 Client Error": "Your Freshsales API key does not have permission to access this resource.",
            "Invalid Freshsales API key": "Your Freshsales API key is invalid or expired. Please generate a new key and reconnect.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FreshsalesResumeConfig]:
        return ResumableSourceManager[FreshsalesResumeConfig](inputs, FreshsalesResumeConfig)

    def source_for_pipeline(
        self,
        config: FreshsalesSourceConfig,
        resumable_source_manager: ResumableSourceManager[FreshsalesResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return freshsales_source(
            api_key=config.api_key,
            domain=config.domain,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
