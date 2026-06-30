import time
import typing
import datetime as dt
import collections.abc

from django.conf import settings
from django.db import OperationalError, close_old_connections

import grpc
import pyarrow as pa
from google.ads.googleads import client as google_ads_client_module
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from google.ads.googleads.v23.common import types as ga_common
from google.ads.googleads.v23.enums import types as ga_enums
from google.ads.googleads.v23.resources import types as ga_resources
from google.ads.googleads.v23.services import types as ga_services
from google.ads.googleads.v23.services.services.google_ads_field_service import (
    GoogleAdsFieldServiceClient,
    pagers as field_service_pagers,
)
from google.ads.googleads.v23.services.services.google_ads_service import GoogleAdsServiceClient, pagers
from google.api_core import exceptions as google_api_exceptions
from google.auth import exceptions as google_auth_exceptions
from google.oauth2 import service_account
from google.protobuf.json_format import MessageToJson

from posthog.models.integration import Integration

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc import tracked_interceptors
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql import Column, Table
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GoogleAdsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.configs import (
    GoogleAdsResumeConfig,
    GoogleAdsSourceConfigUnion,
    clean_customer_id,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.schemas import (
    FIELD_ALIASES,
    RESOURCE_SCHEMAS,
)
from products.warehouse_sources.backend.types import IncrementalFieldType

# Host used to label the tracked gRPC transport's logs/metrics. Matches
# `GoogleAdsServiceClient.DEFAULT_ENDPOINT`.
GOOGLE_ADS_HOST = "googleads.googleapis.com"

# The Google Ads SDK hardcodes `grpc.max_receive_message_length` to 64 MiB. A single
# `GoogleAdsService.Search` page can carry up to 10,000 rows, and wide resources routinely
# serialize past 64 MiB — when that happens the gRPC client aborts the call with a
# RESOURCE_EXHAUSTED "Received message larger than max" before we process any row, failing
# the whole sync. We can't ask the API for smaller pages (`page_size` is rejected with
# PAGE_SIZE_NOT_SUPPORTED as of v17), so the only lever is raising the client's receive
# limit. 512 MiB leaves comfortable headroom over the largest payloads we've observed.
GRPC_MAX_RECEIVE_MESSAGE_LENGTH = 512 * 1024 * 1024
_GRPC_MAX_RECEIVE_MESSAGE_LENGTH_KEY = "grpc.max_receive_message_length"


def _ensure_grpc_receive_limit() -> None:
    """Raise the Google Ads gRPC client's inbound message cap in place.

    ``get_service`` reads the SDK's module-level ``_GRPC_CHANNEL_OPTIONS`` each time it builds
    a channel, so rewriting the entry here makes every channel we subsequently create pick up
    the higher limit. The update is idempotent and safe to call repeatedly.
    """
    options = google_ads_client_module._GRPC_CHANNEL_OPTIONS
    for index, (key, _value) in enumerate(options):
        if key == _GRPC_MAX_RECEIVE_MESSAGE_LENGTH_KEY:
            options[index] = (key, GRPC_MAX_RECEIVE_MESSAGE_LENGTH)
            return
    options.append((_GRPC_MAX_RECEIVE_MESSAGE_LENGTH_KEY, GRPC_MAX_RECEIVE_MESSAGE_LENGTH))


def _backoff_sleep(attempt: int) -> None:
    """Sleep before the next retry: linear growth capped at 30s (2s, 4s, 6s, ...)."""
    time.sleep(min(2 * attempt, 30))


# ``GoogleAdsClient`` performs an OAuth token refresh at construction, reaching Google's token
# endpoint over the network. Two failure shapes on that hop are transient and usually clear on a
# short backoff: a connection-level hiccup (e.g. a proxy timeout) surfaces as
# ``google.auth.exceptions.TransportError``, while a server-side blip surfaces as a ``RefreshError``
# carrying a 5xx token-endpoint response. Riding both out here avoids failing (and re-capturing) the
# whole import activity before a single row is fetched. Auth rejections (revoked/expired refresh
# token, restricted API access) also surface as ``RefreshError`` but carry an OAuth error body, not
# a 5xx — they are not retried here and still hit the non-retryable handling elsewhere.
_MAX_CLIENT_INIT_ATTEMPTS = 4

# google-auth flags token-endpoint responses with status 500/503/504/408/429 as retryable
# (``RefreshError.retryable``), but its retryable set omits 502 Bad Gateway. Google's frontend
# returns 502 as a transient HTML "Error 502 (Server Error)" page while a backend is briefly
# unreachable — as recoverable as the codes it does retry — so we recognise it explicitly.
_BAD_GATEWAY_REFRESH_ERROR_SIGNATURE = "502 (Server Error)"


def _is_transient_client_init_error(exc: BaseException) -> bool:
    """Return True for a client-construction failure worth riding out in-process.

    Covers a connection-level ``TransportError`` and a ``RefreshError`` carrying a transient 5xx
    token-endpoint response. An auth-rejection ``RefreshError`` (revoked/expired credential,
    restricted API access) is not transient — it carries ``retryable=False`` and an OAuth error
    body, never a 5xx — so it returns False and the caller's non-retryable handling still applies.
    """
    if isinstance(exc, google_auth_exceptions.TransportError):
        return True
    if isinstance(exc, google_auth_exceptions.RefreshError):
        return getattr(exc, "retryable", False) or _BAD_GATEWAY_REFRESH_ERROR_SIGNATURE in str(exc)
    return False


def _load_client_with_transient_retry(
    config_dict: dict[str, object],
    *,
    max_attempts: int = _MAX_CLIENT_INIT_ATTEMPTS,
) -> GoogleAdsClient:
    """Build a ``GoogleAdsClient`` from a config dict, retrying a transient token-refresh failure.

    Only transient failures on the token-refresh hop are retried (see
    ``_is_transient_client_init_error``); any other error — including an auth-rejection
    ``RefreshError`` — re-raises immediately so the caller's non-retryable handling still applies.
    """
    attempt = 0
    while True:
        try:
            return GoogleAdsClient.load_from_dict(config_dict)
        except Exception as e:
            attempt += 1
            if attempt >= max_attempts or not _is_transient_client_init_error(e):
                raise
            _backoff_sleep(attempt)


_MAX_INTEGRATION_FETCH_ATTEMPTS = 4


def _get_integration(integration_id: int, team_id: int) -> Integration:
    """Fetch the OAuth ``Integration`` row, retrying a transient DB failure with backoff.

    Temporal activities run in a long-lived worker that never goes through Django's request
    cycle, so a pooled Postgres connection can be closed server-side while it sits idle, or the
    connection pooler can reject the query with a wait timeout when the pool is saturated. Both
    surface as a transient ``OperationalError`` and both clear once a healthy connection is used.
    ``close_old_connections()`` evicts connections already known to be stale (and, after a failed
    query marks one unusable, drops it), so each attempt runs on a fresh connection; the short
    backoff also gives a saturated pool time to drain rather than retrying straight back into the
    same wait timeout. This read is idempotent, so it is safe to repeat. Mirrors the backoff shape
    of the client-init and search retries. ``Integration.DoesNotExist`` is left to propagate.
    """
    attempt = 0
    while True:
        close_old_connections()
        try:
            return Integration.objects.get(id=integration_id, team_id=team_id)
        except OperationalError:
            attempt += 1
            if attempt >= _MAX_INTEGRATION_FETCH_ATTEMPTS:
                raise
            _backoff_sleep(attempt)


def google_ads_client(config: GoogleAdsSourceConfigUnion, team_id: int) -> GoogleAdsClient:
    """Initialize a `GoogleAdsClient` with provided config."""
    _ensure_grpc_receive_limit()

    if isinstance(config, GoogleAdsSourceConfig):
        integration = _get_integration(config.google_ads_integration_id, team_id)

        login_customer_id: str | None = None
        if config.is_mcc_account and config.is_mcc_account.enabled:
            login_customer_id = clean_customer_id(config.is_mcc_account.mcc_client_id)

        config_dict: dict[str, object] = {
            "developer_token": settings.GOOGLE_ADS_DEVELOPER_TOKEN,
            "refresh_token": integration.refresh_token,
            "client_id": settings.GOOGLE_ADS_APP_CLIENT_ID,
            "client_secret": settings.GOOGLE_ADS_APP_CLIENT_SECRET,
            "use_proto_plus": False,
        }
        if login_customer_id is not None:
            config_dict["login_customer_id"] = login_customer_id

        client = _load_client_with_transient_retry(config_dict)
    else:
        credentials = service_account.Credentials.from_service_account_info(
            {
                "private_key": config.private_key,
                "private_key_id": config.private_key_id,
                "token_uri": config.token_uri,
                "client_email": config.client_email,
            },
            scopes=["https://www.googleapis.com/auth/adwords"],
        )
        client = GoogleAdsClient(credentials=credentials, developer_token=config.developer_token)
    return client


class GoogleAdsColumn(Column):
    """Represents a column of a Google Ads resource."""

    def __init__(
        self,
        qualified_name: str,
        data_type: ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType,
        is_repeatable: bool,
        type_url: str,
        output_name: str | None = None,
    ):
        self.name = output_name if output_name is not None else qualified_name.replace(".", "_")
        self.qualified_name = qualified_name
        self.data_type = data_type
        self.type_url = type_url
        # Some types require special handling, so we provide quick access to them
        self.is_repeatable = is_repeatable
        self.is_enum = data_type == ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.ENUM
        self.is_message = data_type == ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.MESSAGE
        self.is_date = data_type == ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.DATE

    @staticmethod
    def _safe_get_enum(enum_cls, value) -> str:
        try:
            return enum_cls(value).name
        except ValueError:
            return str(value)

    def resolve_value(self, value):
        """Coerce a raw protobuf value to the appropriate Python type."""
        if self.is_enum:
            enum_cls = _resolve_protobuf_message_type_url(self.type_url)
            if self.is_repeatable:
                return [self._safe_get_enum(enum_cls, v) for v in value]
            return self._safe_get_enum(enum_cls, value)

        if self.is_message:
            if self.is_repeatable:
                return list(map(MessageToJson, value))
            return MessageToJson(value)

        if self.is_date:
            if self.is_repeatable:
                return [dt.date.fromisoformat(v[:10]) if v else None for v in value]
            return dt.date.fromisoformat(value[:10]) if value else None

        return value

    def to_arrow_field(self):
        """Return the Arrow type associated with this column.

        Special handling for:
          * ENUM: We cast them to `str`.
          * MESSAGE: Serialized as JSON strings.
        """
        arrow_type: pa.DataType

        match self.data_type:
            case ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.BOOLEAN:
                arrow_type = pa.bool_()
            case ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.DATE:
                arrow_type = pa.date32()
            case ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.DOUBLE:
                arrow_type = pa.float64()
            case ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.ENUM:
                arrow_type = pa.string()
            case ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.FLOAT:
                arrow_type = pa.float64()
            case ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.INT32:
                arrow_type = pa.int32()
            case ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.INT64:
                arrow_type = pa.int64()
            case ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.MESSAGE:
                # Message types could be treated as Arrow structs, as they are well defined.
                # But doing so requires introspecting into Protobuf message types and resolving
                # any type inconsistencies.
                # For simplicity, we will store these as JSON strings.
                # TODO: Maybe use arrow structs later?
                arrow_type = pa.string()
            case (
                ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.RESOURCE_NAME
                | ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.STRING
            ):
                arrow_type = pa.string()
            case ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.UINT64:
                arrow_type = pa.uint64()
            case _:
                raise ValueError(f"Column '{self.name}' has an unsupported protobuf type: '{self.data_type}'")

        if self.is_repeatable:
            arrow_type = pa.list_(arrow_type)

        return pa.field(self.name, arrow_type)


def _resolve_protobuf_message_type_url(type_url: str) -> type:
    """Traverse a protobuf message type URL to find it's Python type."""
    match type_url.split("."):
        case ["google", "ads", "googleads", "v23", "common", *rest] | [
            "com",
            "google",
            "ads",
            "googleads",
            "v23",
            "common",
            *rest,
        ]:
            return _traverse_attributes(ga_common, *rest)
        case ["google", "ads", "googleads", "v23", "enums", *rest] | [
            "com",
            "google",
            "ads",
            "googleads",
            "v23",
            "enums",
            *rest,
        ]:
            return _traverse_attributes(ga_enums, *rest)
        case ["google", "ads", "googleads", "v23", "resources", *rest] | [
            "com",
            "google",
            "ads",
            "googleads",
            "v23",
            "resources",
            *rest,
        ]:
            return _traverse_attributes(ga_resources, *rest)
        case _:
            raise ValueError(f"Type url could not be found: '{type_url}'")


def _traverse_attributes(thing: typing.Any, *path: str):
    """Attempt to traverse attributes of thing."""
    current = thing

    for component in path:
        if component == "type":
            component += "_"

        current = getattr(current, component)
    return current


def get_incremental_fields() -> dict[str, list[tuple[str, IncrementalFieldType]]]:
    d = {}
    for alias, contents in RESOURCE_SCHEMAS.items():
        assert isinstance(contents, dict)

        if "filter_field_names" not in contents:
            continue

        d[alias] = contents["filter_field_names"]

    return d


class GoogleAdsTable(Table[GoogleAdsColumn]):
    def __init__(
        self,
        *args,
        requires_filter: bool,
        primary_key: list[str],
        should_sync_default: bool,
        description: str | None,
        partition_keys: list[str] | None = None,
        extra_where: str | None = None,
        **kwargs,
    ):
        self.requires_filter = requires_filter
        self.primary_key = [pkey.replace(".", "_") for pkey in primary_key]
        self.should_sync_default = should_sync_default
        self.description = description
        self.partition_keys = [pkey.replace(".", "_") for pkey in partition_keys] if partition_keys else None
        self.extra_where = extra_where
        super().__init__(*args, **kwargs)


TableSchemas = dict[str, GoogleAdsTable]


def get_schemas(config: GoogleAdsSourceConfigUnion, team_id: int) -> TableSchemas:
    """Obtain Google Ads schemas.

    This is a two step process:
    1. Query all Google Ads resources resources.
    2. Query the fields for said resources.

    Only selectable fields are, well, selected.
    """
    client = google_ads_client(config, team_id)
    gaf_service = client.get_service("GoogleAdsFieldService", interceptors=tracked_interceptors(GOOGLE_ADS_HOST))
    fields_query = _search_fields_with_transient_retry(
        gaf_service, "select name, data_type, is_repeated, type_url where selectable = true"
    )
    fields_map = {field.name: field for field in fields_query.results}
    table_schemas = {}

    for table_alias, resource_contents in RESOURCE_SCHEMAS.items():
        assert isinstance(resource_contents, dict)

        resource_name = resource_contents["resource_name"]
        assert isinstance(resource_name, str)

        field_names = resource_contents["field_names"]

        requires_filter = resource_contents.get("filter_field_names", None) is not None
        primary_key = typing.cast(list[str], resource_contents.get("primary_key", []))
        extra_where = typing.cast(str | None, resource_contents.get("extra_where", None))
        partition_keys = typing.cast(list[str] | None, resource_contents.get("partition_keys", None))

        should_sync_default = resource_contents.get("should_sync_default", True)
        description = resource_contents.get("description", None)

        columns = []

        for field_name in field_names:
            assert isinstance(field_name, str)

            try:
                field = fields_map[field_name]
            except KeyError:
                field = fields_map[field_name.removeprefix(f"{resource_name}.")]

            alias = FIELD_ALIASES.get(field_name)
            output_name = alias.replace(".", "_") if alias else None

            columns.append(
                GoogleAdsColumn(
                    qualified_name=field_name,
                    data_type=field.data_type,
                    is_repeatable=field.is_repeated,
                    type_url=field.type_url,
                    output_name=output_name,
                )
            )

        table = GoogleAdsTable(
            name=resource_name,
            alias=table_alias,
            requires_filter=requires_filter,
            primary_key=primary_key,
            extra_where=extra_where,
            partition_keys=partition_keys,
            columns=columns,
            parents=None,
            should_sync_default=should_sync_default,
            description=description,
        )
        table_schemas[table_alias] = table

    return table_schemas


def google_ads_source(
    config: GoogleAdsSourceConfigUnion,
    resource_name: str,
    team_id: int,
    resumable_source_manager: ResumableSourceManager[GoogleAdsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: typing.Any = None,
    incremental_field: str | None = None,
    incremental_field_type: IncrementalFieldType | None = None,
) -> SourceResponse:
    """A data warehouse Google Ads source.

    We utilize the Google Ads gRPC API to query for the configured resource and
    yield batches of rows as ``pyarrow.Table``.

    The fetch loop checkpoints the next ``page_token`` after each page is
    yielded so a restart can pick up where it left off instead of re-running
    the full query.
    """

    name = NamingConvention.normalize_identifier(resource_name)
    table = get_schemas(config, team_id)[resource_name]

    if table.requires_filter and not should_use_incremental_field:
        should_use_incremental_field = True
        incremental_field = "segments.date"
        incremental_field_type = IncrementalFieldType.Date

    def get_rows() -> collections.abc.Iterator[pa.Table]:
        query = f"SELECT {','.join(f'{field.qualified_name}' for field in table)} FROM {table.name}"

        if should_use_incremental_field:
            if incremental_field is None or incremental_field_type is None:
                raise ValueError("incremental_field and incremental_field_type can't be None")

            if db_incremental_field_last_value is None:
                last_value: int | dt.datetime | dt.date | str = incremental_type_to_initial_value(
                    incremental_field_type
                )
            else:
                last_value = db_incremental_field_last_value

            if isinstance(last_value, dt.datetime) or isinstance(last_value, dt.date):
                last_value = f"'{last_value.isoformat()}'"

            query += f" WHERE {incremental_field} >= {last_value}"

            if incremental_field_type == IncrementalFieldType.Date:
                # Dates require an upper bound too, so we pick something very in the future.
                # TODO: Make sure to bump this before 2100-01-01.
                query += f" AND {incremental_field} < '2100-01-01'"

        if table.extra_where:
            query += f" {'AND' if 'WHERE' in query else 'WHERE'} {table.extra_where}"

        client = google_ads_client(config, team_id)
        service: GoogleAdsServiceClient = client.get_service(
            "GoogleAdsService", version="v23", interceptors=tracked_interceptors(GOOGLE_ADS_HOST)
        )
        customer_id = clean_customer_id(config.customer_id)

        yield from _search_as_arrow_tables(
            service=service,
            customer_id=customer_id,
            query=query,
            table=table,
            resumable_source_manager=resumable_source_manager,
        )

    return SourceResponse(
        name=name,
        items=get_rows,
        primary_keys=table.primary_key,
        partition_count=1 if table.requires_filter else None,  # this enables partitioning
        partition_size=1 if table.requires_filter else None,  # this enables partitioning
        partition_mode="datetime" if table.requires_filter else None,
        partition_format="day" if table.requires_filter else None,
        partition_keys=table.partition_keys or (["segments_date"] if table.requires_filter else None),
    )


# Google flags ``UNAVAILABLE`` (e.g. its frontend returning ``502:Bad Gateway`` — the request never
# reached a healthy backend), ``INTERNAL`` ("Internal error encountered." from the backend), and
# ``RESOURCE_EXHAUSTED`` ("Resource has been exhausted (e.g. check quota)." — a quota/rate-limit
# rejection) as transient, retry-with-backoff statuses: a fresh attempt after a short backoff usually
# succeeds. Riding the blip out in-process keeps the whole import activity from failing — which
# would otherwise re-fetch schemas, rebuild the gRPC client, and restart pagination from the last
# checkpoint — and avoids the captured error-tracking noise.
_MAX_TRANSIENT_SEARCH_ATTEMPTS = 4

_TRANSIENT_GRPC_STATUS_CODES = frozenset(
    {grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.INTERNAL, grpc.StatusCode.RESOURCE_EXHAUSTED}
)

# A client-side "Received message larger than max" abort also carries ``RESOURCE_EXHAUSTED`` (see the
# receive-limit note at the top of this module), but it is deterministic — a retry re-requests the
# same oversized page and fails identically — so it is excluded from the transient set. Raising the
# receive limit, not retrying, is what addresses it.
_RECEIVE_LIMIT_EXHAUSTED_SIGNATURE = "Received message larger than max"


def _is_transient_grpc_error(exc: BaseException) -> bool:
    """Return True for a transient gRPC failure Google's guidance says to retry.

    The gapic transport usually surfaces these as ``google.api_core.exceptions.ServiceUnavailable``
    / ``InternalServerError`` / ``ResourceExhausted``, but the raw ``grpc`` ``_InactiveRpcError``
    (whose ``code()`` returns the ``StatusCode``) can also propagate. The Google Ads SDK additionally
    re-wraps the transport error in a ``GoogleAdsException`` when it can pull an ads ``failure`` from
    the trailing metadata (e.g. a backend ``DEADLINE_EXCEEDED`` returned alongside the status); the
    gRPC status then lives on the wrapped ``error``, so we unwrap and inspect it too.
    """
    if isinstance(exc, google_api_exceptions.ServiceUnavailable | google_api_exceptions.InternalServerError):
        return True
    candidate: typing.Any = exc.error if isinstance(exc, GoogleAdsException) else exc
    # ``ResourceExhausted`` exposes ``code`` as an HTTP int, not a callable ``StatusCode``, so the
    # gapic-wrapped form is matched by type rather than via the ``code()`` check below.
    if isinstance(candidate, google_api_exceptions.ResourceExhausted):
        return _RECEIVE_LIMIT_EXHAUSTED_SIGNATURE not in str(candidate)
    code = getattr(candidate, "code", None)
    if not callable(code):
        return False
    status = code()
    if status not in _TRANSIENT_GRPC_STATUS_CODES:
        return False
    if status == grpc.StatusCode.RESOURCE_EXHAUSTED:
        return _RECEIVE_LIMIT_EXHAUSTED_SIGNATURE not in str(candidate)
    return True


_T = typing.TypeVar("_T")


def _call_with_transient_retry(
    call: collections.abc.Callable[[], _T],
    *,
    max_attempts: int = _MAX_TRANSIENT_SEARCH_ATTEMPTS,
) -> _T:
    """Run ``call``, retrying a transient gRPC failure (see ``_is_transient_grpc_error``) with backoff.

    A non-transient error re-raises immediately so the caller's handling and Temporal's retry policy
    still apply; the final attempt re-raises rather than sleeping.
    """
    attempt = 0
    while True:
        try:
            return call()
        except Exception as e:
            attempt += 1
            if attempt >= max_attempts or not _is_transient_grpc_error(e):
                raise
            _backoff_sleep(attempt)


def _search_with_transient_retry(
    service: GoogleAdsServiceClient,
    request: dict,
    *,
    max_attempts: int = _MAX_TRANSIENT_SEARCH_ATTEMPTS,
) -> pagers.SearchPager:
    """Call ``GoogleAdsService.search``, retrying a transient gRPC failure with backoff.

    Each retry re-requests the same ``page_token``, so there is no partial state to reconcile. The
    transient status may itself arrive wrapped in a ``GoogleAdsException`` (see
    ``_is_transient_grpc_error``). Non-transient errors re-raise immediately so the caller's
    stale-page-token handling and Temporal's retry policy still apply.
    """
    return _call_with_transient_retry(lambda: service.search(request=request), max_attempts=max_attempts)


def _search_fields_with_transient_retry(
    service: GoogleAdsFieldServiceClient,
    query: str,
    *,
    max_attempts: int = _MAX_TRANSIENT_SEARCH_ATTEMPTS,
) -> field_service_pagers.SearchGoogleAdsFieldsPager:
    """Call ``GoogleAdsFieldService.search_google_ads_fields``, retrying a transient gRPC failure.

    Schema discovery hits the same transient ``UNAVAILABLE`` / ``INTERNAL`` blips as the row search
    (see ``_is_transient_grpc_error``), so riding them out in-process keeps a momentary Google-side
    error from failing the whole import. Non-transient errors re-raise immediately so the caller's
    handling and Temporal's retry policy still apply.
    """
    return _call_with_transient_retry(lambda: service.search_google_ads_fields(query=query), max_attempts=max_attempts)


_STALE_PAGE_TOKEN_REQUEST_ERRORS = ("INVALID_PAGE_TOKEN", "EXPIRED_PAGE_TOKEN")


def _is_stale_page_token_error(exc: GoogleAdsException) -> bool:
    """Return True if a ``GoogleAdsException`` was caused by a stale page token.

    Google Ads search page tokens are ephemeral, but our resumption contract
    persists them (see ``_search_as_arrow_tables``). When a sync resumes from a
    token Google no longer accepts, the API rejects the request with either
    ``request_error: INVALID_PAGE_TOKEN`` (malformed/unrecognised) or
    ``request_error: EXPIRED_PAGE_TOKEN`` (a once-valid token aged out between
    runs) — both mean the same thing for us: restart pagination from the first
    page. The proto text representation is the same for proto-plus and raw
    protobuf failures, so we match on it directly.
    """
    failure = getattr(exc, "failure", None)
    if failure is None:
        return False
    failure_text = str(failure)
    return any(request_error in failure_text for request_error in _STALE_PAGE_TOKEN_REQUEST_ERRORS)


def _search_as_arrow_tables(
    service: GoogleAdsServiceClient,
    customer_id: str | None,
    query: str,
    table: GoogleAdsTable,
    resumable_source_manager: ResumableSourceManager[GoogleAdsResumeConfig],
) -> collections.abc.Generator[pa.Table]:
    """Paginate ``GoogleAdsService.search`` and yield each page as a ``pyarrow.Table``.

    Resumption contract:
    * If the manager has saved state, start from ``resume.page_token``.
    * After yielding each page, persist the token that would fetch the *next*
      page. On restart we re-enter at that saved token, so any page that was
      yielded but never acked by a save is simply re-yielded. Merge semantics
      over ``primary_keys`` dedupe those repeated rows.
    * A resumed token may have expired between runs (Google Ads page tokens are
      short-lived). If Google rejects it with ``INVALID_PAGE_TOKEN`` or
      ``EXPIRED_PAGE_TOKEN`` we discard the saved token and restart pagination
      from the first page — the same merge semantics make re-yielding
      already-synced rows safe.
    """
    page_token = ""
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            page_token = resume.page_token

    while True:
        # `GoogleAdsServiceClient.search` only accepts `customer_id` and `query`
        # as convenience kwargs — `page_token` must be passed via the `request`
        # argument (a dict is coerced to ``SearchGoogleAdsRequest`` by gapic).
        try:
            response = _search_with_transient_retry(
                service,
                {
                    "customer_id": customer_id,
                    "query": query,
                    "page_token": page_token,
                },
            )
        except GoogleAdsException as e:
            # Only a non-empty (resumed or mid-stream) token can be stale; an empty
            # token always requests the first page, so the guard also prevents an
            # infinite restart loop if the first page itself were ever rejected.
            if page_token and _is_stale_page_token_error(e):
                resumable_source_manager.save_state(GoogleAdsResumeConfig(page_token=""))
                page_token = ""
                continue
            raise

        # ``response.pages`` is a gapic pager — we only consume the first page per
        # request and drive pagination ourselves so the saved ``page_token`` is
        # always in lockstep with what we've yielded.
        page = next(iter(response.pages), None)
        if page is None:
            break

        rows = list(_response_as_dicts(page, table))
        if rows:
            yield pa.Table.from_pylist(rows, schema=table.to_arrow_schema())

        next_page_token = page.next_page_token
        if not next_page_token:
            break

        resumable_source_manager.save_state(GoogleAdsResumeConfig(page_token=next_page_token))
        page_token = next_page_token


def _response_as_dicts(
    response: ga_services.SearchGoogleAdsResponse,
    table: Table[GoogleAdsColumn],
) -> collections.abc.Iterable[dict[str, typing.Any]]:
    """Convert a Google Ads search response page into row dicts.

    Each row is packaged into a single GoogleAdsRow regardless of the
    underlying resource, with only the fields referenced by the query set.
    """
    field_paths = response.field_mask.paths
    path_to_column = {col.qualified_name: col for col in table}

    for row in response.results:
        row_dict = {}

        for path in field_paths:
            value = _traverse_attributes(row, *path.split("."))
            column = path_to_column[path]
            row_dict[column.name] = column.resolve_value(value)

        yield row_dict
