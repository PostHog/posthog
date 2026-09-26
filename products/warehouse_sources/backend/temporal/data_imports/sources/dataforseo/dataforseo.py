import base64
from collections.abc import Callable, Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.dataforseo.settings import (
    DATAFORSEO_ENDPOINTS,
    DataForSEOEndpointConfig,
    ParseKind,
)

DATAFORSEO_BASE_URL = "https://api.dataforseo.com/v3"

DEFAULT_LOCATION_NAME = "United States"
DEFAULT_LANGUAGE_NAME = "English"

# Documented maximum `limit` for paginated Labs endpoints (default is 100).
PAGE_SIZE = 1000
# Every page is a billable request, so bound the per-target spend on paginated endpoints.
MAX_PAGES_PER_TARGET = 5
# The connector issues at least one billable request per target for every selected table, so an
# unbounded target list lets a saved config fan out into arbitrarily many charged requests per
# scheduled sync.
MAX_TARGETS = 25
# The SERP table spends one billable request per keyword per sync, so bound the keyword list too.
MAX_KEYWORDS = 50
REQUEST_TIMEOUT_SECONDS = 120
MAX_RETRIES = 5


class DataForSEORetryableError(Exception):
    """Raised on transient failures (HTTP 429/5xx, per-minute rate limit, 50xxx body codes)."""


class DataForSEOAPIError(Exception):
    """Raised on permanent body-level errors (auth, funds, invalid request)."""


@frozen
class DataForSEOResumeConfig:
    # Which fan-out value the sync is on and the next page offset within it: `target` for the
    # target-scoped endpoints, `keyword` for the keyword-scoped ones. Values are processed in
    # config order, so on resume earlier ones are skipped entirely. Both default to empty so
    # state written by an older deploy still loads.
    target: str = ""
    keyword: str = ""
    offset: int = 0


def _make_session(api_login: str, api_password: str) -> requests.Session:
    # DataForSEO uses HTTP basic auth; the encoded token rides in the Authorization header, so
    # register both the password and the token for redaction in tracked HTTP logs/samples.
    token = base64.b64encode(f"{api_login}:{api_password}".encode()).decode()
    return make_tracked_session(
        headers={"Authorization": f"Basic {token}", "Accept": "application/json"},
        redact_values=(api_password, token),
    )


def parse_targets(targets: str) -> list[str]:
    """Split the user's comma-separated targets field into a de-duplicated, normalized list.

    DataForSEO expects domains without the scheme, so strip `http(s)://` and a trailing slash.
    A leading `www.` is kept off domains too, matching the API docs' guidance.
    """
    seen: set[str] = set()
    result: list[str] = []
    for raw in targets.split(","):
        target = raw.strip().lower()
        for prefix in ("https://", "http://", "www."):
            target = target.removeprefix(prefix)
        target = target.rstrip("/")
        if target and target not in seen:
            seen.add(target)
            result.append(target)
    return result


def validate_targets(targets: str) -> tuple[list[str], str | None]:
    """Parse and bound the targets field. Returns the parsed list plus a user-facing error, if any."""
    parsed = parse_targets(targets)
    if not parsed:
        return parsed, "Enter at least one target domain (e.g. example.com)"
    if len(parsed) > MAX_TARGETS:
        return parsed, f"Too many target domains ({len(parsed)}); enter at most {MAX_TARGETS} distinct domains."
    return parsed, None


def parse_keywords(keywords: str) -> list[str]:
    """Split the user's comma-separated keywords field into a de-duplicated, normalized list.

    DataForSEO lower-cases keywords server-side, so normalizing here keeps the rows we sync
    keyed the same way the API returns them.
    """
    seen: set[str] = set()
    result: list[str] = []
    for raw in keywords.split(","):
        keyword = " ".join(raw.split()).lower()
        if keyword and keyword not in seen:
            seen.add(keyword)
            result.append(keyword)
    return result


