import re
from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.campayn.settings import (
    CAMPAYN_ENDPOINTS,
    CampaynEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

CAMPAYN_API_PATH = "/api/v1"
REQUEST_TIMEOUT_SECONDS = 60
# Per-account host: requests go to {subdomain}.campayn.com. The label is validated against this
# pattern at source-create so a pasted URL or injection can't retarget the credential elsewhere.
_SUBDOMAIN_PATTERN = re.compile(r"^[a-zA-Z0-9-]+$")


class CampaynRetryableError(Exception):
    pass


def normalize_subdomain(subdomain: str) -> str:
    """Reduce whatever the user entered to the bare Campayn subdomain label.

    Users frequently paste the full host ("acme.campayn.com") or a URL
    ("https://acme.campayn.com/") into the subdomain field. Collapse those to the
    bare label so the base URL doesn't become "https://acme.campayn.com.campayn.com/".
    """
    subdomain = subdomain.strip()
    if "://" in subdomain:
        subdomain = subdomain.split("://", 1)[1]
    # Drop any path/query left over from a pasted URL.
    subdomain = subdomain.split("/", 1)[0]
    # Strip a trailing ".campayn.com" so a full host collapses to the subdomain label.
    return re.sub(r"\.campayn\.com$", "", subdomain, flags=re.IGNORECASE)


def is_subdomain_valid(subdomain: str) -> bool:
    return bool(_SUBDOMAIN_PATTERN.match(normalize_subdomain(subdomain)))


def base_url(subdomain: str) -> str:
    return f"https://{normalize_subdomain(subdomain)}.campayn.com{CAMPAYN_API_PATH}"


def _headers(api_key: str) -> dict[str, str]:
    # Campayn's custom auth scheme: "Authorization: TRUEREST apikey={key}".
    return {"Authorization": f"TRUEREST apikey={api_key}", "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((CampaynRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> Any:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise CampaynRetryableError(f"Campayn API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Campayn API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _as_rows(payload: Any) -> list[dict[str, Any]]:
    """Coerce a Campayn list response into a list of row dicts.

    Every documented list endpoint returns a bare JSON array. We couldn't curl-verify the live API
    (it needs a per-account subdomain + key), so we also tolerate a single object or a ``{data: [...]}``
    wrapper defensively rather than crashing the sync if the shape differs from the docs.
    """
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return [payload]
    return []


def _iter_list_ids(
    session: requests.Session, subdomain: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[str]:
    payload = _fetch(session, f"{base_url(subdomain)}/lists.json", headers, logger)
    for item in _as_rows(payload):
        # `id` drives all fan-out, so fail fast on a malformed list record rather than silently
        # dropping its contacts/forms.
        yield str(item["id"])


def get_rows(
    subdomain: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = CAMPAYN_ENDPOINTS[endpoint]
    headers = _headers(api_key)
    # One session reused across every request (and, for fan-out, every list) so urllib3 keeps the
    # connection alive instead of re-handshaking per request. `redact_values` masks the API key
    # everywhere the tracked adapter records request headers/URLs/samples — the custom
    # `TRUEREST apikey=...` header isn't recognised by the name-based scrubbers.
    session = make_tracked_session(redact_values=(api_key,))

    if config.fan_out_over_lists:
        yield from _get_fan_out_rows(session, subdomain, headers, logger, config)
        return

    payload = _fetch(session, f"{base_url(subdomain)}{config.path}", headers, logger)
    rows = _as_rows(payload)
    if rows:
        yield rows


def _get_fan_out_rows(
    session: requests.Session,
    subdomain: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    config: CampaynEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    """Fetch a child resource (contacts/forms) per list, stamping each row with its parent ``list_id``.

    Full refresh only — these endpoints expose no incremental filter. The parent ``list_id`` is part of
    the composite primary key, so the same contact appearing under multiple lists stays a distinct row.
    """
    for list_id in _iter_list_ids(session, subdomain, headers, logger):
        url = f"{base_url(subdomain)}{config.path.format(list_id=list_id)}"
        try:
            payload = _fetch(session, url, headers, logger)
        except requests.HTTPError as exc:
            # A list deleted between enumeration and this fetch 404s. Skip it rather than failing the
            # whole sync; any other HTTP error is re-raised.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Campayn: list {list_id} not found while fetching {config.name}, skipping")
                continue
            raise

        rows = [{**row, "list_id": list_id} for row in _as_rows(payload)]
        if rows:
            yield rows


def campayn_source(
    subdomain: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = CAMPAYN_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(subdomain=subdomain, api_key=api_key, endpoint=endpoint, logger=logger),
        primary_keys=config.primary_keys,
        # No stable creation-time field is exposed on any Campayn resource, so partitioning is disabled.
        partition_mode=None,
    )


def validate_credentials(subdomain: str, api_key: str) -> bool:
    # /lists.json is the cheapest read and the entry point every fan-out depends on.
    try:
        # `redact_values` masks the API key in tracked telemetry — the credential check runs before
        # the source is saved, so the raw key must not leak into HTTP logs/samples here either.
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{base_url(subdomain)}/lists.json", headers=_headers(api_key), timeout=15
        )
        return response.status_code == 200
    except Exception:
        return False
