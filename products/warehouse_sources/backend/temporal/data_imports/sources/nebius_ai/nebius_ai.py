import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.nebius_ai.settings import NEBIUS_AI_ENDPOINTS

# Token Factory rebrand of the former api.studio.nebius.ai host. OpenAI-compatible surface.
NEBIUS_AI_BASE_URL = "https://api.tokenfactory.nebius.com/v1"

# OpenAI-style `limit`. Nebius accepts up to 100 on the paginated list endpoints.
PAGE_SIZE = 100


class NebiusAIRetryableError(Exception):
    pass


@dataclasses.dataclass
class NebiusAIResumeConfig:
    # OpenAI-style cursor: the id of the last object already yielded, sent as `after` to fetch the
    # next page. None starts the list from the beginning.
    after: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _build_url(path: str, params: dict[str, Any]) -> str:
    url = f"{NEBIUS_AI_BASE_URL}{path}"
    if not params:
        return url
    return f"{url}?{urlencode(params)}"


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    # /models is the cheapest authenticated probe: every valid key can read it and it needs no params.
    # `redact_values` keeps the key out of captured request samples; redirects are pinned off so the
    # bearer token is never replayed to a host the probe did not validate against.
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
    try:
        response = session.get(f"{NEBIUS_AI_BASE_URL}/models", headers=_get_headers(api_key), timeout=10)
    except requests.RequestException as exc:
        # A timeout or connection blip is not a credential problem — never report it as an invalid key.
        return False, f"Could not reach Nebius AI: {exc}"

    if response.ok:
        return True, None

    if response.status_code == 401:
        return (
            False,
            "Your Nebius AI API key is invalid or has expired. Create a new key in the Nebius AI Studio console, then reconnect.",
        )

    if response.status_code == 403:
        return (
            False,
            "Your Nebius AI API key does not have the permissions needed to sync this data. Grant read access to the key, then reconnect.",
        )

    # 429/5xx and other unexpected statuses are transient; don't mislabel the key as invalid.
    return False, f"Nebius AI API returned status {response.status_code}, try reconnecting shortly."


@retry(
    # ChunkedEncodingError is a mid-stream connection break, transient like ConnectionError/ReadTimeout.
    retry=retry_if_exception_type(
        (
            NebiusAIRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    response = session.get(url, headers=headers, timeout=60)

    # Nebius enforces per-plan rate limits with 429s; retry those and transient 5xx with backoff.
    if response.status_code == 429 or response.status_code >= 500:
        raise NebiusAIRetryableError(f"Nebius AI API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Nebius AI API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NebiusAIResumeConfig],
) -> Iterator[Any]:
    config = NEBIUS_AI_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across every page so urllib3 keeps the connection alive. `redact_values`
    # masks the key in captured samples; `allow_redirects=False` stops the bearer token being replayed
    # to an attacker-controlled host on a 30x.
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)

    if not config.paginated:
        data = _fetch_page(session, _build_url(config.path, {}), headers, logger)
        items = data.get("data", [])
        if items:
            yield items
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    after = resume.after if resume else None

    while True:
        params: dict[str, Any] = {"limit": PAGE_SIZE}
        if after:
            params["after"] = after

        data = _fetch_page(session, _build_url(config.path, params), headers, logger)
        items = data.get("data", [])
        if not items:
            break

        yield items

        # Prefer the server-provided cursor; fall back to the last row's id when the endpoint
        # omits `last_id` (some OpenAI-compatible list responses only return `has_more`). Index the
        # required primary key directly so any malformed final row — missing `id` or not even a
        # mapping — fails loudly instead of silently dropping every later page.
        last_id = data.get("last_id") or items[-1]["id"]
        if not data.get("has_more") or not last_id:
            break

        after = last_id
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it; merge
        # dedupes the re-pulled rows on the primary key.
        resumable_source_manager.save_state(NebiusAIResumeConfig(after=after))


def nebius_ai_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NebiusAIResumeConfig],
) -> SourceResponse:
    config = NEBIUS_AI_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        # These OpenAI-style list endpoints return newest-first. sort_mode is inert while every stream
        # is full-refresh (no incremental watermark), but declaring the true order keeps resume/
        # watermark semantics correct if a server-side time filter is ever added.
        sort_mode="desc",
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
