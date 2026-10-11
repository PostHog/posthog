"""The shared import surface for the vendor directories under `sources/`.

Vendor directories still import shared code from `products.warehouse_sources` directly. This module
re-exports that code, so vendor imports can move here and tach can then forbid all other imports.
"""

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSwitchGroupConfig,
)
from products.warehouse_sources.backend.facade.types import IncrementalField, IncrementalFieldType
from products.warehouse_sources.backend.temporal.data_imports.sources.common import config
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    FieldType,
    ResumableSource,
    SimpleSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import (
    SourceKey,
    SourceRegistry,
    source_key,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse

__all__ = [
    "CanonicalDescriptions",
    "DataWarehouseSourceCategory",
    "EndpointResource",
    "FieldType",
    "IncrementalField",
    "IncrementalFieldType",
    "PageNumberPaginator",
    "RESTAPIConfig",
    "ReleaseStatus",
    "Resource",
    "ResumableSource",
    "ResumableSourceManager",
    "SimpleSource",
    "SourceConfig",
    "SourceFieldInputConfig",
    "SourceFieldInputConfigType",
    "SourceFieldSwitchGroupConfig",
    "SourceInputs",
    "SourceKey",
    "SourceRegistry",
    "SourceResponse",
    "SourceSchema",
    "build_endpoint_schemas",
    "config",
    "frozen",
    "make_tracked_session",
    "rest_api_resource",
    "source_key",
]
