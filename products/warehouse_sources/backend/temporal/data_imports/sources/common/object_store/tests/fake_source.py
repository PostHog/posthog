import dataclasses
from collections.abc import Callable
from typing import Any

from products.warehouse_sources.backend.facade.source_config import SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.config import Config
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.config import (
    AzureBlobConfig,
    DiscoveryOptions,
    ObjectStoreConfig,
    ObjectStoreProvider,
    StoreConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.locations import (
    parse_azure_url,
    parse_gcs_url,
    parse_r2_url,
    parse_s3_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.self_managed import (
    SelfManagedCredential,
    SelfManagedLocation,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.source_base import (
    ObjectStorageSource,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

StoreBuilder = Callable[[dict[str, Any]], StoreConfig]


def _s3_compatible(provider: ObjectStoreProvider, parse: Callable[[str], Any]) -> StoreBuilder:
    def build(values: dict[str, Any]) -> StoreConfig:
        return ObjectStoreConfig.from_url(
            provider,
            parse(values["url_pattern"]),
            access_key_id=values["access_key_id"],
            secret_access_key=values["secret_access_key"],
        )

    return build


def _azure(values: dict[str, Any]) -> StoreConfig:
    return AzureBlobConfig.from_url(parse_azure_url(values["url_pattern"]), account_key=values["account_key"])


STORE_BUILDERS: dict[str, StoreBuilder] = {
    "s3": _s3_compatible(ObjectStoreProvider.S3, parse_s3_url),
    "gcs": _s3_compatible(ObjectStoreProvider.GCS, parse_gcs_url),
    "r2": _s3_compatible(ObjectStoreProvider.R2, parse_r2_url),
    "azure": _azure,
}


@dataclasses.dataclass(frozen=False)
class FakeObjectStorageConfig(Config):
    values: dict[str, Any]


class FakeObjectStorageSource(ObjectStorageSource[FakeObjectStorageConfig]):
    """An object storage source made only from the shared layer: the job inputs are the config."""

    self_managed_service = "s3"

    def __init__(
        self,
        build_store_config: StoreBuilder = STORE_BUILDERS["s3"],
        connection_inputs: dict[str, Any] | None = None,
    ) -> None:
        self._build_store_config = build_store_config
        self._connection_inputs = connection_inputs or {}

    @property
    def source_type(self) -> ExternalDataSourceType:
        raise NotImplementedError

    @property
    def get_source_config(self) -> SourceConfig:
        raise NotImplementedError

    def parse_config(self, job_inputs: dict) -> FakeObjectStorageConfig:
        return FakeObjectStorageConfig(values=dict(job_inputs))

    def serialize_config(self, config: FakeObjectStorageConfig) -> dict[str, Any]:
        return dict(config.values)

    def object_store_config(self, config: FakeObjectStorageConfig) -> StoreConfig:
        return self._build_store_config(config.values)

    def discovery_options(self, config: FakeObjectStorageConfig) -> DiscoveryOptions:
        return DiscoveryOptions()

    def self_managed_connection_inputs(
        self, location: SelfManagedLocation, credential: SelfManagedCredential
    ) -> dict[str, Any]:
        return self._connection_inputs
