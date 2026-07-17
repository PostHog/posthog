import re
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.settings import (
    LIGHTSPEED_RETAIL_ENDPOINTS,
)

# X-Series v2.0 list pages cap at 200 items.
PAGE_SIZE = 200
REQUEST_TIMEOUT_SECONDS = 60
# Rate limit is 300 × registers + 50 requests per 5-minute window (429 with a
# Retry-After HTTP date); generous exponential backoff keeps us under it.
MAX_RETRY_ATTEMPTS = 6


class LightspeedRetailRetryableError(Exception):
    pass


@dataclasses.dataclass
class LightspeedRetailResumeConfig:
    # X-Series keyset pagination: `after=<version>` where version is the max
    # record version of the previous page — one integer fully describes where
    # to pick back up.
    after: int


def _get_session(api_token: str) -> requests.Session:
    return make_tracked_session(headers={"Authorization": f"Bearer {api_token}"}, redact_values=(api_token,))


def _clean_domain_prefix(domain_prefix: str) -> str:
    """Accept either the bare store subdomain or a pasted full domain/URL."""
    prefix = domain_prefix.strip().removeprefix("https://").removeprefix("http://")
    prefix = prefix.split(".")[0].split("/")[0]
    if not re.fullmatch(r"[a-zA-Z0-9-]+", prefix):
        raise ValueError(f"Invalid Lightspeed domain prefix: {domain_prefix}")
    return prefix


def _base_url(domain_prefix: str) -> str:
    return f"https://{_clean_domain_prefix(domain_prefix)}.retail.lightspeed.app/api/2.0"


def _to_version(value: Any) -> Optional[int]:
    """Coerce an incremental cursor value to an integer record version."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_url(domain_prefix: str, path: str, after: Optional[int], page_size: int = PAGE_SIZE) -> str:
    params: dict[str, Any] = {"page_size": page_size}
    if after is not None:
        params["after"] = after
    return f"{_base_url(domain_prefix)}{path}?{urlencode(params)}"


def validate_credentials(domain_prefix: str, api_token: str) -> bool:
    """Confirm the token and store subdomain are valid with a cheap outlets probe."""
    try:
        response = _get_session(api_token).get(
            _build_url(domain_prefix, "/outlets", None, page_size=1),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    domain_prefix: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LightspeedRetailResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = LIGHTSPEED_RETAIL_ENDPOINTS[endpoint]
    session = _get_session(api_token)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        after: Optional[int] = resume_config.after
        logger.debug(f"Lightspeed Retail: resuming {endpoint} from version {after}")
    elif should_use_incremental_field:
        after = _to_version(db_incremental_field_last_value)
    else:
        after = None

    @retry(
        retry=retry_if_exception_type((LightspeedRetailRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=120),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = session.get(page_url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise LightspeedRetailRetryableError(
                f"Lightspeed Retail API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(
                f"Lightspeed Retail API error: status={response.status_code}, body={response.text}, url={page_url}"
            )
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(_build_url(domain_prefix, config.path, after))
        items = data.get("data", []) or []

        if not items:
            break

        yield items

        next_after = (data.get("version") or {}).get("max")
        if next_after is None:
            # Defensive: without the keyset cursor we can't advance; recompute
            # from the page to avoid refetching the same window forever.
            next_after = max((item.get("version") or 0) for item in items)
            if after is not None and next_after <= after:
                break

        after = int(next_after)
        # Save state AFTER yielding the page so a crash re-yields the last page
        # (merge dedupes on primary key) rather than skipping it.
        resumable_source_manager.save_state(LightspeedRetailResumeConfig(after=after))


def lightspeed_retail_source(
    domain_prefix: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LightspeedRetailResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = LIGHTSPEED_RETAIL_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            domain_prefix=domain_prefix,
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Keyset pagination on the monotonic version yields ascending version order.
        sort_mode="asc",
    )
