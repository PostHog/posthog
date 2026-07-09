import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.printify.settings import (
    PRINTIFY_ENDPOINTS,
    PrintifyEndpointConfig,
)

PRINTIFY_BASE_URL = "https://api.printify.com/v1"
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm a token is genuine. Every shop-scoped stream needs the shop list
# anyway, so `shops.read` access is effectively required for the source to work at all.
DEFAULT_PROBE_PATH = "/shops.json"


class PrintifyRetryableError(Exception):
    pass


@dataclasses.dataclass
class PrintifyResumeConfig:
    # Shop currently being iterated for shop-scoped endpoints; None for account-level endpoints.
    # A resumed sync re-fetches this shop from `page`; merge dedupes re-pulled rows on the
    # primary key.
    shop_id: int | None = None
    # Next page to fetch (1-based, Laravel-style page numbers). Ignored by non-paginated endpoints.
    page: int = 1


def _headers(api_key: str) -> dict[str, str]:
    # Printify requires a User-Agent header on every request.
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": "PostHog",
    }


@retry(
    retry=retry_if_exception_type((PrintifyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    page: int | None,
    limit: int | None,
    logger: FilteringBoundLogger,
) -> tuple[list[dict[str, Any]], bool]:
    params: dict[str, Any] = {}
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit

    response = session.get(
        f"{PRINTIFY_BASE_URL}{path}",
        params=params or None,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    # Printify throttles at 600 req/min globally (100 req/min on catalog endpoints) with HTTP 429.
    if response.status_code == 429 or response.status_code >= 500:
        raise PrintifyRetryableError(f"Printify API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"Printify API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()

    # Non-paginated endpoints (shops, webhooks, catalog) return a bare JSON array.
    if isinstance(data, list):
        return data, False

    # Paginated endpoints return a Laravel paginator: {"current_page", "data": [...], "last_page",
    # "next_page_url", ...}.
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        items: list[dict[str, Any]] = data["data"]
        current_page = data.get("current_page")
        last_page = data.get("last_page")
        if isinstance(current_page, int) and isinstance(last_page, int):
            has_more = current_page < last_page
        else:
            has_more = bool(data.get("next_page_url"))
        return items, has_more and bool(items)

    raise PrintifyRetryableError(f"Printify returned an unexpected payload for {path}: {type(data).__name__}")


def _prepare_rows(
    config: PrintifyEndpointConfig, items: list[dict[str, Any]], shop_id: int | None
) -> list[dict[str, Any]]:
    rows = items
    if config.redact_fields:
        redacted = set(config.redact_fields)
        rows = [{key: value for key, value in row.items() if key not in redacted} for row in rows]
    if shop_id is not None:
        # Shop-scoped objects don't reliably carry their shop id, and the composite primary key
        # needs it. Webhook objects that already include one keep the API's own value.
        rows = [{**row, "shop_id": row.get("shop_id", shop_id)} for row in rows]
    return rows


def _iter_endpoint_pages(
    session: requests.Session,
    config: PrintifyEndpointConfig,
    path: str,
    start_page: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PrintifyResumeConfig],
    shop_id: int | None,
) -> Iterator[list[dict[str, Any]]]:
    if not config.paginated:
        items, _ = _fetch_page(session, path, None, None, logger)
        if items:
            yield _prepare_rows(config, items, shop_id)
        # Save AFTER yielding so a crash resumes at this shop — re-fetching it once is
        # idempotent because merge dedupes on the primary key.
        if shop_id is not None:
            resumable_source_manager.save_state(PrintifyResumeConfig(shop_id=shop_id, page=1))
        return

    page = start_page
    while True:
        items, has_more = _fetch_page(session, path, page, config.page_size, logger)
        if items:
            yield _prepare_rows(config, items, shop_id)

        if not has_more or not items:
            break

        page += 1
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(PrintifyResumeConfig(shop_id=shop_id, page=page))


def _list_shops(session: requests.Session, logger: FilteringBoundLogger) -> list[dict[str, Any]]:
    shops, _ = _fetch_page(session, PRINTIFY_ENDPOINTS["shops"].path, None, None, logger)
    return shops


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PrintifyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = PRINTIFY_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if not config.shop_scoped:
        start_page = resume.page if resume else 1
        if resume:
            logger.debug(f"Printify: resuming {endpoint} from page {start_page}")
        yield from _iter_endpoint_pages(
            session, config, config.path, start_page, logger, resumable_source_manager, shop_id=None
        )
        return

    shops = _list_shops(session, logger)
    resume_shop_id = resume.shop_id if resume else None
    resume_page = resume.page if resume else 1
    if resume_shop_id is not None and all(shop["id"] != resume_shop_id for shop in shops):
        # The saved shop no longer exists (disconnected sales channel); start from the beginning.
        logger.debug(f"Printify: saved shop {resume_shop_id} not found, restarting {endpoint} from the first shop")
        resume_shop_id = None

    if resume_shop_id is not None:
        logger.debug(f"Printify: resuming {endpoint} from shop {resume_shop_id}, page {resume_page}")

    skipping = resume_shop_id is not None
    for shop in shops:
        shop_id = shop["id"]
        if skipping:
            if shop_id != resume_shop_id:
                continue
            skipping = False
            start_page = resume_page
        else:
            start_page = 1

        path = config.path.format(shop_id=shop_id)
        yield from _iter_endpoint_pages(
            session, config, path, start_page, logger, resumable_source_manager, shop_id=shop_id
        )


def printify_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PrintifyResumeConfig],
) -> SourceResponse:
    config = PRINTIFY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def check_access(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the API token.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        response = session.get(f"{PRINTIFY_BASE_URL}{path}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Printify: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Printify returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Printify API token"
    return False, message or "Could not validate Printify API token"
