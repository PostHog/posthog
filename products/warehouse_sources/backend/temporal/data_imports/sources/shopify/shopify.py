import re
import json
import dataclasses
from collections.abc import Iterator
from typing import Any

import requests
from requests.exceptions import ChunkedEncodingError
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.constants import ID, resolve_schema_name
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.settings import ENDPOINT_CONFIGS
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.utils import (
    ShopifyGraphQLObject,
    safe_unwrap,
    unwrap,
)

from .constants import (
    SHOPIFY_ACCESS_SCOPES_URL,
    SHOPIFY_ACCESS_TOKEN_CHECK,
    SHOPIFY_ACCESS_TOKEN_GRANT,
    SHOPIFY_ACCESS_TOKEN_URL,
    SHOPIFY_API_URL,
    SHOPIFY_API_VERSION,
    SHOPIFY_DEFAULT_PAGE_SIZE,
    SHOPIFY_GRAPHQL_OBJECTS,
    SHOPIFY_PAGE_SIZE_OVERRIDES,
)

# Resume phases for the shopify source. "all" is the non-incremental branch;
# "earliest" and "latest" are the two incremental sweeps in shopify_source.get_rows.
PHASE_ALL = "all"
PHASE_EARLIEST = "earliest"
PHASE_LATEST = "latest"

# Raised when Shopify's OAuth token endpoint returns a 4xx — the app credentials are
# invalid or the app was uninstalled, so re-auth is the only fix. `ShopifySource.
# get_non_retryable_errors` matches on this exact text to fail the job fast.
SHOPIFY_ACCESS_TOKEN_AUTH_ERROR = (
    "Failed to retrieve Shopify access token: the app credentials are invalid or the "
    "app was uninstalled. Please reconnect your Shopify integration."
)

# Substring of the GraphQL error Shopify returns when the connected access token lacks the
# scope needed to read a field, e.g. "Access denied for fulfillmentOrders field." or
# "Access denied for paymentTerms field. Required access: `read_payment_terms` access scope."
# Retrying can't grant the missing scope — the user must reconnect with expanded permissions —
# so `ShopifySource.get_non_retryable_errors` matches this substring to fail the job fast.
# The field name varies, so the match anchors on the stable leading phrase.
SHOPIFY_GRAPHQL_ACCESS_DENIED_ERROR = "Access denied for"

# Shopify's Admin API returns 402 Payment Required when the store is frozen for an unpaid
# bill — the shop owner must settle their outstanding Shopify balance to unfreeze the store,
# so retrying the import cannot recover. `requests.raise_for_status` renders this as
# "402 Client Error: Payment Required for url: https://<store>.myshopify.com/...".
# `ShopifySource.get_non_retryable_errors` matches on the stable status text (not the
# per-store URL) to fail the job fast.
SHOPIFY_PAYMENT_REQUIRED_ERROR_MATCH = "402 Client Error: Payment Required"
SHOPIFY_PAYMENT_REQUIRED_ERROR_MESSAGE = (
    "Shopify returned 402 Payment Required — your Shopify store appears to be frozen due to "
    "an unpaid bill. Settle your outstanding balance in Shopify to unfreeze the store, then "
    "the import will resume."
)


@dataclasses.dataclass
class ShopifyResumeConfig:
    phase: str
    cursor: str


class ShopifyPermissionError(Exception):
    """Raised when the access token can't read some resources.

    `missing_permissions` maps resource -> Shopify's GraphQL error; the surface layer turns it
    into a user message via `missing_permissions_message`.
    """

    def __init__(self, missing_permissions: dict[str, str]):
        self.missing_permissions = missing_permissions
        super().__init__(f"Shopify access token lacks permissions for: {', '.join(missing_permissions)}")


# Shopify names the scope a denied field needs as "Required access: `read_x` access scope."
_REQUIRED_SCOPE_RE = re.compile(r"`(read_\w+|write_\w+)`")


def missing_permissions_message(missing_permissions: dict[str, str]) -> str:
    """User-facing summary naming each unreadable resource and the scope it needs."""
    parts = []
    for resource, error in missing_permissions.items():
        scopes = _REQUIRED_SCOPE_RE.findall(error)
        parts.append(f"{resource} (needs {', '.join(scopes)})" if scopes else resource)
    return (
        f"Your Shopify access token can't read {', '.join(parts)}. "
        "Reconnect your Shopify integration and grant the listed access scopes."
    )


