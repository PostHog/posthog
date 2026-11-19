"""The names that only vendor tests import.

Keep production imports in `products.warehouse_sources.sources.sdk`. A patch target must name the origin module of the
object (for example `products...common.resumable.get_client`), not this module, because a patch
on a re-export changes nothing.
"""

from posthog.hogql.parser import parse_select

from posthog.credentials_service.errors import CredentialsServiceFailure
from posthog.models.integration.model import Integration
from posthog.temporal.common.codec import EncryptionCodec
from posthog.test.anti_ssrf import mock_anti_ssrf_dns_lookup

from products.cdp.backend.templates.helpers import BaseHogFunctionTemplateSimpleTest
from products.cdp.backend.validation import compile_hog
from products.warehouse_sources.backend.temporal.data_imports.sources.common import boundary_checkpoint, resumable
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.file_parsing import FileFormatError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import HostResolution
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store import source_base
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.config import StoreConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.errors import (
    ACCESS_DENIED_ERROR,
    INVALID_CONFIG_ERROR,
    NO_IMPORTABLE_FILES_ERROR,
    NO_SUCH_BUCKET_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.filesystem import (
    ObjectStore,
    open_store,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.self_managed import (
    parse_self_managed_url,
)
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
    http_response,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.tests.resolver import addrinfo, resolver
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import ReplaceScope

from common.hogvm.python.execute import execute_bytecode

__all__ = [
    "ACCESS_DENIED_ERROR",
    "BaseHogFunctionTemplateSimpleTest",
    "ColumnTypeCategory",
    "CredentialsServiceFailure",
    "DEFAULT_RETRY_ATTEMPTS",
    "DriveResult",
    "EncryptionCodec",
    "FakeNetwork",
    "FileFormatError",
    "HostResolution",
    "INVALID_CONFIG_ERROR",
    "Integration",
    "NO_IMPORTABLE_FILES_ERROR",
    "NO_SUCH_BUCKET_ERROR",
    "ObjectStore",
    "RecordedRequest",
    "ReplaceScope",
    "RunStopped",
    "Script",
    "ScriptedResponse",
    "SourceDriver",
    "StoreConfig",
    "UnexpectedRequest",
    "activate_safe_point",
    "addrinfo",
    "always",
    "boundary_checkpoint",
    "build_default_schemas",
    "build_default_sync_settings",
    "compile_hog",
    "error_message_matches",
    "execute_bytecode",
    "http_response",
    "mock_anti_ssrf_dns_lookup",
    "open_store",
    "parse_select",
    "parse_self_managed_url",
    "resolver",
    "rest_client",
    "resumable",
    "route",
    "scripted_network",
    "source_base",
    "source_inputs",
]
