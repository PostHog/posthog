import json
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode, urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.zapier_supported_storage.settings import (
    ZAPIER_SUPPORTED_STORAGE_ENDPOINTS,
)

# The host is fixed (Storage by Zapier is a single global service). Only the per-store `secret`
# varies, and it is sent as a header, so there is no host to interpolate and no SSRF surface.
ZAPIER_SUPPORTED_STORAGE_URL = "https://store.zapier.com/api/records"


class ZapierSupportedStorageRetryableError(Exception):
    pass


def _headers(secret: str) -> dict[str, str]:
    return {"X-Secret": secret, "Accept": "application/json"}


def _stringify_value(value: Any) -> str | None:
    """Coerce a stored value to a string so the `value` column has one stable type.

    Storage by Zapier holds arbitrary JSON per key (strings, numbers, objects, arrays). Keeping the
    column a single type avoids schema-inference conflicts across rows in the Delta table; strings
    pass through unchanged and everything else is JSON-encoded. `None` is preserved so a genuinely
    null value stays null rather than becoming the literal string "null"."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)


@retry(
    retry=retry_if_exception_type(
        (ZapierSupportedStorageRetryableError, requests.ReadTimeout, requests.ConnectionError)
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_store(session: requests.Session, secret: str, logger: FilteringBoundLogger) -> dict[str, Any]:
    response = session.get(ZAPIER_SUPPORTED_STORAGE_URL, headers=_headers(secret), timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise ZapierSupportedStorageRetryableError(
            f"Storage by Zapier API error (retryable): status={response.status_code}"
        )

    if not response.ok:
        # Never log response.text: the store holds arbitrary secret values and a 4xx body can echo
        # store contents or request context, which would leak into operational logs. Log only status
        # plus scheme/host/path (the URL carries no query string here, but stay defensive).
        safe = urlsplit(response.url)
        safe_url = f"{safe.scheme}://{safe.netloc}{safe.path}"
        logger.error(f"Storage by Zapier API error: status={response.status_code}, url={safe_url}")
        # raise_for_status() would attach the full response (body included) to the exception, which is
        # surfaced as the schema's latest_error. Rebuild the error from scheme/host/path only so no
        # response body reaches stored error state. The "<status> Client Error: <reason> for url:
        # https://store.zapier.com" prefix stays stable for get_non_retryable_errors() matching.
        raise requests.HTTPError(
            f"{response.status_code} Client Error: {response.reason} for url: {safe_url}",
            response=response,
        )

    data = response.json()
    # The endpoint always returns the whole store as a flat `{key: value}` object. Treat any other
    # shape as retryable rather than an empty store: returning `{}` here would let a transient API or
    # proxy response complete a "successful" full refresh with zero rows and wipe previously synced
    # records.
    if not isinstance(data, dict):
        logger.error(f"Storage by Zapier returned an unexpected payload shape: {type(data).__name__}")
        raise ZapierSupportedStorageRetryableError(
            f"Storage by Zapier returned an unexpected payload shape: {type(data).__name__}"
        )
    return data


def get_rows(secret: str, logger: FilteringBoundLogger) -> Iterator[Any]:
    batcher = Batcher(logger=logger, chunk_size=5000, chunk_size_bytes=100 * 1024 * 1024)
    # capture=False: the entire response body is the store's arbitrary key/value contents, so HTTP
    # sample capture would serialize customer data to object storage where the name-based scrubbers
    # can't redact keys they don't recognize. Requests are still metered and logged.
    # allow_redirects=False: the `X-Secret` header is a credential and requests does not strip custom
    # headers when following cross-host redirects, so pin the credentialed request to store.zapier.com.
    session = make_tracked_session(redact_values=(secret,), capture=False, allow_redirects=False)

    # The store is fetched in a single call - there is no pagination or list endpoint.
    store = _fetch_store(session, secret, logger)
    for key, value in store.items():
        batcher.batch({"key": key, "value": _stringify_value(value)})
        if batcher.should_yield():
            yield batcher.get_table()

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def zapier_supported_storage_source(
    secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = ZAPIER_SUPPORTED_STORAGE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(secret=secret, logger=logger),
        primary_keys=config.primary_keys,
        # Full refresh only - the store exposes no timestamps to partition on.
        partition_count=1,
        partition_size=1,
    )


def validate_credentials(secret: str) -> tuple[bool, str | None]:
    """Confirm the store secret is genuine with one cheap probe.

    The secret both identifies and authorizes the store, so a single GET tells us everything:
    - 200: the secret resolves to a store (valid).
    - 400: the secret is not a valid UUID4 (Storage by Zapier rejects malformed secrets outright).
    - 401: the secret is missing or does not resolve to a store (invalid).
    """
    # capture=False for the same reason as get_rows: even a single-key probe response echoes stored
    # customer data that the name-based sample-capture scrubbers can't be trusted to redact.
    # allow_redirects=False pins the credentialed `X-Secret` request to store.zapier.com so the secret
    # can't be forwarded to a cross-host redirect target.
    session = make_tracked_session(redact_values=(secret,), capture=False, allow_redirects=False)
    # Limit the probe to a single key so we don't pull a whole store just to validate.
    url = f"{ZAPIER_SUPPORTED_STORAGE_URL}?{urlencode({'key': '__posthog_probe__'})}"
    try:
        response = session.get(url, headers=_headers(secret), timeout=10)
    except requests.RequestException as exc:
        return False, f"Could not reach Storage by Zapier: {exc}"

    if response.ok:
        return True, None
    if response.status_code == 400:
        return (
            False,
            "Your Storage by Zapier secret must be a valid UUID4. Copy the store secret exactly and reconnect.",
        )
    if response.status_code == 401:
        return False, "Your Storage by Zapier secret is invalid. Copy the store secret exactly and reconnect."
    return False, f"Storage by Zapier API returned status {response.status_code}"