# Shopify's GraphQL Admin API rate-limits on a cost-based leaky bucket, so a single bucket
# can take this long to refill from empty (~2000 points at 100/sec on Plus). Cap the throttle
# wait here so a malformed `restoreRate` can't stall the worker past its heartbeat.
_SHOPIFY_MAX_THROTTLE_WAIT_SECONDS = 60.0


class ShopifyRetryableError(Exception):
    """Exception raised when Shopify issues a retryable error (e.g. rate limit, 5xx).

    `retry_after`, when set, is the number of seconds Shopify's throttle status says we
    should wait before the leaky bucket has refilled enough to satisfy the query again.
    """

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


def _throttle_retry_after(payload: Any) -> float | None:
    """Seconds to wait for the cost bucket to refill enough for the requested query.

    A throttled response carries `extensions.cost` with the points the query needed
    (`requestedQueryCost`) and how fast the bucket refills (`throttleStatus.restoreRate`),
    which is exactly how long to back off. Returns None when that data is missing or
    malformed so the caller falls back to plain exponential backoff.
    """
    cost, ok = safe_unwrap(payload, path="extensions.cost")
    if not ok or not isinstance(cost, dict):
        return None
    requested = cost.get("requestedQueryCost")
    throttle = cost.get("throttleStatus")
    if not isinstance(requested, int | float) or not isinstance(throttle, dict):
        return None
    available = throttle.get("currentlyAvailable")
    restore_rate = throttle.get("restoreRate")
    if not isinstance(available, int | float) or not isinstance(restore_rate, int | float) or restore_rate <= 0:
        return None
    deficit = requested - available
    if deficit <= 0:
        return None
    return min(deficit / restore_rate, _SHOPIFY_MAX_THROTTLE_WAIT_SECONDS)


def _get_retryable_error(payload: Any) -> ShopifyRetryableError | None:
    """Check if the response indicates a retryable error in the payload (e.g. rate limit, 5xx)"""
    errors, ok = safe_unwrap(payload, path="errors")
    if ok:
        serialized_errors = json.dumps(errors).lower()
        if "throttled" in serialized_errors:
            return ShopifyRetryableError("Shopify: rate limit exceeded...", retry_after=_throttle_retry_after(payload))
        if "internal_server_error" in serialized_errors:
            return ShopifyRetryableError(f"Shopify: internal errors in payload {serialized_errors}")
    currently_available, ok = safe_unwrap(payload, path="extensions.cost.throttleStatus.currentlyAvailable")
    if ok and isinstance(currently_available, int | float):
        # this check is a little liberal. if we find that we are getting rate limited
        # too often might be worth it to check against the requestedCost instead
        if currently_available <= 0:
            return ShopifyRetryableError("Shopify: rate limit exceeded...", retry_after=_throttle_retry_after(payload))
    return None


_shopify_backoff = wait_exponential_jitter(initial=1, max=30)


def _shopify_retry_wait(retry_state: RetryCallState) -> float:
    """Back off exponentially, but never for less than Shopify's reported refill time.

    Plain exponential backoff tops out around 15s across the 5 attempts, which can give up
    while the cost bucket is still draining. When a rate-limit response told us how long the
    bucket needs (see `_throttle_retry_after`), honor that instead.
    """
    backoff = _shopify_backoff(retry_state)
    outcome = retry_state.outcome
    if outcome is not None and not outcome.cancelled():
        exc = outcome.exception()
        if isinstance(exc, ShopifyRetryableError) and exc.retry_after is not None:
            return max(backoff, exc.retry_after)
    return backoff


