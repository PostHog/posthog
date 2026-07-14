"""Platform.sh (Upsun) transport layer.

Platform.sh's REST API is a HAL-style JSON surface behind a short-lived OAuth2 bearer token. The
user supplies a long-lived API token (created in the Console), which we exchange for a ~15-minute
access token via `POST {auth_host}/oauth2/token` with HTTP basic auth `platform-api-user:` and
`grant_type=api_token` (verified against the live auth endpoints for both brands). The client
re-exchanges proactively before expiry and once reactively on a 401 mid-run.

Two brand host pairs exist for the same API: api.platform.sh + auth.api.platform.sh (Platform.sh)
and api.upsun.com + auth.upsun.com (Upsun). The user picks the brand in the source form.

Organization-level lists return an `{"items": [...], "_links": {...}}` envelope with cursor
pagination (`page[size]`, `_links.next.href`). Project-scoped lists return bare JSON arrays; the
activities feed is newest-first and pages backwards through history via `count` + `starts_at`
(params absent from the OpenAPI spec but used by the official Platform.sh PHP client and CLI, which
page by setting `starts_at` to the oldest `created_at` seen and dedupe by id).

Fan-out: organizations -> projects/subscriptions/members, and organizations -> projects ->
environments/activities. Resume state checkpoints the current organizations page URL after all its
children are processed; a resumed run re-fans that page and merge dedupes on the primary key.
"""

import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.platform_sh.settings import (
    PLATFORM_SH_ENDPOINTS,
    PlatformShEndpointConfig,
)

API_HOSTS = {
    "platform_sh": "https://api.platform.sh",
    "upsun": "https://api.upsun.com",
}
AUTH_HOSTS = {
    "platform_sh": "https://auth.api.platform.sh",
    "upsun": "https://auth.upsun.com",
}

# Access tokens are issued for ~900s; refresh this many seconds early so a request never rides an
# about-to-expire token across a slow response.
TOKEN_REFRESH_MARGIN_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 60

AUTH_FAILED_MESSAGE = "Platform.sh authentication failed"


@dataclasses.dataclass
class PlatformShResumeConfig:
    # Next URL to fetch. For the top-level organizations table it's the next page URL; for fan-out
    # tables it's the current organizations page URL (resume re-fans that page and its children,
    # merge dedupes on the primary key).
    next_url: str | None = None


class PlatformShRetryableError(Exception):
    pass


class PlatformShAuthenticationError(Exception):
    """Raised when the token exchange rejects the API token. Matched by
    `get_non_retryable_errors` — retrying can never satisfy a credential problem."""


class PlatformShUntrustedURLError(Exception):
    """Raised when a next-page/resume URL points off the configured API host. We attach the bearer
    token to every request, so following an off-host URL would leak it; refuse instead."""


class PlatformShPageCapExceededError(Exception):
    """Raised when a fan-out parent exceeds the per-parent page cap. Failing loudly beats silently
    writing an incomplete table that later runs would never backfill."""


