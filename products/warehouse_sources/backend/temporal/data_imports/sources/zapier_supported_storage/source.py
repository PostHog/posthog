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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    ZapierSupportedStorageSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zapier_supported_storage.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    ZAPIER_SUPPORTED_STORAGE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zapier_supported_storage.zapier_supported_storage import (
    validate_credentials as validate_zapier_supported_storage_credentials,
    zapier_supported_storage_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    "records": (
        "Every key/value pair in the store, one row per key with columns {key, value}. Values are "
        "returned as strings (JSON-encoded when not already a string). Full refresh only - the store "
        "exposes no timestamps or pagination."
    ),
}


@SourceRegistry.register
class ZapierSupportedStorageSource(SimpleSource[ZapierSupportedStorageSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://help.zapier.com/hc/en-us/articles/8496293271053"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZAPIERSUPPORTEDSTORAGE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ZAPIER_SUPPORTED_STORAGE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Zapier (Storage by Zapier)",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Storage by Zapier store secret to pull your key/value store into the PostHog Data warehouse.

The secret is the per-store UUID you use with the [Storage by Zapier](https://help.zapier.com/hc/en-us/articles/8496293271053) app (the `secret` value passed to `StoreClient`, or the `X-Secret` you send to `store.zapier.com`). It both identifies and authorizes the store, so treat it like a password.

Only full-refresh syncing is supported: the store has no timestamps, so every sync pulls the whole store.
""",
            iconPath="/static/services/zapier_supported_storage.png",
            docsUrl="https://posthog.com/docs/cdp/sources/zapier-supported-storage",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="secret",
                        label="Store secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="xxxxxxxx-xxxx-4xxx-xxxx-xxxxxxxxxxxx",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.zapier_supported_storage.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # The store secret is the only credential; a 401 (missing/unknown secret) or 400 (not a
            # valid UUID4) can never be fixed by retrying, so stop the sync.
            "401 Client Error: Unauthorized for url: https://store.zapier.com": "Your Storage by Zapier secret is invalid. Copy the store secret exactly and reconnect.",
            "400 Client Error: Bad Request for url: https://store.zapier.com": "Your Storage by Zapier secret must be a valid UUID4. Copy the store secret exactly and reconnect.",
        }

    def get_schemas(
        self,
        config: ZapierSupportedStorageSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            return SourceSchema(
                name=endpoint,
                # The store carries no created/updated timestamps, so incremental sync is impossible.
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=ZAPIER_SUPPORTED_STORAGE_ENDPOINTS[endpoint].should_sync_default,
                description=_ENDPOINT_DESCRIPTIONS.get(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: ZapierSupportedStorageSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_zapier_supported_storage_credentials(config.secret)

    def source_for_pipeline(self, config: ZapierSupportedStorageSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return zapier_supported_storage_source(
            secret=config.secret,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