def validate_keywords(keywords: str | None) -> tuple[list[str], str | None]:
    """Parse and bound the keywords field. Returns the parsed list plus a user-facing error, if any."""
    parsed = parse_keywords(keywords or "")
    if len(parsed) > MAX_KEYWORDS:
        return parsed, f"Too many keywords ({len(parsed)}); enter at most {MAX_KEYWORDS} distinct keywords."
    return parsed, None


def _raise_for_body_status(status_code: Any, status_message: Any) -> None:
    """Classify a DataForSEO body-level status code (top-level or per-task).

    20000 is success. 40202 (per-minute rate limit) and 50xxx (server side) are transient;
    everything else in the 4xxxx range is permanent (auth, funds, invalid request).
    """
    if status_code is None or status_code == 20000:
        return
    if status_code == 40202 or 50000 <= status_code < 60000:
        raise DataForSEORetryableError(f"DataForSEO API error (retryable) [{status_code}]: {status_message}")
    raise DataForSEOAPIError(f"DataForSEO API error [{status_code}]: {status_message}")


@retry(
    retry=retry_if_exception_type((DataForSEORetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _request_task(
    session: requests.Session,
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    """Call one endpoint and return the first task's result list.

    Live endpoints take a single-task POST array; the free Labs lookups are plain GETs.
    """
    url = f"{DATAFORSEO_BASE_URL}{path}"
    if method == "GET":
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    else:
        response = session.post(url, json=[payload], timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise DataForSEORetryableError(f"DataForSEO API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"DataForSEO API error: status={response.status_code}, body={response.text[:500]}, url={url}")
        response.raise_for_status()

    body = response.json()
    if not isinstance(body, dict):
        raise DataForSEOAPIError(f"DataForSEO API error [unexpected_response]: response was not a JSON object ({url})")

    _raise_for_body_status(body.get("status_code"), body.get("status_message"))

    tasks = body.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return []

    task = tasks[0]
    _raise_for_body_status(task.get("status_code"), task.get("status_message"))

    result = task.get("result")
    if not isinstance(result, list):
        return []
    return [entry for entry in result if isinstance(entry, dict)]


def _parse_items(results: list[dict[str, Any]], target: str | None) -> Iterator[dict[str, Any]]:
    for result in results:
        items = result.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                yield {**item, "target": target}


def _parse_ranked_keywords(results: list[dict[str, Any]], target: str | None) -> Iterator[dict[str, Any]]:
    # Lift the primary-key fields out of the nested keyword_data/ranked_serp_element blocks so
    # the table has queryable top-level key columns; the full nested payloads are kept as-is.
    for result in results:
        items = result.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            keyword_data = item.get("keyword_data") or {}
            serp_item = (item.get("ranked_serp_element") or {}).get("serp_item") or {}
            keyword = keyword_data.get("keyword")
            if not keyword:
                continue
            yield {
                **item,
                "target": target,
                "keyword": keyword,
                "item_type": serp_item.get("type"),
                "rank_group": serp_item.get("rank_group"),
                "rank_absolute": serp_item.get("rank_absolute"),
                "ranked_url": serp_item.get("url"),
            }


def _parse_monthly_items(results: list[dict[str, Any]], target: str | None) -> Iterator[dict[str, Any]]:
    for result in results:
        items = result.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            year, month = item.get("year"), item.get("month")
            # `date` is the injected stable partition column (first day of the item's month).
            date = f"{year:04d}-{month:02d}-01" if isinstance(year, int) and isinstance(month, int) else None
            yield {**item, "target": target, "date": date}


def _parse_result_rows(results: list[dict[str, Any]], target: str | None) -> Iterator[dict[str, Any]]:
    # Backlinks summary carries its fields directly on tasks[].result[] with no nested items.
    for result in results:
        yield {**result, "target": target}


def _parse_keyword_monthly_searches(results: list[dict[str, Any]], _value: str | None) -> Iterator[dict[str, Any]]:
    # One request covers every keyword, so the rows carry the keyword from the response rather
    # than an injected fan-out value. Each keyword's history arrives as a nested
    # keyword_info.monthly_searches array, which is flattened into one row per month.
    for result in results:
        items = result.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            keyword = item.get("keyword")
            monthly_searches = (item.get("keyword_info") or {}).get("monthly_searches")
            if not keyword or not isinstance(monthly_searches, list):
                continue
            for entry in monthly_searches:
                if not isinstance(entry, dict):
                    continue
                year, month = entry.get("year"), entry.get("month")
                if not isinstance(year, int) or not isinstance(month, int):
                    continue
                yield {
                    "keyword": keyword,
                    "se_type": item.get("se_type"),
                    "location_code": item.get("location_code"),
                    "language_code": item.get("language_code"),
                    "search_partners": item.get("search_partners"),
                    "year": year,
                    "month": month,
                    # `date` is the injected stable partition column (first day of the month).
                    "date": f"{year:04d}-{month:02d}-01",
                    "search_volume": entry.get("search_volume"),
                }


def _parse_serp_items(results: list[dict[str, Any]], keyword: str | None) -> Iterator[dict[str, Any]]:
    # Stamp each SERP element with the keyword and the crawl metadata from its result block, so a
    # snapshot can be told apart from the next one taken for the same keyword.
    for result in results:
        items = result.get("items")
        if not isinstance(items, list):
            continue
        context = {
            "keyword": result.get("keyword") or keyword,
            "se_domain": result.get("se_domain"),
            "location_code": result.get("location_code"),
            "language_code": result.get("language_code"),
            "check_url": result.get("check_url"),
            "datetime": result.get("datetime"),
        }
        for item in items:
            if isinstance(item, dict):
                yield {**item, **context}


def _parse_lookup_rows(results: list[dict[str, Any]], target: str | None) -> Iterator[dict[str, Any]]:
    # Lookup tables are global: their rows sit directly on tasks[].result[] and carry no target.
    yield from results


_PARSERS: dict[ParseKind, Callable[[list[dict[str, Any]], str | None], Iterator[dict[str, Any]]]] = {
    "items": _parse_items,
    "ranked_keywords": _parse_ranked_keywords,
    "monthly_items": _parse_monthly_items,
    "result_rows": _parse_result_rows,
    "lookup_rows": _parse_lookup_rows,
    "keyword_monthly_searches": _parse_keyword_monthly_searches,
    "serp_items": _parse_serp_items,
}


def _payload(
    config: DataForSEOEndpointConfig,
    value: str | list[str],
    location_name: str,
    language_name: str,
    offset: int | None = None,
) -> dict[str, Any] | None:
    """Build the single-task request body, or None for the untargeted GET lookups.

    `value` is the endpoint's fan-out value: a target domain, one keyword, or — for the batched
    keyword endpoint — the whole keyword list.
    """
    if config.scope == "global":
        return None

    payload: dict[str, Any] = dict(config.extra_payload)
    if config.scope == "target":
        payload["target"] = value
    elif config.scope == "keyword":
        payload["keyword"] = value
    else:
        payload["keywords"] = value

    if config.localized:
        payload["location_name"] = location_name
        payload["language_name"] = language_name
    if config.paginated:
        payload["limit"] = PAGE_SIZE
        payload["offset"] = offset or 0
    return payload


def _has_more_pages(results: list[dict[str, Any]], item_count: int, next_offset: int) -> bool:
    if item_count == 0:
        return False
    total_count = results[0].get("total_count") if results else None
    if isinstance(total_count, int):
        return next_offset < total_count
    # Without a usable total_count, keep going only while pages come back full.
    return item_count >= PAGE_SIZE


def _next_page_offset(
    config: DataForSEOEndpointConfig,
    results: list[dict[str, Any]],
    offset: int,
    endpoint: str,
    value: str,
    logger: FilteringBoundLogger,
) -> int | None:
    """Offset of the next page for this fan-out value, or None once it is done."""
    if not config.paginated:
        return None

    item_count = sum(len(result.get("items") or []) for result in results)
    next_offset = offset + item_count
    if not _has_more_pages(results, item_count, next_offset):
        return None

    if next_offset >= PAGE_SIZE * MAX_PAGES_PER_TARGET:
        logger.warning(
            f"DataForSEO: page cap reached, truncating results. endpoint={endpoint} value={value} "
            f"rows_fetched={next_offset} max_rows={PAGE_SIZE * MAX_PAGES_PER_TARGET}"
        )
        return None
    return next_offset


def _resume_state(config: DataForSEOEndpointConfig, value: str, offset: int) -> DataForSEOResumeConfig:
    if config.scope == "keyword":
        return DataForSEOResumeConfig(keyword=value, offset=offset)
    return DataForSEOResumeConfig(target=value, offset=offset)


def get_rows(
    api_login: str,
    api_password: str,
    targets: list[str],
    keywords: list[str],
    location_name: str,
    language_name: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DataForSEOResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = DATAFORSEO_ENDPOINTS[endpoint]
    parser = _PARSERS[config.kind]
    session = _make_session(api_login, api_password)

    # A lookup has no fan-out and the batched keyword endpoint covers every keyword in one
    # request, so neither has a cursor to resume from.
    if config.scope in ("global", "keyword_batch"):
        payload = _payload(config, keywords, location_name, language_name)
        rows = list(parser(_request_task(session, config.method, config.path, payload, logger), None))
        if rows:
            yield rows
        return

    values = keywords if config.scope == "keyword" else targets

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    resume_value = (resume.keyword or resume.target) if resume is not None else None
    start_index, start_offset = 0, 0
    # If the saved value was removed from the config since the state was written, start over.
    if resume is not None and resume_value in values:
        start_index = values.index(resume_value)
        start_offset = resume.offset
        logger.debug(f"DataForSEO: resuming endpoint={endpoint} from value={resume_value} offset={resume.offset}")

    for index in range(start_index, len(values)):
        value = values[index]
        offset = start_offset if index == start_index else 0
        next_value = values[index + 1] if index + 1 < len(values) else None

        while True:
            results = _request_task(
                session,
                config.method,
                config.path,
                _payload(config, value, location_name, language_name, offset),
                logger,
            )
            rows = list(parser(results, value))
            if rows:
                yield rows

            next_offset = _next_page_offset(config, results, offset, endpoint, value, logger)
            if next_offset is None:
                break

            # Persist AFTER yielding — a crash re-yields the last page rather than skipping it.
            resumable_source_manager.save_state(_resume_state(config, value, next_offset))
            offset = next_offset

        if next_value is not None:
            resumable_source_manager.save_state(_resume_state(config, next_value, 0))


def dataforseo_source(
    api_login: str,
    api_password: str,
    targets: list[str],
    keywords: list[str],
    location_name: str,
    language_name: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DataForSEOResumeConfig],
) -> SourceResponse:
    config = DATAFORSEO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_login=api_login,
            api_password=api_password,
            targets=targets,
            keywords=keywords,
            location_name=location_name,
            language_name=language_name,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_login: str, api_password: str) -> bool:
    """Confirm the credentials with the free account-info endpoint (never billed)."""
    if not api_login.strip() or not api_password.strip():
        return False

    try:
        session = _make_session(api_login, api_password)
        response = session.get(f"{DATAFORSEO_BASE_URL}/appendix/user_data", timeout=30)
    except Exception:
        return False

    if not response.ok:
        return False

    try:
        body = response.json()
    except ValueError:
        return False

    return isinstance(body, dict) and body.get("status_code") == 20000
