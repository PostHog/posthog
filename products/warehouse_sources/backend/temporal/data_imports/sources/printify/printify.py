import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    make_tracked_session,
    retry_with_deadline,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.interruptible_wait import (
    interruptible_wait,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.printify.settings import (
    PRINTIFY_ENDPOINTS,
    PrintifyEndpointConfig,
    PrintifyFanOut,
)

PRINTIFY_BASE_URL = "https://api.printify.com/v1"
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm a token is genuine. Every shop-scoped stream needs the shop list
# anyway, so `shops.read` access is effectively required for the source to work at all.
DEFAULT_PROBE_PATH = "/shops.json"
# Catalog endpoints share a separate 100 requests/minute limit per account. Catalog fan-out makes
# hundreds of requests, so it paces itself rather than relying on 429 backoff. Each of the three
# catalog fan-out tables takes a third of the limit, so they stay under it when they sync at once.
CATALOG_REQUEST_INTERVAL_SECONDS = 1.8


class PrintifyRetryableError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class PrintifyResumeConfig:
    # Shop currently being iterated for shop-scoped endpoints; None for account-level endpoints.
    # A resumed sync re-fetches this shop from `page`; merge dedupes re-pulled rows on the
    # primary key.
    shop_id: int | None = None
    # Next page to fetch (1-based, Laravel-style page numbers). Ignored by non-paginated endpoints.
    page: int = 1
    # Last catalog parent whose child rows were yielded, for catalog fan-out endpoints.
    blueprint_id: int | None = None
    print_provider_id: int | None = None
    # Product fan-out walks each page in product id order; this is the last id on `page` it finished.
    product_id: str | None = None


@dataclasses.dataclass(frozen=True, order=True)
class CatalogPair:
    blueprint_id: int
    print_provider_id: int


def _headers(api_key: str) -> dict[str, str]:
    # Printify requires a User-Agent header on every request.
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": "PostHog",
    }


_retry = retry_with_deadline(
    retry=retry_if_exception_type((PrintifyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)


def _request(
    session: requests.Session,
    path: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
    allow_not_found: bool = False,
) -> Any:
    response = session.get(
        f"{PRINTIFY_BASE_URL}{path}",
        params=params or None,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    # Printify throttles at 600 req/min globally (100 req/min on catalog endpoints) with HTTP 429.
    if response.status_code == 429 or response.status_code >= 500:
        raise PrintifyRetryableError(f"Printify API error (retryable): status={response.status_code}, path={path}")

    if allow_not_found and response.status_code == 404:
        return None

    if not response.ok:
        logger.error(f"Printify API error: status={response.status_code}, body={response.text}, path={path}")
        # raise_for_status() would embed the full request URL in the exception, which is surfaced
        # as the schema's latest_error outside the warehouse table ACLs. Printify authenticates via
        # the Authorization header today, but rebuild the error from scheme/host/path only so a
        # redirect or future query-param auth can never leak credentials into stored error state.
        # The "<status> Client Error: <reason> for url: https://api.printify.com" prefix stays
        # stable for get_non_retryable_errors() matching.
        safe = urlsplit(response.url)
        raise requests.HTTPError(
            f"{response.status_code} Client Error: {response.reason} for url: {safe.scheme}://{safe.netloc}{safe.path}",
            response=response,
        )

    return response.json()


@_retry
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

    data = _request(session, path, params, logger)

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


@_retry
def _fetch_child(
    session: requests.Session, path: str, params: dict[str, str], logger: FilteringBoundLogger
) -> Any | None:
    # A product can be deleted after the parent listing, and a product can keep a catalog
    # blueprint/provider pair that Printify has since retired. Both answer 404; skip that parent.
    return _request(session, path, params, logger, allow_not_found=True)


def _shipping_rate_rows(payload: Any, parent: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any]] = set()
    for profile in payload.get("profiles") or []:
        for variant_id in profile.get("variant_ids") or []:
            for country in profile.get("countries") or []:
                # The primary key is (pair, variant, country); keep the first profile if two overlap.
                if (variant_id, country) in seen:
                    continue
                seen.add((variant_id, country))
                rows.append(
                    {
                        **parent,
                        "variant_id": variant_id,
                        "country": country,
                        "handling_time": payload.get("handling_time"),
                        "first_item": profile.get("first_item"),
                        "additional_items": profile.get("additional_items"),
                    }
                )
    return rows


def _shape_child_rows(endpoint: str, payload: Any, parent: dict[str, Any]) -> list[dict[str, Any]]:
    if endpoint == "catalog_variants":
        variants = payload.get("variants") if isinstance(payload, dict) else None
        return [{**variant, **parent} for variant in variants or []]
    if endpoint == "catalog_shipping_rates":
        return _shipping_rate_rows(payload, parent)
    if endpoint == "product_gpsr":
        return [{**parent, "sections": payload}] if isinstance(payload, list) and payload else []
    return [{**row, **parent} for row in payload] if isinstance(payload, list) else []


def _iter_child_rows(
    session: requests.Session,
    config: PrintifyEndpointConfig,
    parent: dict[str, Any],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PrintifyResumeConfig],
    state: PrintifyResumeConfig,
) -> Iterator[list[dict[str, Any]]]:
    path = config.path.format(**parent)
    payload = _fetch_child(session, path, config.query_params, logger)
    if payload is None:
        logger.debug(f"Printify: {path} returned 404, skipping")
    rows = _shape_child_rows(config.name, payload, parent) if payload is not None else []

    resumable_source_manager.save_state(state)
    if rows:
        yield rows
    else:
        resumable_source_manager.safe_point()


def _pace_catalog_request(resumable_source_manager: ResumableSourceManager[PrintifyResumeConfig]) -> None:
    interruptible_wait(CATALOG_REQUEST_INTERVAL_SECONDS, safe_point=resumable_source_manager.safe_point)


def _list_shops(session: requests.Session, logger: FilteringBoundLogger) -> list[dict[str, Any]]:
    shops, _ = _fetch_page(session, PRINTIFY_ENDPOINTS["shops"].path, None, None, logger)
    return shops


def _iter_shop_product_pages(
    session: requests.Session,
    shop_id: int,
    start_page: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PrintifyResumeConfig],
) -> Iterator[tuple[int, list[dict[str, Any]]]]:
    products_config = PRINTIFY_ENDPOINTS["products"]
    path = products_config.path.format(shop_id=shop_id)
    page = start_page
    while True:
        products, has_more = _fetch_page(session, path, page, products_config.page_size, logger)
        # The product listing yields no rows itself; every child row of earlier products is yielded.
        resumable_source_manager.safe_point()
        yield page, products
        if not has_more or not products:
            return
        page += 1