def _make_paginated_shopify_request(
    url: str,
    sess: requests.Session,
    graphql_object: ShopifyGraphQLObject,
    logger: FilteringBoundLogger,
    query: str | None = None,
    phase: str = PHASE_ALL,
    initial_cursor: str | None = None,
    resumable_source_manager: ResumableSourceManager[ShopifyResumeConfig] | None = None,
) -> Iterator[list[Any]]:
    endpoint_config = ENDPOINT_CONFIGS.get(graphql_object.name)

    @retry(
        # Transient network failures (proxy/egress hiccups, connect/read timeouts) surface from
        # `sess.post` as requests ConnectionError/Timeout — e.g. a 504 from the egress proxy tunnel.
        # They're retryable like a 5xx, so reissue the request with backoff instead of failing the
        # whole import. ConnectionError covers ProxyError; Timeout covers connect/read timeouts.
        retry=retry_if_exception_type(
            (ShopifyRetryableError, requests.exceptions.ConnectionError, requests.exceptions.Timeout)
        ),
        stop=stop_after_attempt(5),
        wait=_shopify_retry_wait,
        reraise=True,
    )
    def execute(vars: dict[str, Any]):
        # `post` reads the body eagerly (stream=False), so a connection dropped mid-stream
        # surfaces here as ChunkedEncodingError. It's transient — retry it like a 5xx below.
        try:
            response = sess.post(url, json={"query": graphql_object.query, "variables": vars})
        except ChunkedEncodingError as e:
            raise ShopifyRetryableError(f"Shopify: connection broken while reading response: {e}") from e
        if response.status_code >= 500:
            raise ShopifyRetryableError(
                f"Shopify: internal error from request {response.status_code} {response.reason}"
            )
        else:
            response.raise_for_status()
        payload = response.json()
        retryable_error = _get_retryable_error(payload)
        if retryable_error:
            raise retryable_error

        if "errors" in payload:
            error_messages = [e.get("message", "") for e in payload["errors"]]
            joined = "; ".join(error_messages)
            raise Exception(f"Shopify GraphQL error: {joined}")

        if "data" not in payload:
            raise Exception(f"Unexpected graphql response format in Shopify rows read. Keys: {list(payload.keys())}")

        return payload

    pageSize = SHOPIFY_PAGE_SIZE_OVERRIDES.get(graphql_object.name, SHOPIFY_DEFAULT_PAGE_SIZE)
    vars: dict[str, Any] = {"pageSize": pageSize}
    logger.debug(f"Using page size {vars['pageSize']} for object {graphql_object.name}")
    if query:
        vars.update({"query": query})
    if initial_cursor is not None:
        vars.update({"cursor": initial_cursor})
    has_next_page = True
    while has_next_page:
        logger.debug(f"Querying shopify endpoint {graphql_object.name} with vars: {vars}")
        payload = execute(vars)
        data = unwrap(payload, path=f"data.{graphql_object.name}.nodes")
        if endpoint_config is not None:
            if endpoint_config.incremental_field_resolver:
                data = [endpoint_config.incremental_field_resolver(row) for row in data if row.get("discount")]
            if endpoint_config.partition_key_resolver:
                data = [endpoint_config.partition_key_resolver(row) for row in data if row.get("discount")]
        yield data
        page_info = unwrap(payload, path=f"data.{graphql_object.name}.pageInfo")
        has_next_page = page_info.get("hasNextPage", False)
        if has_next_page:
            # this is intentionally an unsafe lookup so errors surface if expectations aren't met
            next_cursor = page_info["endCursor"]
            vars.update({"cursor": next_cursor})
            # Checkpoint points to the NEXT unfetched page. Because this save happens
            # only after the generator is resumed past `yield data`, a shutdown/crash
            # after yielding can still cause the last yielded page to be re-fetched on
            # resume; primary-key merge semantics dedupe if that happens.
            if resumable_source_manager is not None:
                resumable_source_manager.save_state(ShopifyResumeConfig(phase=phase, cursor=next_cursor))


