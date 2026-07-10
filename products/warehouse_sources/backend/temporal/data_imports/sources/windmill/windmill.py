import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.windmill.settings import (
    WINDMILL_ENDPOINTS,
    WindmillEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5
PER_PAGE = 100

HOST_NOT_ALLOWED_ERROR = "Windmill instance URL is not allowed"


class WindmillRetryableError(Exception):
    pass


class WindmillHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class WindmillResumeConfig:
    # 1-based index of the last-yielded page, so a resume re-fetches it and merge dedupes on the
    # primary key.
    page: int


def normalize_base_url(url: str) -> str:
    """Return the API root (``https://<host>/api``) for a user-supplied Windmill instance URL.

    Forces https (matching the Okta/ServiceNow/Braze connectors that also take a user-supplied
    host), strips any trailing slash, and tolerates the user pasting a URL that already ends in
    ``/api`` so we never build ``/api/api``.

    The authority is rebuilt from the parsed host (and port) alone, dropping any userinfo, query,
    or fragment. This keeps the host we SSRF-check identical to the host requests actually connects
    to — an embedded ``user@`` or trailing ``?``/``#`` can't make the checked authority diverge
    from the effective one.
    """
    stripped = re.sub(r"^https?://", "", url.strip(), flags=re.IGNORECASE)
    parsed = urlparse(f"https://{stripped}")
    host = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError:
        port = None
    netloc = f"{host}:{port}" if port else host
    path = parsed.path.rstrip("/")
    if path.lower().endswith("/api"):
        path = path[: -len("/api")]
    return f"https://{netloc}{path}/api"


def _host_from_url(base_url: str) -> str:
    return (urlparse(normalize_base_url(base_url)).hostname or "").lower()


def _workspace_url(base_url: str, workspace: str, path: str) -> str:
    return f"{normalize_base_url(base_url)}/w/{quote(workspace, safe='')}{path}"


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _format_after(value: Any) -> str:
    """Format an incremental cursor value as an RFC 3339 timestamp for Windmill's *_after filters."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _build_params(
    config: WindmillEndpointConfig,
    page: int,
    incremental_field: str | None,
    after_value: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if config.paginated:
        params["page"] = page
        params["per_page"] = PER_PAGE
    if config.supports_order_desc:
        # Ascending so rows inserted mid-sync append at the end instead of shifting earlier pages,
        # and so the incremental watermark advances monotonically.
        params["order_desc"] = "false"

    after_param = config.incremental_after_params.get(incremental_field or "")
    if after_param and after_value:
        params[after_param] = after_value

    return params


def _normalize_items(items: Any) -> list[dict[str, Any]]:
    """Windmill list endpoints return bare JSON arrays; keep only object rows."""
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def validate_credentials(
    api_token: str, base_url: str, workspace: str, team_id: int | None = None
) -> tuple[bool, str | None]:
    """Probe ``/w/{workspace}/users/whoami`` to confirm the token can reach the workspace."""
    # The instance URL is fully customer-controlled, so block hosts that resolve to
    # private/internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(_host_from_url(base_url), team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    url = _workspace_url(base_url, workspace, "/users/whoami")
    # Redact the bearer token wherever the tracked adapter records request samples — the
    # Authorization header uses a scheme the name-based scrubbers don't cover.
    session = make_tracked_session(allow_redirects=False, redact_values=(api_token,))
    try:
        response = session.get(url, headers=_get_headers(api_token), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Windmill API token"
    if response.status_code in (403, 404):
        return False, f"Could not access Windmill workspace '{workspace}' with this token"

    try:
        message = response.json().get("message", response.text)
    except Exception:
        message = response.text
    return False, message


def get_rows(
    api_token: str,
    base_url: str,
    workspace: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[WindmillResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = WINDMILL_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)

    # Re-check at run time (not just at source-create) in case the URL was edited or now resolves
    # to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _is_host_safe(_host_from_url(base_url), team_id)
    if not host_ok:
        raise WindmillHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

    after_value: str | None = None
    if (
        incremental_field in config.incremental_after_params
        and should_use_incremental_field
        and db_incremental_field_last_value
    ):
        after_value = _format_after(db_incremental_field_last_value)

    # Redact the bearer token wherever the tracked adapter records request samples — the
    # Authorization header uses a scheme the name-based scrubbers don't cover. One session is
    # reused across every page so the redaction applies to all requests.
    session = make_tracked_session(allow_redirects=False, redact_values=(api_token,))

    @retry(
        retry=retry_if_exception_type((WindmillRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(page: int) -> list[dict[str, Any]]:
        params = _build_params(config, page, incremental_field, after_value)
        page_url = _workspace_url(base_url, workspace, config.path)
        if params:
            page_url = f"{page_url}?{urlencode(params)}"
        response = session.get(page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise WindmillRetryableError(
                f"Windmill API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"Windmill API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return _normalize_items(response.json())

    # listUsers ignores pagination params and returns every row at once; a single request avoids
    # re-fetching the same full list forever.
    if not config.paginated:
        items = fetch_page(1)
        if items:
            yield items
        return

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    # A saved page number only indexes into a fixed result set. When an incremental watermark is
    # active it may have advanced since the page was saved (a partial run commits rows and moves
    # the cursor), which reshuffles the filtered pages so page N would skip earlier unsynced rows.
    # Restart from page 1 in that case; the watermark still bounds the scan and merge dedupes.
    if after_value is not None:
        resume_config = None
    page = resume_config.page if resume_config is not None else 1
    if resume_config is not None:
        logger.debug(f"Windmill: resuming {endpoint} from page={page}")

    while True:
        items = fetch_page(page)
        if not items:
            break

        yield items

        # Save the page we just yielded (not the next one) so a resume re-fetches it; merge
        # semantics on the primary key dedupe.
        resumable_source_manager.save_state(WindmillResumeConfig(page=page))

        if len(items) < PER_PAGE:
            break
        page += 1


def windmill_source(
    api_token: str,
    base_url: str,
    workspace: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[WindmillResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = WINDMILL_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            base_url=base_url,
            workspace=workspace,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            team_id=team_id,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        # We always request ascending order where the API allows it, so incremental watermarks
        # advance safely batch by batch.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format=config.partition_format if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
