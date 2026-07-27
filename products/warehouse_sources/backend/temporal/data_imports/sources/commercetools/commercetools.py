import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.settings import (
    COMMERCETOOLS_ENDPOINTS,
    CommercetoolsEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# commercetools query results cap at 500 per request.
PAGE_SIZE = 500
# Offset pagination is hard-capped at 10,000; past it we re-anchor the
# lastModifiedAt window instead.
MAX_OFFSET = 10_000
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5


class CommercetoolsRetryableError(Exception):
    pass


@dataclasses.dataclass
class CommercetoolsResumeConfig:
    # Where to pick the lastModifiedAt-ordered scan back up: the current window
    # anchor (None until the first re-anchor on a full scan) plus the offset
    # within that window.
    anchor: Optional[str]
    offset: int


def _get_session(client_secret: str) -> requests.Session:
    return make_tracked_session(redact_values=(client_secret,))


def _validate_path_component(value: str, label: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", value):
        raise ValueError(f"Invalid commercetools {label}: {value}")
    return value


def _auth_url(region: str) -> str:
    return f"https://auth.{_validate_path_component(region, 'region')}.commercetools.com/oauth/token"


def _api_base_url(region: str, project_key: str) -> str:
    region = _validate_path_component(region, "region")
    project_key = _validate_path_component(project_key, "project key")
    return f"https://api.{region}.commercetools.com/{project_key}"


def _mint_token(session: requests.Session, region: str, client_id: str, client_secret: str) -> str:
    """Exchange client credentials for a bearer token (~48h lifetime)."""
    response = session.post(
        _auth_url(region),
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _format_last_modified(value: Any) -> str:
    """Format a cursor for a lastModifiedAt query predicate (ISO 8601 UTC with ms)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00.000Z")
    return str(value)


def _build_url(
    base_url: str,
    config: CommercetoolsEndpointConfig,
    anchor: Optional[str],
    offset: int,
) -> str:
    # lastModifiedAt-ascending order keeps the incremental watermark monotonic;
    # `withTotal=false` skips an expensive count on every page.
    params: list[tuple[str, Any]] = [
        ("limit", PAGE_SIZE),
        ("offset", offset),
        ("sort", "lastModifiedAt asc"),
        ("withTotal", "false"),
    ]
    if anchor is not None:
        # `>=` re-fetches boundary rows (merge dedupes on primary key) so rows
        # sharing the anchor timestamp are never skipped.
        params.append(("where", f'lastModifiedAt >= "{anchor}"'))
    return f"{base_url}{config.path}?{urlencode(params)}"


def validate_credentials(region: str, project_key: str, client_id: str, client_secret: str) -> bool:
    """Confirm the API client is valid by minting a token — scopes are granted
    per resource, so a successful mint is the only universal probe."""
    try:
        _validate_path_component(project_key, "project key")
        _mint_token(_get_session(client_secret), region, client_id, client_secret)
        return True
    except Exception:
        return False


def get_rows(
    region: str,
    project_key: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CommercetoolsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = COMMERCETOOLS_ENDPOINTS[endpoint]
    session = _get_session(client_secret)
    base_url = _api_base_url(region, project_key)
    token = _mint_token(session, region, client_id, client_secret)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        anchor: Optional[str] = resume_config.anchor
        offset = resume_config.offset
        logger.debug(f"commercetools: resuming {endpoint} from anchor={anchor}, offset={offset}")
    else:
        anchor = (
            _format_last_modified(db_incremental_field_last_value)
            if should_use_incremental_field and db_incremental_field_last_value is not None
            else None
        )
        offset = 0

    @retry(
        retry=retry_if_exception_type((CommercetoolsRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        nonlocal token
        response = session.get(page_url, headers={"Authorization": f"Bearer {token}"}, timeout=REQUEST_TIMEOUT_SECONDS)

        # Tokens last ~48h; re-mint once if the sync outlives one.
        if response.status_code == 401:
            token = _mint_token(session, region, client_id, client_secret)
            response = session.get(
                page_url, headers={"Authorization": f"Bearer {token}"}, timeout=REQUEST_TIMEOUT_SECONDS
            )

        if response.status_code == 429 or response.status_code >= 500:
            raise CommercetoolsRetryableError(
                f"commercetools API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(
                f"commercetools API error: status={response.status_code}, body={response.text}, url={page_url}"
            )
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(_build_url(base_url, config, anchor, offset))
        items = data["results"] or []

        if items:
            yield items

        if len(items) < PAGE_SIZE:
            break

        offset += PAGE_SIZE
        if offset >= MAX_OFFSET:
            # Re-anchor the window on the latest lastModifiedAt seen to step
            # past the hard offset cap. The strict-advance guard prevents an
            # infinite loop if 10k+ rows share the boundary timestamp.
            next_anchor = max((item.get("lastModifiedAt") or "") for item in items)
            if not next_anchor or next_anchor == anchor:
                logger.error(
                    f"commercetools: cannot advance past offset cap on {endpoint} "
                    f"(anchor={anchor}); stopping to avoid an infinite loop"
                )
                break
            anchor = next_anchor
            offset = 0
            logger.debug(f"commercetools: re-anchoring {endpoint} at lastModifiedAt >= {anchor}")

        # Save state AFTER yielding the page so a crash re-yields the last page
        # (merge dedupes on primary key) rather than skipping it.
        resumable_source_manager.save_state(CommercetoolsResumeConfig(anchor=anchor, offset=offset))


def commercetools_source(
    region: str,
    project_key: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CommercetoolsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = COMMERCETOOLS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            region=region,
            project_key=project_key,
            client_id=client_id,
            client_secret=client_secret,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
        sort_mode="asc",
    )