# A Shopify store subdomain is lowercase alphanumerics and hyphens.
_SHOPIFY_SUBDOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def normalize_store_id(raw: str) -> str:
    """Reduce whatever the user pasted to the bare Shopify store subdomain.

    The store id is interpolated into ``https://{}.myshopify.com/...``, so a value
    that already carries a scheme, a path, or the ``.myshopify.com`` suffix builds a
    broken host (e.g. ``store.myshopify.com.myshopify.com`` or a host of ``https``) —
    the single biggest cause of Shopify connection failures. Accepts ``my-store``,
    ``my-store.myshopify.com``, ``https://my-store.myshopify.com`` and the admin
    deep-link ``https://admin.shopify.com/store/my-store``, all returning ``my-store``.

    Raises ``ValueError`` if the result isn't a plain subdomain, which also pins
    outbound traffic to ``*.myshopify.com`` (no breaking out to another host).
    """
    store_id = (raw or "").strip().lower()
    store_id = store_id.removeprefix("https://").removeprefix("http://")
    # Admin deep-link: admin.shopify.com/store/<store-id>[/...]
    if store_id.startswith("admin.shopify.com/store/"):
        store_id = store_id.removeprefix("admin.shopify.com/store/")
    # Drop any path/query/fragment that rode along with a pasted URL.
    store_id = store_id.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    # Strip the domain suffix, looping to collapse an accidental double suffix.
    while store_id.endswith(".myshopify.com"):
        store_id = store_id.removesuffix(".myshopify.com")
    if not _SHOPIFY_SUBDOMAIN_RE.match(store_id):
        raise ValueError(
            f"Invalid Shopify store id {raw!r}. Enter just your store subdomain — the 'my-store' "
            "in 'my-store.myshopify.com'."
        )
    return store_id


@retry(
    # A transient TLS/connection drop on the token endpoint (e.g. SSL EOF, proxy/egress hiccup,
    # connect/read timeout) surfaces from `post` as requests ConnectionError/Timeout — SSLError
    # is a ConnectionError. A connection dropped mid-response surfaces as ChunkedEncodingError,
    # which is a RequestException rather than a ConnectionError, so it must be listed explicitly.
    # The adapter's own urllib3 retries back off for only ~1.5s, too short to ride out a
    # multi-second blip. Minting a token is idempotent, so reissue with backoff rather than failing
    # the whole import. 4xx/5xx are raised as plain Exceptions below and so are untouched here —
    # auth failures still fail fast.
    retry=retry_if_exception_type(
        (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.ChunkedEncodingError)
    ),
    stop=stop_after_attempt(5),
    wait=_shopify_backoff,
    reraise=True,
)
def _get_shopify_access_token(shopify_store_id: str, shopify_client_id: str, shopify_client_secret: str) -> str:
    # Callers pass an already-normalized store id (see normalize_store_id).
    access_token_url = SHOPIFY_ACCESS_TOKEN_URL.format(shopify_store_id)
    access_data = {
        "client_id": shopify_client_id,
        "client_secret": shopify_client_secret,
        "grant_type": SHOPIFY_ACCESS_TOKEN_GRANT,
    }
    access_res = make_tracked_session().post(access_token_url, data=access_data)
    if not access_res.ok:
        # A 4xx means the app credentials are invalid/revoked (e.g. the app was
        # uninstalled) — re-auth is the only fix, so surface a non-retryable message.
        # 429 (rate limit) and 5xx are transient and stay retryable via the generic message.
        if 400 <= access_res.status_code < 500 and access_res.status_code != 429:
            raise Exception(f"{SHOPIFY_ACCESS_TOKEN_AUTH_ERROR} (HTTP {access_res.status_code})")
        raise Exception(f"Failed to retrieve Shopify access token: {access_res}")
    return access_res.json()["access_token"]


def _get_granted_scopes(store_id: str, sess: requests.Session) -> set[str] | None:
    """The token's granted scope handles, or None on any failure — best-effort so a blip degrades
    the query rather than failing the sync."""
    try:
        res = sess.get(SHOPIFY_ACCESS_SCOPES_URL.format(store_id))
        res.raise_for_status()
        data = res.json()
    except (requests.RequestException, ValueError):
        return None
    scopes = data.get("access_scopes", []) if isinstance(data, dict) else []
    return {scope["handle"] for scope in scopes if isinstance(scope, dict) and "handle" in scope}


