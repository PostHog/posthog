import os
import re
import dataclasses
from collections.abc import Callable, Mapping
from typing import Any, Literal, Optional, Union, cast, get_args, get_type_hints

import orjson
import stripe as stripe_lib
import pyarrow as pa
import requests
from asgiref.sync import async_to_sync
from stripe import ListObject, RequestsClient, StripeClient
from stripe._base_address import BaseAddresses
from stripe._webhook_endpoint_service import WebhookEndpointService
from structlog.types import FilteringBoundLogger

from posthog.temporal.common.logger import get_logger

from products.warehouse_sources.backend.models.external_table_definitions import get_dlt_mapping_for_external_table
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookCreationResult,
    WebhookDeletionResult,
    WebhookSyncResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.constants import (
    ACCOUNT_RESOURCE_NAME,
    BALANCE_TRANSACTION_RESOURCE_NAME,
    CHARGE_RESOURCE_NAME,
    COUPON_RESOURCE_NAME,
    CREDIT_NOTE_RESOURCE_NAME,
    CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME,
    CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    DISPUTE_RESOURCE_NAME,
    INVOICE_ITEM_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME,
    PAYOUT_RESOURCE_NAME,
    PRICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    REFUND_RESOURCE_NAME,
    RESOURCE_TO_STRIPE_WEBHOOK_EVENT,
    SUBSCRIPTION_RESOURCE_NAME,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.custom import InvoiceListWithAllLines
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.settings import (
    APPEND_ONLY_INCREMENTAL_FIELDS,
    WEBHOOK_ONLY_ENDPOINTS,
)

LOGGER = get_logger(__name__)
DEFAULT_LIMIT = 100
# Subscriptions are fetched with two levels of `expand` (subscription discounts and per-line-item
# discounts), so each object is far larger than a typical Stripe resource. A full page of 100 such
# objects can grow past the size that reliably transfers intact, and the response then arrives
# truncated mid-stream — the SDK only discovers the bad body while JSON-decoding it, after its retry
# loop, and re-fetching the identical oversized page just truncates again. A smaller page keeps each
# response well within transferable size; _is_truncated_stripe_list_response stays as a backstop for
# genuinely transient cuts.
SUBSCRIPTION_PAGE_LIMIT = 20

# Small write batch so each chunk (and its durable `earliest` watermark) commits well inside the heartbeat window, letting a large backfill make progress every attempt.
STRIPE_CHUNK_SIZE = 1000

_JSON_WHITESPACE = frozenset(b" \t\n\r\f\v")
_OPEN_BRACE = ord("{")
_CLOSE_BRACE = ord("}")


def _is_retryable_connection_reset(error: stripe_lib.APIConnectionError) -> bool:
    """A connection reset *mid-response* surfaces from ``requests`` as a ``ChunkedEncodingError``
    (the body stream broke after the headers arrived). Stripe's ``_handle_request_error`` only
    flags ``Timeout`` and ``ConnectionError`` as retryable, so it wraps this in an
    ``APIConnectionError`` with ``should_retry=False`` and the SDK gives up — the error then
    propagates straight out of ``auto_paging_iter`` and fails the whole import. The reset is
    transient and our reads are idempotent list/GET calls, so it is safe to retry within the SDK's
    bounded backoff. Matching ``ChunkedEncodingError`` (not ``SSLError`` or other
    ``RequestException``\\ s the SDK also declines) keeps this scoped to the mid-stream drop."""
    return isinstance(error.__cause__, requests.exceptions.ChunkedEncodingError)


def _is_truncated_stripe_list_response(body: Any) -> bool:
    """True when ``body`` is a Stripe ``list`` response cut off before its closing brace.

    A complete Stripe JSON response always ends in ``}``. A list body that opens but never closes
    is a mid-stream truncation — a proxy or connection drop that still returned a 2xx with a
    short body. Stripe only notices while decoding it (in ``_interpret_response``, after the SDK's
    network-retry loop), where it raises ``APIError: Invalid response body from API`` straight out
    of ``get_rows``/``auto_paging_iter`` and fails the whole import.

    Scoped to list responses — every bulk read we make is an idempotent ``.list()`` call — so the
    retry never re-issues a non-idempotent webhook write, whose responses are single objects.
    """
    if isinstance(body, str):
        raw: bytes = body.encode("utf-8", "ignore")
    elif isinstance(body, bytes):
        raw = body
    else:
        return False
    # `_should_retry` runs on every successful list page during a sync, so we scan for the first
    # and last non-whitespace bytes in place rather than `raw.strip()`-ing a full-body copy.
    start = 0
    end = len(raw) - 1
    while start <= end and raw[start] in _JSON_WHITESPACE:
        start += 1
    while end >= start and raw[end] in _JSON_WHITESPACE:
        end -= 1
    if start > end or raw[start] != _OPEN_BRACE or raw[end] == _CLOSE_BRACE:
        return False
    head = raw[start : start + 64]
    # Match the specific `"object": "list"` field, not just the tokens "object" and "list"
    # appearing anywhere in the head — otherwise a truncated single-object response with "list"
    # in a URL or type (e.g. `"type": "list.updated"`) would be retried as if it were a list read.
    return b'"object": "list"' in head or b'"object":"list"' in head


class _RateLimitRetryingRequestsClient(RequestsClient):
    """Stripe's SDK retries 409/5xx (and whatever ``Stripe-Should-Retry`` advises) but never
    retries 429s on its own — ``_should_retry`` excludes them. A rate limit during a large sync,
    most often while ``auto_paging_iter`` lazily fetches the next page, therefore propagates
    straight out of ``get_rows`` and fails the whole import activity.

    Opt 429 into the SDK's existing ``Retry-After``-aware exponential backoff so transient rate
    limits are absorbed in-process (bounded by ``max_network_retries``) instead of crashing the
    run. We also retry a connection reset that drops the response mid-body (the SDK declines it,
    see ``_is_retryable_connection_reset``) and a 2xx whose list body was truncated mid-stream —
    Stripe surfaces the latter as a JSON decode failure (``Invalid response body from API``) only
    after the SDK's retry loop, too late for it to recover on its own. Our Stripe reads are
    list/GET calls, so retrying them is idempotent."""

    def _should_retry(
        self,
        response: Optional[tuple[Any, int, Optional[Mapping[str, str]]]],
        api_connection_error: Optional[stripe_lib.APIConnectionError],
        num_retries: int,
        max_network_retries: Optional[int],
    ) -> bool:
        if super()._should_retry(response, api_connection_error, num_retries, max_network_retries):
            return True
        # The base logic already enforced the retry budget and declined; the cases it leaves on the
        # table are a 429 (the SDK omits it), a 2xx with a truncated list body (the SDK only fails
        # on it later, while parsing), and a connection reset that drops the response mid-body —
        # all safe to retry on our idempotent list/GET calls.
        if num_retries >= (max_network_retries or 0):
            return False
        if response is None:
            return api_connection_error is not None and _is_retryable_connection_reset(api_connection_error)
        body, status_code, _ = response
        if status_code == 429:
            return True
        return 200 <= status_code < 300 and _is_truncated_stripe_list_response(body)


def _tracked_stripe_http_client() -> RequestsClient:
    """Wrap a tracked `requests.Session` in Stripe's `RequestsClient` so every
    Stripe SDK call participates in our HTTP logging, metrics, and sample capture.

    Uses a subclass that additionally retries 429 rate limits and truncated list responses via the
    SDK's built-in backoff."""
    return _RateLimitRetryingRequestsClient(session=make_tracked_session())


def _clean_stripe_error_message(msg: str) -> str:
    """Collapse the long redacted middle of a restricted API key ('rk_live_********...****gbeftZ')
    so the error message stays short enough to render in a frontend toast. The prefix and
    suffix Stripe leaves visible are enough to identify the key in support escalations."""
    # Stripe redacts ~80 chars with `*`. Anything 5+ in a row is the redaction, never legitimate.
    return re.sub(r"\*{5,}", "***", msg)


def _call_stripe(method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Invoke a Stripe SDK list method and rewrite any StripeError it raises with a cleaned
    message — primarily collapsing the long asterisk run from redacted restricted keys.

    Re-raises the same exception instance (so framework-level non-retryable error matching on
    `"PermissionError"` etc. continues to work) but with a shorter, frontend-friendly message
    that still preserves the actionable detail Stripe surfaces (which scope is missing).

    The message is mutated in place rather than reconstructed: StripeError subclasses have
    differing constructor signatures (e.g. InvalidRequestError requires a positional `param`),
    so `type(e)(message=...)` would itself raise a TypeError and mask the original error.
    """
    try:
        return method(*args, **kwargs)
    except stripe_lib.StripeError as e:
        cleaned = _clean_stripe_error_message(e._message or "")
        e._message = cleaned
        e.args = (cleaned,)
        raise


def _is_stripe_resource_missing_error(error: stripe_lib.StripeError) -> bool:
    """True for Stripe's ``resource_missing`` 404 — e.g. a customer deleted between when we
    listed it and when we fetched its nested resources. The object is genuinely gone, so the
    caller can skip it instead of failing the whole sync."""
    return getattr(error, "code", None) == "resource_missing"


def _coerce_incremental_cursor(value: Any) -> Optional[int]:
    """Coerce a stored incremental watermark to the Unix-timestamp int that Stripe object
    `created`/`date` fields are. The persisted watermark can come back as a numeric string, so
    comparing it directly against the int field raises `'<=' not supported between instances of
    'int' and 'str'`. Returns None when the value can't be read as an int, so the caller skips
    the cursor comparison rather than crashing."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _stripe_base_addresses() -> BaseAddresses:
    # Redirect Stripe API calls to a local mock (e.g. STRIPE_API_BASE=http://localhost:12111)
    # when running the stripe-mock dev service. No-op in production where the var is unset.
    base = os.environ.get("STRIPE_API_BASE")
    return BaseAddresses(api=base) if base else BaseAddresses()


@dataclasses.dataclass
class StripeResource:
    method: Callable[..., ListObject[Any]]
    params: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class StripeNestedResource:
    method: Callable[..., ListObject[Any]]
    nested_parent_param: str
    parent_id: str
    parent: StripeResource
    parent_name: str = ""
    params: dict[str, Any] = dataclasses.field(default_factory=dict)
    # Optional predicate over a parent object. When set and it returns False, we skip the nested
    # API call for that parent entirely. Stripe has no top-level list for these nested resources, so
    # the default behaviour fans out one call per parent — most of which return nothing. A cheap
    # signal already present on the parent object lets us avoid the calls that can't yield data.
    parent_has_nested: Optional[Callable[[dict[str, Any]], bool]] = None


def _customer_might_have_balance_transactions(customer: dict[str, Any]) -> bool:
    """Skip the per-customer balance-transactions call when the customer's credit balance is exactly 0.

    A customer balance transaction is a credit/debit against the customer's stored balance, so any
    customer that has ever had one and not netted it back to zero carries a non-zero ``balance``. The
    vast majority of customers never touch their balance, so this turns the full per-customer sweep
    (one call each, almost all empty) into a handful of calls.

    Tradeoff: a customer whose balance was credited and then fully consumed back to 0 has ledger
    entries but a 0 balance, so we won't fetch their history. This is rare and an accepted cost of
    avoiding the per-customer fan-out. A missing ``balance`` (unexpected payload shape) is treated as
    "might have" so we never silently drop data."""
    balance = customer.get("balance")
    return balance is None or balance != 0


@dataclasses.dataclass
class StripeResumeConfig:
    starting_after: str


def _batch_and_yield(
    objects: Any,
    batcher: Batcher,
    incremental_field_name: Optional[str] = None,
    stop_at_or_before: Optional[int] = None,
):
    """Batch raw Stripe objects into pa.Tables and yield them, stopping early once we reach an object
    we already have (`stop_at_or_before`). Yielding in small batches lets the pipeline write and
    persist the incremental watermark frequently, so progress survives a heartbeat timeout or redeploy."""
    for obj in objects:
        if stop_at_or_before is not None and incremental_field_name is not None:
            if obj[incremental_field_name] <= stop_at_or_before:
                break
        batcher.batch(obj)
        while batcher.should_yield():
            yield batcher.get_table()

    while batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def _build_resources(
    client: StripeClient, logger: Optional[FilteringBoundLogger] = None
) -> dict[str, Union[StripeResource, StripeNestedResource]]:
    """Single source of truth for the resources we sync from Stripe and how they relate.

    Used by both get_rows (for the actual sync) and validate_credentials (for permission
    checks). Nested resources carry their parent on `.parent`, so callers can derive the
    nested→parent linkage without restating it elsewhere.

    `logger` is only consumed by InvoiceListWithAllLines; pass None when the caller doesn't
    need the wrapped invoice expansion (e.g. validation, which just probes the list endpoint).
    """
    return {
        ACCOUNT_RESOURCE_NAME: StripeResource(method=client.accounts.list),
        BALANCE_TRANSACTION_RESOURCE_NAME: StripeResource(method=client.balance_transactions.list),
        CHARGE_RESOURCE_NAME: StripeResource(method=client.charges.list),
        CUSTOMER_RESOURCE_NAME: StripeResource(method=client.customers.list),
        DISPUTE_RESOURCE_NAME: StripeResource(method=client.disputes.list),
        INVOICE_ITEM_RESOURCE_NAME: StripeResource(method=client.invoice_items.list),
        INVOICE_RESOURCE_NAME: StripeResource(
            method=(
                (lambda params: InvoiceListWithAllLines(client, params, logger))  # type: ignore
                if logger is not None
                else client.invoices.list
            )
        ),
        PAYOUT_RESOURCE_NAME: StripeResource(method=client.payouts.list),
        PRICE_RESOURCE_NAME: StripeResource(method=client.prices.list, params={"expand[]": "data.tiers"}),
        PRODUCT_RESOURCE_NAME: StripeResource(method=client.products.list),
        REFUND_RESOURCE_NAME: StripeResource(method=client.refunds.list),
        SUBSCRIPTION_RESOURCE_NAME: StripeResource(
            method=client.subscriptions.list,
            params={
                "status": "all",
                # Smaller page than DEFAULT_LIMIT because the expansions below bloat each object; see
                # SUBSCRIPTION_PAGE_LIMIT. Overrides the default `limit` in the merged params.
                "limit": SUBSCRIPTION_PAGE_LIMIT,
                # Expand discount objects so coupon details (amount_off, percent_off, duration) are inline.
                # Without expansion Stripe returns only discount IDs, which prevents revenue projection.
                # Key must be "expand" (not "expand[]") for a list value: the SDK encodes it as
                # expand[0]=…&expand[1]=…, whereas "expand[]" + a list yields expand[][0]=… (doubled
                # brackets), which Stripe rejects with "Invalid string: {...}".
                "expand": ["data.discounts", "data.items.data.discounts"],
            },
        ),
        CREDIT_NOTE_RESOURCE_NAME: StripeResource(method=client.credit_notes.list),
        COUPON_RESOURCE_NAME: StripeResource(method=client.coupons.list),
        CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME: StripeNestedResource(
            method=client.customers.balance_transactions.list,
            nested_parent_param="customer",
            parent_id="id",
            parent=StripeResource(method=client.customers.list),
            parent_name=CUSTOMER_RESOURCE_NAME,
            parent_has_nested=_customer_might_have_balance_transactions,
        ),
        CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME: StripeNestedResource(
            method=client.customers.payment_methods.list,
            nested_parent_param="customer",
            parent_id="id",
            parent=StripeResource(method=client.customers.list),
            parent_name=CUSTOMER_RESOURCE_NAME,
        ),
    }


def get_rows(
    api_key: str,
    endpoint: str,
    account_id: Optional[str],
    db_incremental_field_last_value: Optional[Any],
    db_incremental_field_earliest_value: Optional[Any],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[StripeResumeConfig],
    should_use_incremental_field: bool = False,
):
    client = StripeClient(
        api_key,
        stripe_account=account_id,
        stripe_version="2024-09-30.acacia",
        max_network_retries=2,
        base_addresses=_stripe_base_addresses(),
        http_client=_tracked_stripe_http_client(),
    )
    default_params = {"limit": DEFAULT_LIMIT}
    resources = _build_resources(client, logger=logger)

    batcher = Batcher(logger=logger, chunk_size=STRIPE_CHUNK_SIZE)

    if endpoint in WEBHOOK_ONLY_ENDPOINTS:
        # Webhook-only resources (e.g. Discount) have no Stripe list endpoint — Discount
        # can only be retrieved in the context of a customer/subscription/invoice. These
        # tables are populated exclusively by their corresponding webhook events. Yield
        # nothing so the initial "sync" completes immediately, allowing the webhook source
        # manager to take over (it requires schema.initial_sync_complete=True before activating).
        logger.debug(f"Stripe: {endpoint} endpoint is webhook-only, skipping API list")
        return

    resource = resources.get(endpoint, None)
    if not resource:
        raise Exception(f"Stripe endpoint does not exist: {endpoint}")

    logger.debug(f"Stripe: reading from resource {resource}")

    # Get the incremental field name for this endpoint
    incremental_field_config = APPEND_ONLY_INCREMENTAL_FIELDS.get(endpoint, [])
    incremental_field_name = incremental_field_config[0]["field"] if incremental_field_config else "created"

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if (
        not should_use_incremental_field
        or (db_incremental_field_last_value is None and db_incremental_field_earliest_value is None)
        or isinstance(resource, StripeNestedResource)
    ):
        logger.debug(f"Stripe: iterating all objects from resource")
        resume_params = {}
        if resume_config is not None:
            resume_params = {"starting_after": resume_config.starting_after}
            logger.debug(f"Stripe: resuming from object id: {resume_config.starting_after}")

        if isinstance(resource, StripeNestedResource):
            stripe_parent_objects = _call_stripe(
                resource.parent.method,
                params={**default_params, **resource.parent.params, **resume_params},
            )
            skipped_parents = 0
            for obj in stripe_parent_objects.auto_paging_iter():
                parent_obj_id = obj[resource.parent_id]
                # Skip parents that a cheap signal on the parent object rules out — avoids one empty
                # nested call per parent (the bulk of Stripe API volume for these resources).
                if resource.parent_has_nested is not None and not resource.parent_has_nested(obj):
                    skipped_parents += 1
                    continue
                try:
                    stripe_nested_objects = _call_stripe(
                        resource.method,
                        **{resource.nested_parent_param: parent_obj_id},
                        params={**default_params, **resource.params},
                    )
                    for nested_obj in stripe_nested_objects.auto_paging_iter():
                        batcher.batch(
                            {
                                **nested_obj,
                                **{resource.nested_parent_param: parent_obj_id},
                            }
                        )

                        # A single batch can split into several ready chunks, so drain them all
                        # before batching the next item — otherwise the next batch() trips the
                        # "table already ready" guard.
                        while batcher.should_yield():
                            py_table = batcher.get_table()
                            yield py_table

                            last_cur = py_table.column(resource.nested_parent_param)[-1].as_py()
                            resumable_source_manager.save_state(StripeResumeConfig(starting_after=last_cur))
                except stripe_lib.InvalidRequestError as e:
                    # The parent was deleted between listing it and fetching its nested resources,
                    # so Stripe 404s the nested call. Skip the now-gone parent and keep syncing the
                    # rest rather than failing the whole import.
                    if not _is_stripe_resource_missing_error(e):
                        raise
                    logger.debug(f"Stripe: skipping {resource.nested_parent_param}={parent_obj_id}, no longer exists")
            if skipped_parents:
                logger.debug(
                    f"Stripe: skipped {skipped_parents} {resource.nested_parent_param}(s) with no nested data, saving that many API calls"
                )
        else:
            stripe_objects = _call_stripe(
                resource.method, params={**default_params, **resource.params, **resume_params}
            )
            for obj in stripe_objects.auto_paging_iter():
                batcher.batch(obj)

                while batcher.should_yield():
                    py_table = batcher.get_table()
                    yield py_table

                    last_cur = py_table.column("id")[-1].as_py()
                    resumable_source_manager.save_state(StripeResumeConfig(starting_after=last_cur))

        while batcher.should_yield(include_incomplete_chunk=True):
            py_table = batcher.get_table()
            yield py_table

            if isinstance(resource, StripeNestedResource):
                last_cur = py_table.column(resource.nested_parent_param)[-1].as_py()
            else:
                last_cur = py_table.column("id")[-1].as_py()

            resumable_source_manager.save_state(StripeResumeConfig(starting_after=last_cur))

        return

    # check for any objects less than the minimum object we already have
    if db_incremental_field_earliest_value is not None:
        logger.debug(
            f"Stripe: iterating earliest objects from resource: created[lt] = {db_incremental_field_earliest_value}"
        )

        stripe_objects = _call_stripe(
            resource.method,
            params={
                **default_params,
                **resource.params,
                f"created[lt]": db_incremental_field_earliest_value,
            },
        )
        yield from _batch_and_yield(stripe_objects.auto_paging_iter(), batcher)

    # check for any objects more than the maximum object we already have
    if db_incremental_field_last_value is not None:
        logger.debug(f"Stripe: iterating latest objects from resource: created[gt] = {db_incremental_field_last_value}")

        stripe_objects = _call_stripe(
            resource.method,
            params={
                **default_params,
                **resource.params,
                f"created[gt]": db_incremental_field_last_value,
            },
        )
        yield from _batch_and_yield(
            stripe_objects.auto_paging_iter(),
            batcher,
            incremental_field_name=incremental_field_name,
            stop_at_or_before=_coerce_incremental_cursor(db_incremental_field_last_value),
        )


def _webhook_table_transformer(table: pa.Table) -> pa.Table:
    data_col = table.column("data").to_pylist()
    created_col = table.column("created").to_pylist()

    # Deduplicate by object id, keeping the event with the latest created timestamp.
    # Multiple webhook events (e.g. customer.created then customer.updated) can reference
    # the same object, and delta merge doesn't deduplicate within the source batch.
    best_by_id: dict[str, tuple[int, dict]] = {}
    for data_str, event_created in zip(data_col, created_col):
        if data_str is None:
            continue
        obj = orjson.loads(data_str)["object"]
        obj_id = obj.get("id")
        if obj_id is None:
            continue

        ts = event_created if isinstance(event_created, int) else 0
        existing = best_by_id.get(obj_id)
        if existing is None or ts > existing[0]:
            best_by_id[obj_id] = (ts, obj)

    rows = [obj for _, obj in best_by_id.values()]
    return table_from_py_list(rows)


def stripe_source(
    api_key: str,
    account_id: Optional[str],
    endpoint: str,
    db_incremental_field_last_value: Optional[Any],
    db_incremental_field_earliest_value: Optional[Any],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[StripeResumeConfig],
    webhook_source_manager: WebhookSourceManager,
    should_use_incremental_field: bool = False,
):
    column_mapping = get_dlt_mapping_for_external_table(f"stripe_{endpoint.lower()}")
    column_hints = {key: value.get("data_type") for key, value in column_mapping.items()}

    # Get the incremental field name for partition keys
    incremental_field_config = APPEND_ONLY_INCREMENTAL_FIELDS.get(endpoint, [])
    incremental_field_name = incremental_field_config[0]["field"] if incremental_field_config else "created"

    webhook_enabled = async_to_sync(webhook_source_manager.webhook_enabled)()

    def items():
        if webhook_enabled:
            return webhook_source_manager.get_items(table_transformer=_webhook_table_transformer)

        return get_rows(
            api_key=api_key,
            account_id=account_id,
            endpoint=endpoint,
            db_incremental_field_last_value=db_incremental_field_last_value,
            db_incremental_field_earliest_value=db_incremental_field_earliest_value,
            logger=logger,
            should_use_incremental_field=should_use_incremental_field,
            resumable_source_manager=resumable_source_manager,
        )

    return SourceResponse(
        items=items,
        primary_keys=["id"],
        name=endpoint,
        column_hints=column_hints,
        # Stripe data is returned in descending timestamp order
        sort_mode="desc",
        partition_count=1,  # this enables partitioning
        partition_size=1,  # this enables partitioning
        partition_mode="datetime",
        partition_format="week",
        partition_keys=[incremental_field_name],
    )


class StripePermissionError(Exception):
    """Raised when Stripe API key is valid but lacks read permission for one or more resources (403)."""

    def __init__(self, missing_permissions: dict[str, str]):
        self.missing_permissions = missing_permissions
        message = f"Stripe API key lacks permissions for: {', '.join(missing_permissions.keys())}"
        super().__init__(message)


class StripeAuthenticationError(Exception):
    """Raised when Stripe API key itself is invalid (401) — distinct from per-resource permission denial."""

    def __init__(self, stripe_message: str):
        self.stripe_message = stripe_message
        super().__init__(stripe_message)


class StripeValidationError(Exception):
    """Raised when one or more resources failed with a non-403 exception (network, schema, rate
    limit, etc.) during credential validation. Distinct from StripePermissionError so callers can
    decide whether to surface the verbose underlying message — permission errors are
    self-explanatory from the resource name, but unknown errors need the raw detail."""

    def __init__(self, errors: dict[str, str], missing_permissions: Optional[dict[str, str]] = None):
        self.errors = errors
        # If we also collected legitimate 403s before hitting the unknown error, keep them on the
        # exception so callers can report both classes of failure in a single message.
        self.missing_permissions = missing_permissions or {}
        message = f"Stripe validation failed for: {', '.join(errors.keys())}"
        super().__init__(message)


def _resolve_to_flat(
    name: str, all_resources: dict[str, Union[StripeResource, StripeNestedResource]]
) -> tuple[str, StripeResource]:
    """Nested resources display as `<nested> (<parent>)` and probe the parent endpoint."""
    entry = all_resources[name]
    if isinstance(entry, StripeNestedResource):
        # Parent_name registration enforced by test_validate_credentials_nested_resources_have_registered_parents.
        parent_entry = cast(StripeResource, all_resources[entry.parent_name])
        return f"{name} ({entry.parent_name})", parent_entry
    return name, entry


def _probe_endpoint(resource: StripeResource) -> tuple[str | None, str | None]:
    """Cheap limit=1 probe. Returns ``(permission_msg, error_msg)``. 401 raises ``StripeAuthenticationError``.

    Exactly one tuple slot is set on failure; both ``None`` means success.
    """
    try:
        resource.method(params={"limit": 1})
        return None, None
    except stripe_lib.AuthenticationError as e:
        raise StripeAuthenticationError(_clean_stripe_error_message(str(e))) from e
    except stripe_lib.PermissionError as e:
        raw = getattr(e, "user_message", None) or str(e)
        return _clean_stripe_error_message(raw), None
    except Exception as e:
        return None, _clean_stripe_error_message(str(e))


# customers.list is in default RAK scopes + OAuth-reachable — cheap auth probe.
_BASIC_AUTH_PROBE_ENDPOINT = CUSTOMER_RESOURCE_NAME


def validate_credentials(
    api_key: str,
    endpoints: Optional[list[str]] = None,
    auth_method: Literal["api_key", "oauth"] = "api_key",
) -> bool:
    """Validate Stripe credentials.

    - ``endpoints=None``: single auth probe. 401 → ``StripeAuthenticationError``, 403 → pass.
    - ``endpoints=[...]``: probe each (nested → parent). Raises Permission/Validation errors.
    """
    client = StripeClient(api_key, base_addresses=_stripe_base_addresses(), http_client=_tracked_stripe_http_client())
    all_resources = _build_resources(client, logger=None)

    if endpoints is None:
        probe_name, probe_resource = _resolve_to_flat(_BASIC_AUTH_PROBE_ENDPOINT, all_resources)
        # 403 = auth valid, scope missing — not a failure for the basic check.
        _, error_msg = _probe_endpoint(probe_resource)
        if error_msg is not None:
            raise StripeValidationError({probe_name: error_msg})
        return True

    missing_permissions: dict[str, str] = {}
    errors: dict[str, str] = {}
    resources_to_check: list[tuple[str, StripeResource]] = []

    for name in endpoints:
        # OAuth tokens can't call accounts.list (needs Connect platform access). Silent-skip here
        # because this is a pass/fail validation; check_endpoint_permissions renders an explicit
        # "not available for OAuth" reason instead since it feeds the UI.
        if auth_method == "oauth" and name == ACCOUNT_RESOURCE_NAME:
            continue
        # Webhook-only resources (e.g. Discount) have no list API to probe.
        if name in WEBHOOK_ONLY_ENDPOINTS:
            continue
        if name not in all_resources:
            raise StripePermissionError({name: f"{name} does not exist"})
        resources_to_check.append(_resolve_to_flat(name, all_resources))

    for display_name, resource in resources_to_check:
        permission_msg, error_msg = _probe_endpoint(resource)
        if permission_msg is not None:
            missing_permissions[display_name] = permission_msg
        elif error_msg is not None:
            errors[display_name] = error_msg

    # Non-403 errors win but carry 403s along so the caller can report both.
    if errors:
        raise StripeValidationError(errors, missing_permissions=missing_permissions)
    if missing_permissions:
        raise StripePermissionError(missing_permissions)

    return True


def check_endpoint_permissions(
    api_key: str,
    endpoints: list[str],
    auth_method: Literal["api_key", "oauth"] = "api_key",
) -> dict[str, str | None]:
    """Probe each endpoint's read scope. Returns ``{name: None}`` if reachable, ``{name: reason}`` otherwise.

    Never raises for missing permissions (schema UI needs the full picture). 401 still raises.
    """
    client = StripeClient(api_key, base_addresses=_stripe_base_addresses(), http_client=_tracked_stripe_http_client())
    all_resources = _build_resources(client, logger=None)

    results: dict[str, str | None] = {}
    for name in endpoints:
        if auth_method == "oauth" and name == ACCOUNT_RESOURCE_NAME:
            results[name] = "Account is not available for OAuth-connected Stripe sources"
            continue
        # Webhook-only resources (e.g. Discount) have no list API — treat as reachable.
        if name in WEBHOOK_ONLY_ENDPOINTS:
            results[name] = None
            continue
        if name not in all_resources:
            results[name] = f"{name} is not a known Stripe resource"
            continue

        _, probe_resource = _resolve_to_flat(name, all_resources)
        permission_msg, error_msg = _probe_endpoint(probe_resource)
        results[name] = permission_msg or error_msg

    return results


def _all_known_webhook_events() -> list[str]:
    """Every Stripe event whose prefix appears in RESOURCE_TO_STRIPE_WEBHOOK_EVENT.
    Re-deriving on each reconcile is what auto-heals webhooks created before the map grew."""
    hints = get_type_hints(WebhookEndpointService.CreateParams, include_extras=True)
    enabled_events_type = hints["enabled_events"]
    list_inner = get_args(enabled_events_type)[0]
    possible_event_values: tuple[str] = get_args(list_inner)

    prefixes_set = set(RESOURCE_TO_STRIPE_WEBHOOK_EVENT.values())
    return [e for e in possible_event_values if any(e.startswith(f"{p}.") for p in prefixes_set)]


def _is_stripe_account_access_error(error: Exception, error_str: str) -> bool:
    """Detect Stripe's account-access/account-mismatch rejection (code ``account_invalid``).

    A restricted key sent with a ``stripe_account`` header that doesn't match the key's own
    account makes Stripe reject the request for the account rather than the webhook scope, so it
    never matches the permission/403/forbidden branch. Surfacing the raw message strands the user;
    classifying it lets us point them at the manual-setup fallback instead.
    """
    if getattr(error, "code", None) == "account_invalid":
        return True
    lowered = error_str.lower()
    return (
        "does not have access to account" in lowered
        or "application access may have been revoked" in lowered
        or "no such account" in lowered
    )


def create_webhook(api_key: str, stripe_account_id: str | None, webhook_url: str) -> WebhookCreationResult:
    logger = LOGGER.bind()

    filtered_events = _all_known_webhook_events()

    if not filtered_events:
        return WebhookCreationResult(
            success=False,
            error="Could not determine valid webhook events. Please create the webhook manually.",
        )

    try:
        client = StripeClient(
            api_key,
            stripe_account=stripe_account_id,
            stripe_version="2024-09-30.acacia",
            max_network_retries=2,
            base_addresses=_stripe_base_addresses(),
            http_client=_tracked_stripe_http_client(),
        )

        endpoint = client.webhook_endpoints.create(
            params={
                "url": webhook_url,
                "enabled_events": filtered_events,  # type: ignore
                "description": "PostHog data warehouse webhook",
            }
        )

        extra_inputs: dict[str, Any] = {}
        if endpoint.secret:
            extra_inputs["signing_secret"] = endpoint.secret

        return WebhookCreationResult(success=True, extra_inputs=extra_inputs)
    except Exception as e:
        error_str = _clean_stripe_error_message(str(e))
        logger.warning(
            "Failed to create Stripe webhook",
            error=error_str,
        )

        # Check account access before the permission branch — an account-access rejection can carry a
        # 403 and would otherwise be misclassified as a missing webhook scope.
        if _is_stripe_account_access_error(e, error_str):
            return WebhookCreationResult(
                success=False,
                error=(
                    "Stripe rejected the request because your API key isn't authorized for the configured "
                    "Stripe account. The 'Account id' in your source settings only applies to Stripe Connect "
                    "platform accounts — remove or correct it if your key belongs directly to the account, "
                    "then retry. Otherwise, set up the webhook manually below."
                ),
            )

        if "permission" in error_str.lower() or "403" in error_str or "forbidden" in error_str.lower():
            return WebhookCreationResult(
                success=False,
                error="Your Stripe API key doesn't have permission to create webhooks. Please add the 'Write' permission for 'Webhook endpoints' to your API key, or create the webhook manually.",
            )

        return WebhookCreationResult(success=False, error=f"Failed to create webhook automatically: {error_str}")


def delete_webhook(api_key: str, stripe_account_id: str | None, webhook_url: str) -> WebhookDeletionResult:
    logger = LOGGER.bind()

    try:
        client = StripeClient(
            api_key,
            stripe_account=stripe_account_id,
            stripe_version="2024-09-30.acacia",
            max_network_retries=2,
            base_addresses=_stripe_base_addresses(),
            http_client=_tracked_stripe_http_client(),
        )

        endpoints = client.webhook_endpoints.list(params={"limit": 100})

        for endpoint in endpoints.auto_paging_iter():
            if endpoint.url == webhook_url:
                client.webhook_endpoints.delete(endpoint.id)
                return WebhookDeletionResult(success=True)

        return WebhookDeletionResult(success=True)
    except Exception as e:
        error_str = str(e)
        logger.warning(
            "Failed to delete Stripe webhook",
            error=error_str,
        )

        if "permission" in error_str.lower() or "403" in error_str or "forbidden" in error_str.lower():
            return WebhookDeletionResult(
                success=False,
                error="Your Stripe API key doesn't have permission to delete webhooks. Please delete the webhook manually from your Stripe dashboard.",
            )

        return WebhookDeletionResult(success=False, error=f"Failed to delete webhook: {error_str}")


def update_webhook_events(
    api_key: str, stripe_account_id: str | None, webhook_url: str, desired_events: list[str]
) -> WebhookSyncResult:
    """Add `desired_events` to the matching Stripe endpoint, writing only on drift.
    A 403 (missing webhook write scope) returns a failure result rather than raising, so
    callers can enable the table and warn instead of hard-failing."""
    logger = LOGGER.bind()

    if not desired_events:
        return WebhookSyncResult(success=True)

    try:
        client = StripeClient(
            api_key,
            stripe_account=stripe_account_id,
            stripe_version="2024-09-30.acacia",
            max_network_retries=2,
            base_addresses=_stripe_base_addresses(),
            http_client=_tracked_stripe_http_client(),
        )

        endpoints = client.webhook_endpoints.list(params={"limit": 100})

        for endpoint in endpoints.auto_paging_iter():
            if endpoint.url != webhook_url:
                continue

            current = set(endpoint.enabled_events or [])
            # "*" already covers everything.
            if "*" in current:
                return WebhookSyncResult(success=True)

            missing = [e for e in desired_events if e not in current]
            if not missing:
                return WebhookSyncResult(success=True)

            # Merge, don't replace — never drop events the user added themselves.
            merged = sorted(current | set(desired_events))
            client.webhook_endpoints.update(endpoint.id, params={"enabled_events": merged})  # type: ignore
            return WebhookSyncResult(success=True)

        # No matching endpoint — nothing to reconcile (creation is handled elsewhere).
        return WebhookSyncResult(success=True)
    except stripe_lib.PermissionError as e:
        logger.warning("No permission to update Stripe webhook events", error=str(e))
        return WebhookSyncResult(
            success=False,
            error=(
                "Your Stripe API key doesn't have permission to update webhooks. Add the 'Write' permission "
                f"for 'Webhook endpoints' to your API key, or add these events manually: {', '.join(desired_events)}"
            ),
        )
    except Exception as e:
        error_str = _clean_stripe_error_message(str(e))
        logger.warning("Failed to update Stripe webhook events", error=error_str)
        return WebhookSyncResult(success=False, error=f"Failed to update webhook events automatically: {error_str}")


def get_external_webhook_info(api_key: str, stripe_account_id: str | None, webhook_url: str) -> ExternalWebhookInfo:
    try:
        client = StripeClient(
            api_key,
            stripe_account=stripe_account_id,
            stripe_version="2024-09-30.acacia",
            max_network_retries=2,
            base_addresses=_stripe_base_addresses(),
            http_client=_tracked_stripe_http_client(),
        )

        endpoints = client.webhook_endpoints.list(params={"limit": 100})

        for endpoint in endpoints.auto_paging_iter():
            if endpoint.url == webhook_url:
                return ExternalWebhookInfo(
                    exists=True,
                    url=endpoint.url,
                    enabled_events=endpoint.enabled_events,
                    status=endpoint.status,
                    description=endpoint.description,
                    created_at=str(endpoint.created) if endpoint.created else None,
                )

        return ExternalWebhookInfo(exists=False)
    except Exception as e:
        error_str = str(e)
        if "permission" in error_str.lower() or "403" in error_str or "forbidden" in error_str.lower():
            return ExternalWebhookInfo(
                exists=False,
                error="Your Stripe API key doesn't have permission to read webhooks. Add the 'Read' permission for 'Webhook endpoints' to your API key.",
            )
        return ExternalWebhookInfo(exists=False, error=f"Failed to check webhook status: {error_str}")
