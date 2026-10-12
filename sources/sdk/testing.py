"""The names that only vendor tests import.

Keep production imports in `sources.sdk`. A patch target must name the origin module of the
object (for example `products...common.resumable.get_client`), not this module, because a patch
on a re-export changes nothing.
"""

from posthog.hogql.parser import parse_select

from products.warehouse_sources.backend.temporal.data_imports.sources.common import boundary_checkpoint, resumable
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import rest_client
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    DEFAULT_RETRY_ATTEMPTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import activate_safe_point
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    build_default_schemas,
    build_default_sync_settings,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates import ColumnTypeCategory
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)

__all__ = [
    "ColumnTypeCategory",
    "DEFAULT_RETRY_ATTEMPTS",
    "ScriptedResponse",
    "SourceDriver",
    "activate_safe_point",
    "boundary_checkpoint",
    "build_default_schemas",
    "build_default_sync_settings",
    "error_message_matches",
    "parse_select",
    "rest_client",
    "resumable",
]