def shopify_source(
    shopify_store_id: str,
    shopify_client_id: str,
    shopify_client_secret: str,
    graphql_object_name: str,
    db_incremental_field_last_value: Any | None,
    db_incremental_field_earliest_value: Any | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ShopifyResumeConfig],
    should_use_incremental_field: bool = False,
):
    store_id = normalize_store_id(shopify_store_id)
    api_url = SHOPIFY_API_URL.format(store_id, SHOPIFY_API_VERSION)
    shopify_access_token = _get_shopify_access_token(store_id, shopify_client_id, shopify_client_secret)
    schema_name = resolve_schema_name(graphql_object_name)

    def get_rows():
        sess = make_tracked_session(
            headers={"X-Shopify-Access-Token": shopify_access_token, "Content-Type": "application/json"}
        )
        graphql_object = SHOPIFY_GRAPHQL_OBJECTS.get(schema_name)
        if not graphql_object:
            raise Exception(f"Shopify object does not exist: {schema_name}")

        # Drop fields the token lacks the scope to read, so a partially scoped token imports the
        # rest instead of hard-failing on "Access denied for <field>". Falls back to the minimal
        # query when scopes can't be detected.
        if graphql_object.protected_query_builder is not None:
            granted_scopes = _get_granted_scopes(store_id, sess)
            if granted_scopes is None:
                granted_scopes = set()
                logger.warning(
                    f"Shopify: could not detect granted scopes for {schema_name}; syncing without protected fields"
                )
            graphql_object = ShopifyGraphQLObject(
                name=graphql_object.name,
                query=graphql_object.protected_query_builder(granted_scopes),
                display_name=graphql_object.display_name,
                permissions_query=graphql_object.permissions_query,
                protected_query_builder=graphql_object.protected_query_builder,
            )

        logger.debug(f"Shopify: reading from resource {schema_name}")

        resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

        if not should_use_incremental_field or (
            db_incremental_field_last_value is None and db_incremental_field_earliest_value is None
        ):
            logger.debug(f"Shopify: iterating all objects from source for {schema_name}")
            initial_cursor = (
                resume_config.cursor if resume_config is not None and resume_config.phase == PHASE_ALL else None
            )
            yield from _make_paginated_shopify_request(
                api_url,
                sess,
                graphql_object,
                logger,
                phase=PHASE_ALL,
                initial_cursor=initial_cursor,
                resumable_source_manager=resumable_source_manager,
            )
            return

        endpoint_config = ENDPOINT_CONFIGS.get(schema_name)
        # query_filer is ignored if the key isn't present in the endpoint's available query filters
        query_filter = endpoint_config.query_filter if endpoint_config else "created_at"

        # Skip the earliest sweep entirely if we already resumed into the latest sweep.
        resuming_latest = resume_config is not None and resume_config.phase == PHASE_LATEST

        # check for any objects less than the minimum object we already have
        if db_incremental_field_earliest_value is not None and not resuming_latest:
            logger.debug(
                f"Shopify: iterating earliest objects from source: {query_filter} < {db_incremental_field_earliest_value}"
            )
            query = f"{query_filter}:<'{db_incremental_field_earliest_value}'"
            initial_cursor = (
                resume_config.cursor if resume_config is not None and resume_config.phase == PHASE_EARLIEST else None
            )
            yield from _make_paginated_shopify_request(
                api_url,
                sess,
                graphql_object,
                logger,
                query=query,
                phase=PHASE_EARLIEST,
                initial_cursor=initial_cursor,
                resumable_source_manager=resumable_source_manager,
            )

        # check for any objects more than the maximum object we already have
        if db_incremental_field_last_value is not None:
            logger.debug(
                f"Shopify: iterating latest objects from source: {query_filter} > {db_incremental_field_last_value}"
            )
            query = f"{query_filter}:>'{db_incremental_field_last_value}'"
            initial_cursor = (
                resume_config.cursor if resume_config is not None and resume_config.phase == PHASE_LATEST else None
            )
            yield from _make_paginated_shopify_request(
                api_url,
                sess,
                graphql_object,
                logger,
                query=query,
                phase=PHASE_LATEST,
                initial_cursor=initial_cursor,
                resumable_source_manager=resumable_source_manager,
            )

    endpoint_config = ENDPOINT_CONFIGS.get(schema_name)
    if not endpoint_config:
        raise ValueError(f"Endpoint {schema_name} has no config in shopify/settings.py")
    return SourceResponse(
        items=get_rows,
        primary_keys=[ID],
        # intentionally left as the input object name as the response name needs to match the input name
        name=graphql_object_name,
        partition_count=endpoint_config.partition_count,
        partition_size=endpoint_config.partition_size,
        partition_mode=endpoint_config.partition_mode,
        partition_format=endpoint_config.partition_format,
        partition_keys=endpoint_config.partition_keys,
    )


