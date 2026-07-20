from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.aiven.settings import (
    AIVEN_ENDPOINTS,
    AivenEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

AIVEN_BASE_URL = "https://api.aiven.io/v1"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5


class AivenRetryableError(Exception):
    pass


def _get_headers(api_token: str) -> dict[str, str]:
    # Aiven expects the literal `aivenv1` prefix before the token, not `Bearer`.
    return {
        "Authorization": f"aivenv1 {api_token}",
        "Accept": "application/json",
    }


def _make_session(api_token: str) -> requests.Session:
    # Redact the token everywhere it could surface: the `aivenv1 <token>` scheme is
    # non-standard, so the tracked transport's name-based scrubbers can't recognise it.
    return make_tracked_session(redact_values=(api_token,))


@retry(
    retry=retry_if_exception_type((AivenRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch(
    url: str, headers: dict[str, str], logger: FilteringBoundLogger, session: requests.Session
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    # Aiven does not publish rate limits; treat 429 and transient 5xx as retryable and let the
    # exponential backoff handle spacing. Everything else (401/403/404) is surfaced immediately.
    if response.status_code == 429 or response.status_code >= 500:
        raise AivenRetryableError(f"Aiven API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Never log the raw body: these are authenticated third-party responses whose error
        # payloads can echo tenant metadata or request details into centralized logs.
        logger.error(f"Aiven API error: status={response.status_code}, url={url}")
        response.raise_for_status()

    return response.json()


def _list(
    path: str, data_key: str, headers: dict[str, str], logger: FilteringBoundLogger, session: requests.Session
) -> list[dict[str, Any]]:
    """Fetch a single unpaginated Aiven list endpoint and return the rows under ``data_key``.

    Aiven list endpoints return the whole collection in one JSON response (``{"<data_key>": [...]}``)
    with no pagination params documented or accepted, so a single GET is the complete result.
    """
    data = _fetch(f"{AIVEN_BASE_URL}{path}", headers, logger, session)
    rows = data.get(data_key) or []
    return rows if isinstance(rows, list) else []


def _iter_rows(
    config: AivenEndpointConfig, headers: dict[str, str], logger: FilteringBoundLogger, session: requests.Session
) -> Iterator[list[dict[str, Any]]]:
    """Yield one batch of rows per upstream request, fanning out over parents as needed.

    Child rows get their parent identifiers injected as top-level fields so composite primary
    keys stay unique table-wide and rows remain traceable to their parent resource.
    """
    if config.fan_out == "none":
        rows = _list(config.path_template, config.data_key, headers, logger, session)
        if rows:
            yield rows
        return

    if config.fan_out == "project":
        for project in _list("/project", "projects", headers, logger, session):
            project_name = project["project_name"]
            path = config.path_template.format(project=project_name)
            rows = _list(path, config.data_key, headers, logger, session)
            for row in rows:
                row["project_name"] = project_name
            if rows:
                yield rows
        return

    if config.fan_out == "organization":
        for org in _list("/organizations", "organizations", headers, logger, session):
            organization_id = org["organization_id"]
            path = config.path_template.format(organization_id=organization_id)
            rows = _list(path, config.data_key, headers, logger, session)
            for row in rows:
                row.setdefault("organization_id", organization_id)
            if rows:
                yield rows
        return

    if config.fan_out == "invoice":
        for org in _list("/organizations", "organizations", headers, logger, session):
            organization_id = org["organization_id"]
            invoices = _list(f"/organization/{organization_id}/invoices", "invoices", headers, logger, session)
            for invoice in invoices:
                invoice_number = invoice["invoice_number"]
                path = config.path_template.format(organization_id=organization_id, invoice_number=invoice_number)
                rows = _list(path, config.data_key, headers, logger, session)
                for row in rows:
                    row.setdefault("organization_id", organization_id)
                    row["invoice_number"] = invoice_number
                if rows:
                    yield rows
        return

    raise ValueError(f"Unknown fan_out mode: {config.fan_out}")


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = AIVEN_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)
    # One session for the whole run so fan-out requests reuse pooled connections.
    session = _make_session(api_token)
    yield from _iter_rows(config, headers, logger, session)


def validate_credentials(api_token: str) -> bool:
    """Confirm the token is valid. ``/me`` reflects the token itself and needs no resource scope."""
    try:
        response = _make_session(api_token).get(
            f"{AIVEN_BASE_URL}/me",
            headers=_get_headers(api_token),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def aiven_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = AIVEN_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(api_token=api_token, endpoint=endpoint, logger=logger),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
