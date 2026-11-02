"""The names that only vendor tests import.

Keep production imports in `products.warehouse_sources.sources.sdk`. A patch target must name the origin module of the
object (for example `products...common.resumable.get_client`), not this module, because a patch
on a re-export changes nothing.
"""

from posthog.hogql.parser import parse_select

from posthog.models.integration.model import Integration

from products.warehouse_sources.backend.temporal.data_imports.sources.common import boundary_checkpoint, resumable
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.file_parsing import FileFormatError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import HostResolution
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
    FakeNetwork,
    RunStopped,
    Script,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.driver import DriveResult
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.fake_network import RecordedRequest
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.inputs import source_inputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.responders import (
    UnexpectedRequest,
    always,
    route,
)

__all__ = [
    "ColumnTypeCategory",
    "DEFAULT_RETRY_ATTEMPTS",
    "DriveResult",
    "FakeNetwork",
    "FileFormatError",
    "HostResolution",
    "Integration",
    "RecordedRequest",
    "RunStopped",
    "Script",
    "ScriptedResponse",
    "SourceDriver",
    "UnexpectedRequest",
    "activate_safe_point",
    "always",
    "boundary_checkpoint",
    "build_default_schemas",
    "build_default_sync_settings",
    "error_message_matches",
    "parse_select",
    "rest_client",
    "resumable",
    "route",
    "scripted_network",
    "source_inputs",
]
