"""The only import surface for a vendor directory under `products/warehouse_sources/sources/`.

A vendor imports shared code from this module (or from `products.warehouse_sources.sources.sdk.testing` in tests), and its own
directory as `products.warehouse_sources.sources.<vendor>`. tach (`products.warehouse_sources.sources.*` in `tach.toml`) forbids every other first-party import.

This module only re-exports. `gen_sdk.py` in the layer 2 scripts wrote it from the imports the vendors
had. To add a name, import it here from its origin module and add it to `__all__`. The goal is that
every name here imports without Django at module level, so a vendor can run its tests without the
Django settings. That is not true yet: several origin modules import Django models or settings.
"""

from posthog.cache_utils import cache_for
from posthog.cloud_utils import is_cloud
from posthog.credentials_service.errors import CredentialsSecretError
from posthog.dataclasses import frozen
from posthog.egress.slack.transport import slack_request
from posthog.exceptions_capture import capture_exception
from posthog.integrations import IntegrationKind, IntegrationManager, IntegrationNotFound, IntegrationRecord
from posthog.models.integration import (
    ERROR_TOKEN_REFRESH_FAILED,
    INSTAGRAM_OAUTH_SCOPE,
    GoogleAdsIntegration,
    GoogleAdsQuotaExhaustedError,
    GoogleAdsScopeInsufficientError,
    InstagramIntegration,
    MetaAdsIntegration,
    OauthIntegration,
    google_ads_hierarchy_level,
    refresh_backoff_active,
)
from posthog.models.integration.databricks import NOT_A_DATABRICKS_HOST_MESSAGE, is_databricks_workspace_host
from posthog.schema_enums import ProductKey
from posthog.security.postgres_hosts import SUPABASE_DIRECT_HOST_IPV4_HINT, SUPABASE_DIRECT_HOST_RE
from posthog.security.url_validation import is_url_allowed
from posthog.temporal.common.client import connect
from posthog.temporal.common.errors import NonReportableError
from posthog.temporal.common.shutdown import WorkerShuttingDownError
from posthog.temporal.common.utils import make_sync_retryable_with_exponential_backoff

from products.cdp.backend.templates.hog_function_template import HogFunctionTemplateDC
from products.warehouse_sources.backend.facade.codebase_detection import NOT_DETECTABLE, detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldCredentialAccountSelectConfig,
    SourceFieldFileUploadConfig,
    SourceFieldFileUploadJsonFormatConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthAccountSelectConfig,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigConverter,
    SourceFieldSelectConfigOption,
    SourceFieldSSHTunnelConfig,
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
    ExternalDataSchema,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.external_table_definitions import get_dlt_mapping_for_external_table
