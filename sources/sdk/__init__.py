"""The only import surface for a vendor directory under `sources/`.

A vendor imports shared code from this module (or from `sources.sdk.testing` in tests), and its own
directory as `sources.<vendor>`. tach (`sources.*` in `tach.toml`) forbids every other first-party import.

This module only re-exports. `gen_sdk.py` in the layer 2 scripts wrote it from the imports the vendors
had. To add a name, import it here from its origin module and add it to `__all__`. The goal is that
every name here imports without Django at module level, so a vendor can run its tests without the
Django settings. That is not true yet: several origin modules import Django models or settings.
"""

from posthog.cloud_utils import is_cloud
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.integration import (
    ERROR_TOKEN_REFRESH_FAILED,
    INSTAGRAM_OAUTH_SCOPE,
    InstagramIntegration,
    OauthIntegration,
)
from posthog.models.integration.model import Integration
from posthog.security.url_validation import is_url_allowed
from posthog.temporal.common.errors import NonReportableError
from posthog.temporal.common.shutdown import WorkerShuttingDownError

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldFileUploadConfig,
    SourceFieldFileUploadJsonFormatConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthAccountSelectConfig,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
    SourceFieldSwitchGroupConfig,
    SuggestedTable,
)
from products.warehouse_sources.backend.facade.types import (
    ExternalDataSchemaSyncType,
    ExternalDataSourceType,
    IncrementalField,
    IncrementalFieldType,
)
from products.warehouse_sources.backend.models.external_data_schema import (
    SCHEMA_RESOURCE_ID_METADATA_KEY,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.models.ssh_tunnel import from_private_key
from products.warehouse_sources.backend.temporal.data_imports.sources.common import (
    config,
    integration_secrets,
    source_helpers,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    UNVERSIONED_API_VERSION,
    FieldType,
    ResumableSource,
    SimpleSource,
    VersionDeprecation,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.boundary_checkpoint import (
    BoundaryCheckpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
    CanonicalEndpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.config import Config, str_to_optional_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import (
    CursorSource,
    SourceCursorManager,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
    parse_datetime_value,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.errors import auth_non_retryable_errors
from products.warehouse_sources.backend.temporal.data_imports.sources.common.excel_parsing import (
    EXCEL_ERROR,
    MAX_EXCEL_FILE_BYTES,
    ExcelFileError,
    iter_worksheet_rows,
    list_worksheets,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.file_parsing import (
    CHUNK_SIZE,
    DELIMITER_ERROR,
    FILE_MODIFIED_AT_COLUMN,
    FILE_PATH_COLUMN,
    FORMAT_ERROR,
    ConfiguredFileFormat,
    FileDelimiterError,
    FileFormatError,
    is_format_inferable,
    iter_file_rows,
    normalize_delimiter,
    resolve_file_format,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    DEFAULT_RETRY,
    make_tracked_adapter,
    make_tracked_session,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.observer import redact_request_urls
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import (
    BoundedRetry,
    TrackedHTTPAdapter,
    _NoRedirectSession,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.url_utils import (
    redact_literal_values,
    scrub_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccount,
    IntegrationAccountListingError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (
    OAuthMixin,
    ValidateDatabaseHostMixin,
    _is_host_safe,
    log_connection_open,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import (
    SourceKey,
    SourceRegistry,
    source_key,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.request_pacer import (
    RequestPacer,
    submit_with_context,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    create_paginator,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAUTH2_PERMANENT_ERROR_MARKER,
    APIKeyAuth,
    AuthConfigBase,
    BearerTokenAuth,
    HttpBasicAuth,
    OAuth2Auth,
    OAuth2AuthRequestError,
    OAuth2GrantType,
    strip_oauth2_permanent_marker,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    create_auth,
    create_response_hooks,
    make_parent_key_name,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
    build_chained_resource,
    build_dependent_resource,
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.jsonpath_utils import (
    TJsonPath,
    find_values,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BaseNextUrlPaginator,
    BasePaginator,
    HeaderLinkPaginator,
    JSONLinkPaginator,
    JSONResponseCursorPaginator,
    JSONResponsePaginator,
    OffsetPaginator,
    PageNumberPaginator,
    ParamLocation,
    SinglePagePaginator,
    _inject_param,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClient,
    RESTClientNonRetryableError,
    RESTClientRetryableError,
    _looks_like_json,
    _safe_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ApiKeyAuthConfig,
    AuthConfig,
    BearerTokenAuthConfig,
    ClientConfig,
    Endpoint,
    EndpointResource,
    HttpBasicAuthConfig,
    HTTPMethodBasic,
    IncrementalConfig,
    JSONResponseCursorPaginatorConfig,
    OAuth2AuthConfig,
    PageNumberPaginatorConfig,
    PaginatorConfig,
    ResponseAction,
    RESTAPIConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.utils import (
    resolve_request_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    UNKNOWN_RESOURCE_PREFIX,
    SourceSchema,
    UnknownResourceError,
    build_endpoint_schemas,
    incremental_field,
    rank_incremental_fields,
    schema_for_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql import BacktickIdentifierQuoter
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.base import SQLSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.implementation import (
    SourceMetadata,
    SQLSourceImplementation,
    TableStats,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.incremental import (
    IncrementalFieldFilter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.location import (
    normalize_namespace,
    resolve_source_location,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates import (
    RowFilterColumn,
    ValidatedRowFilter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.query_builder import (
    ParamStyle,
    SelectQueryBuilder,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sync_window import SyncWindow
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    PartitionFormat,
    PartitionMode,
    SortMode,
    SourceInputs,
    SourceResponse,
    TDataType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.salesforce.auth import (
    salesforce_refresh_access_token,
)

__all__ = [
    "APIKeyAuth",
    "ApiKeyAuthConfig",
    "AuthConfig",
    "AuthConfigBase",
    "BacktickIdentifierQuoter",
    "BaseNextUrlPaginator",
    "BasePaginator",
    "BearerTokenAuth",
    "BearerTokenAuthConfig",
    "BoundaryCheckpoint",
    "BoundedRetry",
    "CHUNK_SIZE",
    "CanonicalDescriptions",
    "CanonicalEndpoint",
    "ClientConfig",
    "Config",
    "ConfiguredFileFormat",
    "CursorSource",
    "DEFAULT_RETRY",
    "DELIMITER_ERROR",
    "DataWarehouseSourceCategory",
    "DependentEndpointConfig",
    "ERROR_TOKEN_REFRESH_FAILED",
    "EXCEL_ERROR",
    "Endpoint",
    "EndpointResource",
    "ExcelFileError",
    "ExternalDataSchemaSyncType",
    "ExternalDataSourceType",
    "FILE_MODIFIED_AT_COLUMN",
    "FILE_PATH_COLUMN",
    "FORMAT_ERROR",
    "FieldType",
    "FileDelimiterError",
    "FileFormatError",
    "HTTPMethodBasic",
    "HeaderLinkPaginator",
    "HttpBasicAuth",
    "HttpBasicAuthConfig",
    "INSTAGRAM_OAUTH_SCOPE",
    "IncrementalConfig",
    "IncrementalField",
    "IncrementalFieldFilter",
    "IncrementalFieldType",
    "InstagramIntegration",
    "Integration",
    "IntegrationAccount",
    "IntegrationAccountListingError",
    "JSONLinkPaginator",
    "JSONResponseCursorPaginator",
    "JSONResponseCursorPaginatorConfig",
    "JSONResponsePaginator",
    "MAX_EXCEL_FILE_BYTES",
    "NonReportableError",
    "OAUTH2_PERMANENT_ERROR_MARKER",
    "OAuth2Auth",
    "OAuth2AuthConfig",
    "OAuth2AuthRequestError",
    "OAuth2GrantType",
    "OAuthMixin",
    "OauthIntegration",
    "OffsetPaginator",
    "PageNumberPaginator",
    "PageNumberPaginatorConfig",
    "PaginatorConfig",
    "ParamLocation",
    "ParamStyle",
    "PartitionFormat",
    "PartitionMode",
    "RESTAPIConfig",
    "RESTClient",
    "RESTClientNonRetryableError",
    "RESTClientRetryableError",
    "ReleaseStatus",
    "RequestPacer",
    "Resource",
    "ResponseAction",
    "ResumableSource",
    "ResumableSourceManager",
    "RowFilterColumn",
    "SCHEMA_RESOURCE_ID_METADATA_KEY",
    "SQLSource",
    "SQLSourceImplementation",
    "SelectQueryBuilder",
    "SimpleSource",
    "SinglePagePaginator",
    "SortMode",
    "SourceConfig",
    "SourceCursorManager",
    "SourceFieldFileUploadConfig",
    "SourceFieldFileUploadJsonFormatConfig",
    "SourceFieldInputConfig",
    "SourceFieldInputConfigType",
    "SourceFieldOauthAccountSelectConfig",
    "SourceFieldOauthConfig",
    "SourceFieldSelectConfig",
    "SourceFieldSelectConfigOption",
    "SourceFieldSwitchGroupConfig",
    "SourceInputs",
    "SourceKey",
    "SourceMetadata",
    "SourceRegistry",
    "SourceResponse",
    "SourceSchema",
    "SuggestedTable",
    "SyncWindow",
    "TDataType",
    "TJsonPath",
    "TableStats",
    "TrackedHTTPAdapter",
    "UNKNOWN_RESOURCE_PREFIX",
    "UNVERSIONED_API_VERSION",
    "UnknownResourceError",
    "ValidateDatabaseHostMixin",
    "ValidatedRowFilter",
    "VersionDeprecation",
    "WorkerShuttingDownError",
    "_NoRedirectSession",
    "_inject_param",
    "_is_host_safe",
    "_looks_like_json",
    "_safe_url",
    "auth_non_retryable_errors",
    "build_chained_resource",
    "build_dependent_resource",
    "build_endpoint_schemas",
    "capture_exception",
    "coerce_datetime_to_utc",
    "config",
    "create_auth",
    "create_paginator",
    "create_response_hooks",
    "find_values",
    "from_private_key",
    "frozen",
    "incremental_field",
    "integration_secrets",
    "is_cloud",
    "is_format_inferable",
    "is_url_allowed",
    "iter_file_rows",
    "iter_worksheet_rows",
    "list_worksheets",
    "log_connection_open",
    "make_parent_key_name",
    "make_tracked_adapter",
    "make_tracked_session",
    "normalize_delimiter",
    "normalize_namespace",
    "parse_datetime_value",
    "rank_incremental_fields",
    "redact_literal_values",
    "redact_request_urls",
    "rename_parent_fields",
    "resolve_file_format",
    "resolve_request_url",
    "resolve_source_location",
    "rest_api_resource",
    "rest_api_resources",
    "salesforce_refresh_access_token",
    "schema_for_resource",
    "scrub_url",
    "source_helpers",
    "source_key",
    "str_to_optional_list",
    "strip_oauth2_permanent_marker",
    "submit_with_context",
    "update_sync_type_config_keys",
    "validate_via_probe",
]
