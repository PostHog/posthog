import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.guru.settings import (
    GURU_ENDPOINTS,
    GuruEndpointConfig,
)

GURU_BASE_URL = "https://api.getguru.com/api/v1"
GURU_API_HOST = "api.getguru.com"
REQUEST_TIMEOUT_SECONDS = 60
# Guru's rate limits are not publicly documented — be conservative and honor 429s.
MAX_RETRY_ATTEMPTS = 5


class GuruRetryableError(Exception):
    pass


class GuruHostNotAllowedError(Exception):
    pass


def _is_same_host(url: str) -> bool:
    """Whether ``url`` points at the canonical Guru API host.

    Pagination/resume URLs are server-controlled (they arrive in the Link header), so we
    pin them to the validated host to avoid being redirected at an arbitrary internal
    address (SSRF) and leaking the Basic auth credentials carried on every request.
    """
    try:
        return (urlparse(url).hostname or "").lower() == GURU_API_HOST
    except Exception:
        return False


@dataclasses.dataclass
class GuruResumeConfig:
    # Guru pagination follows a `Link: <url>; rel="next-page"` header whose URL is
    # self-contained (opaque continuation token), so the URL is all we persist.
    next_url: str


def _get_session(api_token: str) -> requests.Session:
    # allow_redirects=False so a 3xx can't silently move the credentialed request off the
    # validated host (SSRF). See _NoRedirectSession in common/http/transport.py.
    return make_tracked_session(redact_values=(api_token,), allow_redirects=False)


def _format_last_modified(value: Any) -> str:
    """Format an incremental cursor for a Guru Query Language date filter.

    GQL absolute dates require an ISO 8601 value with an explicit timezone
    (e.g. 2016-01-01T00:00:00+00:00)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _build_params(
    config: GuruEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, str]:
    params = dict(config.extra_params)

    if not config.incremental_fields:
        return params

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        cursor_field = incremental_field or config.incremental_fields[0]["field"]
        params["q"] = f"{cursor_field} >= {_format_last_modified(db_incremental_field_last_value)}"
        # Ascending order on the cursor field so the incremental watermark advances
        # monotonically as pages are consumed.
        params["sortField"] = cursor_field
        params["sortOrder"] = "asc"
    else:
        # Full refresh: sort on the stable creation date so rows modified mid-sync
        # don't move across page boundaries (lastModified is Guru's default sort).
        params["sortField"] = "dateCreated"
        params["sortOrder"] = "asc"

    return params


def _build_url(path: str, params: dict[str, str]) -> str:
    if not params:
        return f"{GURU_BASE_URL}{path}"
    return f"{GURU_BASE_URL}{path}?{urlencode(params)}"


def _normalize_member(item: dict[str, Any]) -> dict[str, Any]:
    # Team member rows nest the identifying email under `user`; copy it to the top
    # level so it can serve as the primary key. Use direct access so a member missing
    # the email surfaces a fast KeyError instead of a row with a null primary key.
    if "email" not in item and isinstance(item.get("user"), dict):
        return {**item, "email": item["user"]["email"]}
    return item


def validate_credentials(username: str, api_token: str) -> bool:
    """Confirm the user token is valid. /whoami is a cheap authenticated probe."""
    try:
        response = _get_session(api_token).get(
            f"{GURU_BASE_URL}/whoami",
            auth=(username, api_token),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    username: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GuruResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = GURU_ENDPOINTS[endpoint]
    session = _get_session(api_token)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None and _is_same_host(resume_config.next_url):
        url: str = resume_config.next_url
        logger.debug(f"Guru: resuming {endpoint} from URL: {url}")
    else:
        if resume_config is not None:
            logger.warning("Guru: ignoring resume URL whose host does not match the Guru API host")
        url = _build_url(
            config.path,
            _build_params(config, should_use_incremental_field, db_incremental_field_last_value, incremental_field),
        )

    @retry(
        retry=retry_if_exception_type((GuruRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> requests.Response:
        response = session.get(page_url, auth=(username, api_token), timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise GuruRetryableError(f"Guru API error (retryable): status={response.status_code}, url={page_url}")

        # A 3xx isn't an error status (`response.ok` is True), so reject it explicitly rather
        # than silently parsing the redirect body as data — we never follow redirects (SSRF).
        if response.is_redirect or response.is_permanent_redirect:
            raise GuruHostNotAllowedError(
                f"Guru API returned an unexpected redirect (status={response.status_code}); refusing to follow it"
            )

        if not response.ok:
            logger.error(f"Guru API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response

    while True:
        response = fetch_page(url)
        data = response.json()
        items = data if isinstance(data, list) else []

        if endpoint == "members":
            items = [_normalize_member(item) for item in items]

        if items:
            yield items

        next_url = response.links.get("next-page", {}).get("url")
        if not next_url:
            break

        # The next-page URL is server-controlled; only follow it if it stays on the Guru
        # API host so a tampered response can't aim the credentialed request elsewhere (SSRF).
        if not _is_same_host(next_url):
            logger.warning("Guru: stopping pagination, next URL host does not match the Guru API host")
            break

        # Save state AFTER yielding the page so a crash re-yields the last page
        # (merge dedupes on primary key) rather than skipping it.
        resumable_source_manager.save_state(GuruResumeConfig(next_url=next_url))
        url = next_url


def guru_source(
    username: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GuruResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = GURU_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            username=username,
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