def _iter_blueprint_fan_out(
    session: requests.Session,
    config: PrintifyEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PrintifyResumeConfig],
    resume: PrintifyResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    blueprints, _ = _fetch_page(session, PRINTIFY_ENDPOINTS["blueprints"].path, None, None, logger)
    resume_after = resume.blueprint_id if resume else None
    # Sorted ids let a resumed sync skip completed blueprints even when the catalog changed.
    for blueprint_id in sorted({blueprint["id"] for blueprint in blueprints}):
        if resume_after is not None and blueprint_id <= resume_after:
            continue
        _pace_catalog_request(resumable_source_manager)
        yield from _iter_child_rows(
            session,
            config,
            {"blueprint_id": blueprint_id},
            logger,
            resumable_source_manager,
            PrintifyResumeConfig(blueprint_id=blueprint_id),
        )


def _list_product_catalog_pairs(
    session: requests.Session,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PrintifyResumeConfig],
) -> list[CatalogPair]:
    pairs: set[CatalogPair] = set()
    for shop in _list_shops(session, logger):
        for _, products in _iter_shop_product_pages(session, shop["id"], 1, logger, resumable_source_manager):
            for product in products:
                blueprint_id = product.get("blueprint_id")
                print_provider_id = product.get("print_provider_id")
                if isinstance(blueprint_id, int) and isinstance(print_provider_id, int):
                    pairs.add(CatalogPair(blueprint_id, print_provider_id))
    return sorted(pairs)


def _iter_product_catalog_pair_fan_out(
    session: requests.Session,
    config: PrintifyEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PrintifyResumeConfig],
    resume: PrintifyResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    resume_after: CatalogPair | None = None
    if resume and resume.blueprint_id is not None and resume.print_provider_id is not None:
        resume_after = CatalogPair(resume.blueprint_id, resume.print_provider_id)

    for pair in _list_product_catalog_pairs(session, logger, resumable_source_manager):
        if resume_after is not None and pair <= resume_after:
            continue
        _pace_catalog_request(resumable_source_manager)
        yield from _iter_child_rows(
            session,
            config,
            dataclasses.asdict(pair),
            logger,
            resumable_source_manager,
            PrintifyResumeConfig(blueprint_id=pair.blueprint_id, print_provider_id=pair.print_provider_id),
        )


def _iter_product_fan_out(
    session: requests.Session,
    config: PrintifyEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PrintifyResumeConfig],
    resume: PrintifyResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    shops = _list_shops(session, logger)
    resume_shop_id = resume.shop_id if resume else None
    resume_page = resume.page if resume else 1
    resume_product_id = resume.product_id if resume else None
    if resume_shop_id is not None and all(shop["id"] != resume_shop_id for shop in shops):
        logger.debug(f"Printify: saved shop {resume_shop_id} not found, restarting {config.name} from the first shop")
        resume_shop_id = None

    skipping = resume_shop_id is not None
    for shop in shops:
        shop_id = shop["id"]
        skip_through_product_id: str | None = None
        if skipping:
            if shop_id != resume_shop_id:
                continue
            skipping = False
            start_page = resume_page
            skip_through_product_id = resume_product_id
        else:
            start_page = 1

        for page, products in _iter_shop_product_pages(session, shop_id, start_page, logger, resumable_source_manager):
            # Id order, not position, so a resume skips finished products even when the checkpoint
            # product was deleted in the meantime.
            products = sorted(products, key=lambda product: str(product["id"]))
            if skip_through_product_id is not None:
                products = [product for product in products if str(product["id"]) > skip_through_product_id]
                skip_through_product_id = None
            for product in products:
                yield from _iter_child_rows(
                    session,
                    config,
                    {"shop_id": shop_id, "product_id": product["id"]},
                    logger,
                    resumable_source_manager,
                    PrintifyResumeConfig(shop_id=shop_id, page=page, product_id=str(product["id"])),
                )


_FAN_OUT_ITERATORS = {
    PrintifyFanOut.BLUEPRINT: _iter_blueprint_fan_out,
    PrintifyFanOut.PRODUCT_CATALOG_PAIR: _iter_product_catalog_pair_fan_out,
    PrintifyFanOut.PRODUCT: _iter_product_fan_out,
}


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PrintifyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = PRINTIFY_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.fan_out is not None:
        if resume:
            logger.debug(f"Printify: resuming {endpoint} from {resume}")
        yield from _FAN_OUT_ITERATORS[config.fan_out](session, config, logger, resumable_source_manager, resume)
        return

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