def _format_graphql_errors(errors: Any) -> str:
    """Join the `message` fields from a Shopify GraphQL `errors` payload into one string."""
    if isinstance(errors, list):
        messages = [error.get("message") if isinstance(error, dict) else str(error) for error in errors]
        joined = "; ".join(message for message in messages if message)
        if joined:
            return joined
    return str(errors)


def _authenticated_session(store_id: str, client_id: str, client_secret: str) -> tuple[str, requests.Session]:
    """Fetch an access token and return the GraphQL URL plus a session that carries it."""
    api_url = SHOPIFY_API_URL.format(store_id, SHOPIFY_API_VERSION)
    access_token = _get_shopify_access_token(store_id, client_id, client_secret)
    sess = make_tracked_session(headers={"Content-Type": "application/json", "X-Shopify-Access-Token": access_token})
    return api_url, sess


def _probe_resource_permission(api_url: str, sess: requests.Session, resource: ShopifyGraphQLObject) -> str | None:
    """Probe read access to one resource: None if reachable, else the GraphQL error naming the
    missing scope. Throttle/5xx and HTTP/network failures raise — they aren't permission gaps."""
    res = sess.post(api_url, json={"query": resource.permissions_query})
    res.raise_for_status()
    data = res.json()
    retryable_error = _get_retryable_error(data)
    if retryable_error is not None:
        raise retryable_error
    if "errors" in data:
        return _format_graphql_errors(data["errors"])
    return None


def validate_credentials(
    shopify_store_id: str, shopify_client_id: str, shopify_client_secret: str, resources: list[str] | None = None
) -> bool:
    """Validate Shopify credentials.

    - resources=None: only verify the access token, so connecting isn't blocked by a table the
      user may not sync (per-table scopes are surfaced via `check_endpoint_permissions` instead).
    - resources=[...]: also verify read access to those resources, raising ShopifyPermissionError
      naming any whose scope is missing.
    """
    store_id = normalize_store_id(shopify_store_id)
    api_url, sess = _authenticated_session(store_id, shopify_client_id, shopify_client_secret)

    # A valid token can always read the shop resource.
    try:
        res = sess.post(api_url, json={"query": SHOPIFY_ACCESS_TOKEN_CHECK})
        res.raise_for_status()
        data = res.json()
        if "errors" in data:
            raise Exception(f"Failed to verify your Shopify credentials: {data['errors']}")
    except Exception as e:
        raise Exception(f"Failed to verify your Shopify credentials: {e}")

    if resources is None:
        return True

    missing_permissions: dict[str, str] = {}
    for name in resources:
        resource = SHOPIFY_GRAPHQL_OBJECTS.get(resolve_schema_name(name))
        if resource is None:
            continue
        error = _probe_resource_permission(api_url, sess, resource)
        if error is not None:
            missing_permissions[name] = error
    if missing_permissions:
        raise ShopifyPermissionError(missing_permissions)
    return True


def check_endpoint_permissions(
    shopify_store_id: str, shopify_client_id: str, shopify_client_secret: str, endpoints: list[str]
) -> dict[str, str | None]:
    """Per-endpoint read-scope probe for the schema picker: {name: None} if reachable, else a
    message naming the missing scope. A throttle/5xx/transport blip on one endpoint leaves that
    table unknown rather than aborting the batch; only failing to obtain the access token raises."""
    store_id = normalize_store_id(shopify_store_id)
    api_url, sess = _authenticated_session(store_id, shopify_client_id, shopify_client_secret)
    results: dict[str, str | None] = {}
    for name in endpoints:
        resource = SHOPIFY_GRAPHQL_OBJECTS.get(resolve_schema_name(name))
        if resource is None:
            results[name] = None
            continue
        try:
            error = _probe_resource_permission(api_url, sess, resource)
        except (ShopifyRetryableError, requests.RequestException):
            # A throttle/5xx/transport blip on one endpoint isn't a permission verdict. Leave it
            # unknown (reachable) so the rest of the batch keeps its results instead of the whole
            # probe aborting — the real scope check still runs when the user adds that schema.
            error = None
        results[name] = missing_permissions_message({name: error}) if error is not None else None
    return results