from products.warehouse_sources.backend.models.ssh_tunnel import SSHTunnelConfig, from_private_key
from products.warehouse_sources.backend.temporal.data_imports.sources.common import (
    config,
    credentials_service,
    source_helpers,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP,
    UNVERSIONED_API_VERSION,
    ExternalWebhookInfo,
    FieldType,
    ResumableSource,
    SimpleSource,
    VersionDeprecation,
    WebhookCreationResult,
    WebhookDeletionResult,
    WebhookSource,
    WebhookSyncResult,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.deadline import (
    DeadlineExceededError,
    run_with_deadline,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.errors import (
    auth_non_retryable_errors,
    is_transient_egress_proxy_error,
)
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
    normalize_column_name,
    normalize_delimiter,
    resolve_file_format,
    uses_brotli_compression,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc import tracked_interceptors
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    DEFAULT_RETRY,
    make_tracked_adapter,
    make_tracked_session,
    request_deadline,
    retry_with_deadline,
    stop_at_request_deadline,
    suspend_adapter_retries,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.observer import redact_request_urls
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import (
    CLOUDFLARE_TRANSIENT_STATUSES,
    NO_RETRY,
    BoundedRetry,
    TrackedHTTPAdapter,
    _NoRedirectSession,
    default_request_timeout,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.url_utils import (
    redact_literal_values,
    scrub_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccount,
    IntegrationAccountListingError,
    filter_integration_accounts,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.interruptible_wait import (
    interruptible_wait,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.legacy_oauth import (
    LegacyOAuthGrant,
    LegacyOAuthGrantUnusable,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (
    DATABASE_HOST_NOT_ALLOWED_ERROR,
    CredentialAccountsMixin,
    HostNotAllowedError,
    OAuthMixin,
    TemporaryHostResolutionError,
    ValidateDatabaseHostMixin,
    _is_host_safe,
    is_team_allowlisted_for_internal_hosts,
    log_connection_open,
    pinned_connect_host,
    resolve_safe_host,
    unbracket_host,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.oauth_pointers import PointerPath
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.config import (
    AzureBlobConfig,
    DiscoveryOptions,
    ObjectStoreConfig,
    ObjectStoreProvider,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.fields import (
    KEYWORDS,
    discovery_options_from,
    file_option_fields,
    secret_field,
    source_caption,
    text_field,
    url_field,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.filesystem import (
    lookup_s3_bucket_region,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.locations import (
    AZURE_EXAMPLE_URL,
    GCS_EXAMPLE_URL,
    R2_EXAMPLE_URL,
    S3_EXAMPLE_URL,
    parse_azure_url,
    parse_gcs_url,
    parse_r2_url,
    parse_s3_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.self_managed import (
    SelfManagedCredential,
    SelfManagedLocation,
    UnmappableTableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.source_base import (
    ObjectStorageSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.primary_keys import resolve_merge_keys
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
    FanoutEndpointLike,
    build_chained_resource,
    build_dependent_resource,
    rename_parent_fields,
    required_parents_from_endpoint_configs,
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
    set_json_param,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import (
    Resource,
    ResumeHook,
)
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
    ParentRowFilter,
    ResponseAction,
    RESTAPIConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.utils import (
    resolve_request_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent import (
    ParentTableRef,
    iter_parent_pages_from_warehouse,
    parent_snapshot_covers_through,
    try_resolve_parent_table,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.retry_limits import max_retry_after_seconds
from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import reach_safe_point
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    UNKNOWN_RESOURCE_PREFIX,
    SourceSchema,
    UnknownResourceError,
    build_endpoint_schemas,
    incremental_field,
    rank_incremental_fields,
    schema_for_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import (
    probe_status_message,
    unreachable_vendor_message,
    validate_via_probe,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql import (
    AnsiIdentifierQuoter,
    BacktickIdentifierQuoter,
    Column,
    Table,
    resolve_table_projection,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.base import SQLSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.implementation import (
    SourceMetadata,
    SQLSourceImplementation,
    TableStats,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.incremental import (
    IncrementalFieldFilter,
    build_incremental_fields,
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
    SafeSQL,
    SelectQueryBuilder,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sync_window import SyncWindow
from products.warehouse_sources.backend.temporal.data_imports.sources.common.tls import CERTIFICATE_ERRORS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    PartitionFormat,
    PartitionMode,
    SortMode,
    SourceInputs,
    SourceResponse,
    TDataType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.salesforce.auth import (
    salesforce_refresh_access_token,
)

__all__ = [
    "APIKeyAuth",
    "AZURE_EXAMPLE_URL",
    "AnsiIdentifierQuoter",
    "ApiKeyAuthConfig",
    "AuthConfig",
    "AuthConfigBase",
    "AzureBlobConfig",
    "BacktickIdentifierQuoter",
    "BaseNextUrlPaginator",
    "BasePaginator",
    "BearerTokenAuth",
    "BearerTokenAuthConfig",
    "BoundaryCheckpoint",
    "BoundedRetry",
    "CERTIFICATE_ERRORS",
    "CHUNK_SIZE",
    "CLOUDFLARE_TRANSIENT_STATUSES",
    "CanonicalDescriptions",
    "CanonicalEndpoint",
    "ClientConfig",
    "Column",
    "Config",
    "ConfiguredFileFormat",
    "CredentialAccountsMixin",
    "CredentialsSecretError",
    "CursorSource",
    "DATABASE_HOST_NOT_ALLOWED_ERROR",
    "DEFAULT_RETRY",
    "DELIMITER_ERROR",
    "DataWarehouseSourceCategory",
    "DeadlineExceededError",
    "DependentEndpointConfig",
    "DiscoveryOptions",
    "ERROR_TOKEN_REFRESH_FAILED",
    "EXCEL_ERROR",
    "Endpoint",
    "EndpointResource",
    "ExcelFileError",
    "ExternalDataSchema",
    "ExternalDataSchemaSyncType",
    "ExternalDataSource",
    "ExternalDataSourceType",
    "ExternalWebhookInfo",
    "FILE_MODIFIED_AT_COLUMN",
    "FILE_PATH_COLUMN",
    "FORMAT_ERROR",
    "FanoutEndpointLike",
    "FieldType",
    "FileDelimiterError",
    "FileFormatError",
    "GCS_EXAMPLE_URL",
    "GoogleAdsIntegration",
    "GoogleAdsQuotaExhaustedError",
    "GoogleAdsScopeInsufficientError",
    "HTTPMethodBasic",
    "HeaderLinkPaginator",
    "HogFunctionTemplateDC",
    "HostNotAllowedError",
    "HttpBasicAuth",
    "HttpBasicAuthConfig",
    "INSTAGRAM_OAUTH_SCOPE",
    "IncrementalConfig",
    "IncrementalField",
    "IncrementalFieldFilter",
    "IncrementalFieldType",
    "InstagramIntegration",
    "IntegrationAccount",
    "IntegrationAccountListingError",
    "IntegrationKind",
    "IntegrationManager",
    "IntegrationNotFound",
    "IntegrationRecord",
    "JSONLinkPaginator",
    "JSONResponseCursorPaginator",
    "JSONResponseCursorPaginatorConfig",
    "JSONResponsePaginator",
    "KEYWORDS",
    "LegacyOAuthGrant",
    "LegacyOAuthGrantUnusable",
    "MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP",
    "MAX_EXCEL_FILE_BYTES",
    "MetaAdsIntegration",
    "NOT_A_DATABRICKS_HOST_MESSAGE",
    "NOT_DETECTABLE",
    "NO_RETRY",
    "NonReportableError",
    "OAUTH2_PERMANENT_ERROR_MARKER",
    "OAuth2Auth",
    "OAuth2AuthConfig",
    "OAuth2AuthRequestError",
    "OAuth2GrantType",
    "OAuthMixin",
    "OauthIntegration",
    "ObjectStorageSource",
    "ObjectStoreConfig",
    "ObjectStoreProvider",
    "OffsetPaginator",
    "PageNumberPaginator",
    "PageNumberPaginatorConfig",
    "PointerPath",
    "PaginatorConfig",
    "ParamLocation",
    "ParamStyle",
    "ParentRowFilter",
    "ParentTableRef",
    "PartitionFormat",
    "PartitionMode",
    "ProductKey",
    "R2_EXAMPLE_URL",
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
    "ResumeHook",
    "RowFilterColumn",
    "S3_EXAMPLE_URL",
    "SCHEMA_RESOURCE_ID_METADATA_KEY",
    "SQLSource",
    "SQLSourceImplementation",
    "SSHTunnelConfig",
    "SUPABASE_DIRECT_HOST_IPV4_HINT",
    "SUPABASE_DIRECT_HOST_RE",
    "SafeSQL",
    "SelectQueryBuilder",
    "SelfManagedCredential",
    "SelfManagedLocation",
    "SimpleSource",
    "SinglePagePaginator",
    "SortMode",
    "SourceConfig",
    "SourceCursorManager",
    "SourceFieldCredentialAccountSelectConfig",
    "SourceFieldFileUploadConfig",
    "SourceFieldFileUploadJsonFormatConfig",
    "SourceFieldInputConfig",
    "SourceFieldInputConfigType",
    "SourceFieldOauthAccountSelectConfig",
    "SourceFieldOauthConfig",
    "SourceFieldSSHTunnelConfig",
    "SourceFieldSelectConfig",
    "SourceFieldSelectConfigConverter",
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
    "Table",
    "TableStats",
    "TemporaryHostResolutionError",
    "TrackedHTTPAdapter",
    "UNKNOWN_RESOURCE_PREFIX",
    "UNVERSIONED_API_VERSION",
    "UnknownResourceError",
    "UnmappableTableError",
    "ValidateDatabaseHostMixin",
    "ValidatedRowFilter",
    "VersionDeprecation",
    "WebhookCreationResult",
    "WebhookDeletionResult",
    "WebhookSource",
    "WebhookSourceManager",
    "WebhookSyncResult",
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
    "build_incremental_fields",
    "cache_for",
    "capture_exception",
    "coerce_datetime_to_utc",
    "config",
    "connect",
    "create_auth",
    "create_paginator",
    "create_response_hooks",
    "credentials_service",
    "default_request_timeout",
    "detect",
    "discovery_options_from",
    "file_option_fields",
    "filter_integration_accounts",
    "find_values",
    "from_private_key",
    "frozen",
    "get_dlt_mapping_for_external_table",
    "google_ads_hierarchy_level",
    "incremental_field",
    "interruptible_wait",
    "is_cloud",
    "is_databricks_workspace_host",
    "is_format_inferable",
    "is_team_allowlisted_for_internal_hosts",
    "is_transient_egress_proxy_error",
    "is_url_allowed",
    "iter_file_rows",
    "iter_parent_pages_from_warehouse",
    "iter_worksheet_rows",
    "list_worksheets",
    "log_connection_open",
    "lookup_s3_bucket_region",
    "make_parent_key_name",
    "make_sync_retryable_with_exponential_backoff",
    "make_tracked_adapter",
    "make_tracked_session",
    "max_retry_after_seconds",
    "normalize_column_name",
    "normalize_delimiter",
    "normalize_namespace",
    "parent_snapshot_covers_through",
    "parse_azure_url",
    "parse_datetime_value",
    "parse_gcs_url",
    "parse_r2_url",
    "parse_s3_url",
    "pinned_connect_host",
    "probe_status_message",
    "rank_incremental_fields",
    "reach_safe_point",
    "redact_literal_values",
    "redact_request_urls",
    "refresh_backoff_active",
    "rename_parent_fields",
    "request_deadline",
    "required_parents_from_endpoint_configs",
    "resolve_file_format",
    "resolve_merge_keys",
    "resolve_request_url",
    "resolve_safe_host",
    "resolve_source_location",
    "resolve_table_projection",
    "rest_api_resource",
    "rest_api_resources",
    "retry_with_deadline",
    "run_with_deadline",
    "salesforce_refresh_access_token",
    "schema_for_resource",
    "scrub_url",
    "secret_field",
    "set_json_param",
    "slack_request",
    "source_caption",
    "source_helpers",
    "source_key",
    "stop_at_request_deadline",
    "str_to_optional_list",
    "strip_oauth2_permanent_marker",
    "submit_with_context",
    "suspend_adapter_retries",
    "text_field",
    "tracked_interceptors",
    "try_resolve_parent_table",
    "unbracket_host",
    "unreachable_vendor_message",
    "update_sync_type_config_keys",
    "url_field",
    "uses_brotli_compression",
    "validate_via_probe",
]
