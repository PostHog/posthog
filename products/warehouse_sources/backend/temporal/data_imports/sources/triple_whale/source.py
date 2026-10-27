from datetime import UTC, date, datetime
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
    schema_for_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.triplewhale import (
    TripleWhaleSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.triple_whale.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.triple_whale.triple_whale import (
    TripleWhaleResumeConfig,
    probe_credentials,
    triple_whale_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TripleWhaleSource(ResumableSource[TripleWhaleSourceConfig, TripleWhaleResumeConfig]):
    codebase_detection = detect(
        env=("^(TRIPLE_WHALE|TRIPLEWHALE)_",),
        npm=("@triplewhale/react-native-triple-pixel",),
        swiftpm=("github.com/triple-whale/triple-pixel-sdk-spm",),
    )

    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://triplewhale.readme.io/reference/get-customer-journey-attribution-data"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TRIPLEWHALE

    def get_schemas(
        self,
        config: TripleWhaleSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            descriptions={name: endpoint.description for name, endpoint in ENDPOINTS.items()},
        )

    def validate_credentials(
        self,
        config: TripleWhaleSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not config.api_key.strip() or not config.api_key.isascii() or any(c in config.api_key for c in "\r\n"):
            return False, "Enter a valid Triple Whale API key."
        if not config.shop.strip() or any(c in config.shop for c in "/:\r\n "):
            return False, "Enter the shop domain from Triple Whale Settings > Store, without a URL prefix."
        try:
            start = date.fromisoformat(config.start_date)
            if start.isoformat() != config.start_date or start > datetime.now(UTC).date():
                raise ValueError
        except ValueError:
            return False, "Enter an import start date in YYYY-MM-DD format. The date must not be in the future."
        if schema_name is not None:
            schema_for_resource(ENDPOINTS, schema_name)
        response = probe_credentials(config, self.resolve_api_version(api_version), schema_name)
        if response.status_code == 401:
            return False, "Triple Whale rejected the API key. Replace revoked or expired keys."
        if response.status_code == 403:
            if schema_name is None:
                return True, None
            return False, f"Grant the API key {ENDPOINTS[schema_name].scope} read access and access to this shop."
        response.raise_for_status()
        return True, None

    def get_endpoint_permissions(
        self, config: TripleWhaleSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        return {name: self.validate_credentials(config, team_id, name, api_version)[1] for name in endpoints}

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Triple Whale rejected the API key. Replace revoked or expired keys. Keys also stop working when their owner leaves.",
            "403 Client Error": "Grant the API key access to this shop and the selected table's read scope: Pixel Attribution or Summary Page.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.triple_whale.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TripleWhaleResumeConfig]:
        return ResumableSourceManager(inputs, TripleWhaleResumeConfig)

    def source_for_pipeline(
        self,
        config: TripleWhaleSourceConfig,
        resumable_source_manager: ResumableSourceManager[TripleWhaleResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return triple_whale_source(
            config, resumable_source_manager, inputs, self.resolve_api_version(inputs.api_version)
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TRIPLEWHALE,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Triple Whale",
            caption="Import order journeys and daily metrics. Full refresh captures changes to historical data.",
            docsUrl="https://posthog.com/docs/cdp/sources/triple-whale",
            iconPath="/static/services/triple_whale.png",
            releaseStatus=ReleaseStatus.BETA,
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
                        caption="Create a key in Data > APIs. Grant Pixel Attribution and Summary Page read access for both tables.",
                    ),
                    SourceFieldInputConfig(
                        name="shop",
                        label="Shop domain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="example.myshopify.com",
                        secret=False,
                        caption="Copy the shop domain from Settings > Store. The API key owner must have access to this shop.",
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Import start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="2024-01-01",
                        secret=False,
                        caption="Use YYYY-MM-DD. Each sync reads all data from this date. Long date ranges require more requests.",
                    ),
                ],
            ),
        )