class PlatformShClient:
    """Authenticated GET client: exchanges the API token for a bearer token, refreshes it before
    expiry and once reactively on 401, and pins every URL to the configured API host."""

    def __init__(self, api_token: str, platform: str, logger: FilteringBoundLogger) -> None:
        if platform not in API_HOSTS:
            raise ValueError(f"Platform.sh: unknown platform {platform!r}; expected one of {sorted(API_HOSTS)}")
        self.api_base = API_HOSTS[platform]
        self._parsed_base = urlparse(self.api_base)
        self._token_url = f"{AUTH_HOSTS[platform]}/oauth2/token"
        self._api_token = api_token
        self._logger = logger
        self._access_token: str | None = None
        self._token_deadline = 0.0
        # capture=False: environment responses carry `http_access.basic_auth` and activity
        # responses carry raw `log` output — secrets we strip client-side in `_clean_rows`, which
        # runs after HTTP sample capture would have recorded the raw body. Requests stay metered
        # and logged; only the opt-in body capture is excluded.
        self._session = make_tracked_session(redact_values=(api_token,), capture=False)

    def validate_url(self, url: str) -> str:
        """Reject a URL whose scheme or host differs from the configured API base.

        Next-page URLs come from remote `_links` payloads (and persisted resume state), and we send
        the bearer token with them. Pinning the scheme and host stops a tampered link from
        forwarding the token to an attacker-controlled server.
        """
        parsed = urlparse(url)
        if parsed.scheme != self._parsed_base.scheme or parsed.netloc != self._parsed_base.netloc:
            raise PlatformShUntrustedURLError(f"Platform.sh: refusing to follow off-host URL: {url}")
        return url

    @retry(
        retry=retry_if_exception_type((PlatformShRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def _exchange_token(self) -> None:
        # allow_redirects=False: requests preserves the POST body on 307/308 redirects, so
        # following one would re-send the long-lived API token to whatever host the redirect
        # names — the body isn't covered by requests' cross-host Authorization stripping.
        response = self._session.post(
            self._token_url,
            auth=("platform-api-user", ""),
            data={"grant_type": "api_token", "api_token": self._api_token},
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
        if 300 <= response.status_code < 400:
            raise PlatformShUntrustedURLError(
                f"Platform.sh: token endpoint responded with a redirect (status={response.status_code}); "
                "refusing to re-send the API token"
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise PlatformShRetryableError(
                f"Platform.sh token exchange error (retryable): status={response.status_code}"
            )
        if not response.ok:
            # 400/401 from the auth server means the API token itself was rejected.
            raise PlatformShAuthenticationError(
                f"{AUTH_FAILED_MESSAGE}: the API token was rejected by {self._token_url} "
                f"(status={response.status_code})"
            )
        payload = response.json()
        self._access_token = payload["access_token"]
        self._token_deadline = time.monotonic() + float(payload.get("expires_in", 900)) - TOKEN_REFRESH_MARGIN_SECONDS
        # Rebuild the session so the fresh bearer token is masked from tracked logs, same as the
        # long-lived API token; capture stays off (see __init__).
        self._session = make_tracked_session(redact_values=(self._api_token, self._access_token), capture=False)

    def _ensure_token(self) -> str:
        if self._access_token is None or time.monotonic() >= self._token_deadline:
            self._exchange_token()
        assert self._access_token is not None
        return self._access_token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._ensure_token()}",
            "Accept": "application/json",
            "User-Agent": "PostHog",
        }

    @retry(
        retry=retry_if_exception_type(
            (
                PlatformShRetryableError,
                requests.ReadTimeout,
                requests.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            )
        ),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def get(self, url: str) -> requests.Response:
        response = self._session.get(url, headers=self._headers(), timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 401:
            # The bearer token expires after ~15 minutes; re-exchange once and retry. A second 401
            # means the credential itself is broken and falls through to raise_for_status below.
            self._exchange_token()
            response = self._session.get(url, headers=self._headers(), timeout=REQUEST_TIMEOUT_SECONDS)

        # Rate limits aren't publicly documented; honor 429 and transient 5xx with backoff.
        if response.status_code == 429 or response.status_code >= 500:
            raise PlatformShRetryableError(
                f"Platform.sh API error (retryable): status={response.status_code}, url={url}"
            )

        if not response.ok:
            self._logger.error(f"Platform.sh API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response


def _build_url(api_base: str, path: str, page_size: int | None, page_size_param: str = "page[size]") -> str:
    url = f"{api_base}{path}"
    if page_size is not None:
        return f"{url}?{urlencode({page_size_param: page_size})}"
    return url


def _next_link(body: dict[str, Any], current_url: str, client: PlatformShClient) -> str | None:
    """Return the absolute, host-pinned URL of `_links.next.href`, if any. HAL links are typically
    relative ("/organizations?page[after]=..."), so resolve against the current request URL."""
    href = ((body.get("_links") or {}).get("next") or {}).get("href")
    if not href:
        return None
    return client.validate_url(urljoin(current_url, href))


def _iter_envelope_pages(
    client: PlatformShClient,
    url: str,
    max_pages: int | None = None,
    page_cap_context: dict[str, Any] | None = None,
) -> Iterator[tuple[list[dict[str, Any]], str]]:
    """Yield (items, page_url) for each page of an `{"items": [...], "_links": {...}}` list,
    following the `_links.next` cursor. When `max_pages` is set and more pages remain, raise
    rather than truncate: a silently short table would stay incomplete on every later run."""
    page_count = 0
    while True:
        body = client.get(url).json()
        items = body.get("items") if isinstance(body, dict) else None
        if not items:
            return
        next_url = _next_link(body, url, client)
        yield items, url
        page_count += 1
        if not next_url:
            return
        if max_pages is not None and page_count >= max_pages:
            raise PlatformShPageCapExceededError(
                f"Platform.sh: page cap of {max_pages} reached with more pages remaining; "
                f"raise max_pages_per_parent to sync this parent fully. context={page_cap_context or {}}"
            )
        url = next_url


def _strip_keys_recursive(value: Any, keys: list[str]) -> Any:
    """Return `value` with every dict entry whose key is in `keys` removed, at any depth.
    Credential blocks (environment `http_access.basic_auth`) can appear nested inside activity
    payloads at varying depths, so strip by key name rather than a fixed path."""
    if isinstance(value, dict):
        return {k: _strip_keys_recursive(v, keys) for k, v in value.items() if k not in keys}
    if isinstance(value, list):
        return [_strip_keys_recursive(item, keys) for item in value]
    return value


def _clean_rows(rows: list[dict[str, Any]], config: PlatformShEndpointConfig) -> list[dict[str, Any]]:
    if not config.drop_keys and not config.strip_keys_recursive:
        return rows
    cleaned: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            if config.drop_keys:
                row = {k: v for k, v in row.items() if k not in config.drop_keys}
            if config.strip_keys_recursive:
                row = _strip_keys_recursive(row, config.strip_keys_recursive)
        cleaned.append(row)
    return cleaned


def _inject_parent_fields(
    rows: list[dict[str, Any]], parent: dict[str, Any], field_map: dict[str, str] | None
) -> list[dict[str, Any]]:
    """Copy the mapped parent fields onto each child row. Direct access on the parent fields: the
    injected columns feed the child's composite primary key, so a parent missing one is a broken
    response that must fail loudly, not corrupt the key with None."""
    if not field_map:
        return rows
    injected = {child_column: parent[parent_field] for parent_field, child_column in field_map.items()}
    return [{**row, **injected} for row in rows]


def _coerce_datetime(value: Any) -> datetime:
    """Normalize a watermark or row timestamp to an aware UTC datetime for comparison."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day)
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError(f"Platform.sh: cannot interpret {value!r} as a datetime")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _iter_project_activities(
    client: PlatformShClient,
    project_id: str,
    logger: FilteringBoundLogger,
    config: PlatformShEndpointConfig,
    cutoff: datetime | None,
) -> Iterator[list[dict[str, Any]]]:
    """Walk one project's activity feed newest-first, paging backwards with `starts_at` (oldest
    `created_at` seen, mirroring the official CLI's ActivityLoader) and deduping by id. With a
    watermark set, stop once a page crosses below it — the server has no lower-bound filter, so
    the cutoff has to be client-side or every incremental sync would re-walk full history."""
    base_url = f"{client.api_base}{config.path.format(project_id=project_id)}"
    seen_ids: set[str] = set()
    starts_at: str | None = None
    page_count = 0

    while True:
        params: dict[str, Any] = {}
        if config.page_size is not None:
            params["count"] = config.page_size
        if starts_at is not None:
            params["starts_at"] = starts_at
        url = f"{base_url}?{urlencode(params)}" if params else base_url

        rows = client.get(url).json()
        if not isinstance(rows, list) or not rows:
            return
        # `starts_at` bounds pages by "created before"; ties at the boundary can re-return rows we
        # already have, so dedupe by id and stop when a page brings nothing new (feed exhausted).
        new_rows = [row for row in rows if row["id"] not in seen_ids]
        if not new_rows:
            return
        seen_ids.update(row["id"] for row in new_rows)

        if cutoff is not None:
            fresh = [row for row in new_rows if _coerce_datetime(row["created_at"]) >= cutoff]
            if fresh:
                yield fresh
            if len(fresh) < len(new_rows):
                # The page crossed the watermark; everything older was synced by a previous run.
                return
        else:
            yield new_rows

        page_count += 1
        if page_count >= config.max_pages_per_parent:
            raise PlatformShPageCapExceededError(
                f"Platform.sh: activity page cap of {config.max_pages_per_parent} reached for "
                f"project {project_id} with more history remaining; raise max_pages_per_parent."
            )
        starts_at = min(row["created_at"] for row in new_rows)


def _iter_project_children(
    client: PlatformShClient,
    project: dict[str, Any],
    logger: FilteringBoundLogger,
    config: PlatformShEndpointConfig,
    cutoff: datetime | None,
) -> Iterator[list[dict[str, Any]]]:
    project_id = project["id"]
    if config.name == "activities":
        raw_batches: Iterator[list[dict[str, Any]]] = _iter_project_activities(
            client, project_id, logger, config, cutoff
        )
    else:
        # Environments: a single unpaginated bare-array GET per project.
        url = f"{client.api_base}{config.path.format(project_id=project_id)}"
        data = client.get(url).json()
        raw_batches = iter([data] if isinstance(data, list) and data else [])

    for batch in raw_batches:
        yield _clean_rows(_inject_parent_fields(batch, project, config.include_parent_fields), config)


def get_rows(
    api_token: str,
    platform: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PlatformShResumeConfig],
    should_use_incremental_field: bool = False,
    incremental_field: str | None = None,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = PLATFORM_SH_ENDPOINTS[endpoint]
    client = PlatformShClient(api_token, platform, logger)

    cutoff: datetime | None = None
    if (
        config.name == "activities"
        and should_use_incremental_field
        # `created_at` is the only advertised cursor; honor the user's schema setting rather than
        # silently applying a cutoff to a field we weren't asked to use.
        and incremental_field == "created_at"
        and db_incremental_field_last_value is not None
    ):
        cutoff = _coerce_datetime(db_incremental_field_last_value)
        logger.debug(f"Platform.sh: syncing {endpoint} incrementally from {cutoff.isoformat()}")

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    orgs_url = _build_url(client.api_base, "/organizations", PLATFORM_SH_ENDPOINTS["organizations"].page_size)
    if resume is not None and resume.next_url:
        orgs_url = client.validate_url(resume.next_url)
        logger.debug(f"Platform.sh: resuming {endpoint} from organizations page: {orgs_url}")

    if endpoint == "organizations":
        while True:
            body = client.get(orgs_url).json()
            items = body.get("items") if isinstance(body, dict) else None
            if not items:
                return
            next_url = _next_link(body, orgs_url, client)
            yield _clean_rows(items, config)
            if not next_url:
                return
            # Save AFTER yielding so a crash re-yields the last page rather than skipping it
            # (merge dedupes on the primary key).
            resumable_source_manager.save_state(PlatformShResumeConfig(next_url=next_url))
            orgs_url = next_url

    # Fan-out tables: walk the organizations list and emit child rows per org (and, for
    # project-scoped tables, per project). Checkpoint the org page URL after all of its children
    # are processed; a resumed run re-fans that page and merge dedupes.
    for orgs, org_page_url in _iter_envelope_pages(client, orgs_url):
        for org in orgs:
            if config.fan_out_parent == "organizations":
                child_url = _build_url(client.api_base, config.path.format(organization_id=org["id"]), config.page_size)
                for child_items, _ in _iter_envelope_pages(
                    client,
                    child_url,
                    max_pages=config.max_pages_per_parent,
                    page_cap_context={"organization_id": org["id"], "endpoint": endpoint},
                ):
                    yield _clean_rows(_inject_parent_fields(child_items, org, config.include_parent_fields), config)
            else:  # children of projects (environments, activities)
                projects_config = PLATFORM_SH_ENDPOINTS["projects"]
                projects_url = _build_url(
                    client.api_base,
                    projects_config.path.format(organization_id=org["id"]),
                    projects_config.page_size,
                )
                for projects, _ in _iter_envelope_pages(
                    client,
                    projects_url,
                    max_pages=projects_config.max_pages_per_parent,
                    page_cap_context={"organization_id": org["id"], "endpoint": endpoint},
                ):
                    for project in projects:
                        yield from _iter_project_children(client, project, logger, config, cutoff)
        resumable_source_manager.save_state(PlatformShResumeConfig(next_url=org_page_url))


def validate_credentials(api_token: str, platform: str, logger: FilteringBoundLogger) -> tuple[bool, str | None]:
    """Exchange the API token and probe one cheap authenticated call. The token grants the same
    access as the user account (no granular scopes), so one probe confirms the whole credential."""
    try:
        client = PlatformShClient(api_token, platform, logger)
        client.get(_build_url(client.api_base, "/organizations", 1))
        return True, None
    except PlatformShAuthenticationError:
        return False, "Invalid Platform.sh API token"
    except Exception as e:
        return False, f"Could not connect to Platform.sh: {e}"


def platform_sh_source(
    api_token: str,
    platform: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PlatformShResumeConfig],
    should_use_incremental_field: bool = False,
    incremental_field: str | None = None,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    endpoint_config = PLATFORM_SH_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            platform=platform,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            incremental_field=incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Activities arrive newest-first across a per-project fan-out, so `desc` is the honest
        # mode: the pipeline only finalizes the incremental watermark after a fully successful
        # sync, which is required here because rows do not arrive in one global ascending stream.
        # (`db_incremental_field_earliest_value` — desc mid-run backfill scrolling à la Stripe —
        # is deliberately unused: the resumable manager checkpoints fan-out progress instead.)
        sort_mode=endpoint_config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
