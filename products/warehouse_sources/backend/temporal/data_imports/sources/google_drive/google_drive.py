import json
import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
import structlog
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.google_drive.oauth import (
    INTEGRATION_TOKEN_RECHECK_SECONDS,
    MISSING_INTEGRATION_ID_ERROR,
    resolve_google_drive_oauth_token,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_drive.settings import (
    DRIVE_FIELDS,
    GOOGLE_DRIVE_ENDPOINTS,
    GoogleDriveEndpointConfig,
)

# Drive API v3 is the only current version; v2 is retired. The version is a path segment, so the
# resolved pin is threaded into the base URL rather than hardcoded here.
GOOGLE_DRIVE_API_VERSION_V3 = "v3"
GOOGLE_DRIVE_API_BASE = "https://www.googleapis.com/drive"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Read-only is all this source ever needs; asking for less than `drive.readonly` (e.g.
# `drive.metadata.readonly`) would block listing shared drives.
DRIVE_READONLY_SCOPES = ("https://www.googleapis.com/auth/drive.readonly",)

REQUEST_TIMEOUT_SECONDS = 60
VALIDATION_TIMEOUT_SECONDS = 10
# Re-mint a little before expiry so a long page walk never sends a token that lapses in flight.
TOKEN_EXPIRY_MARGIN_SECONDS = 120
DEFAULT_TOKEN_LIFETIME_SECONDS = 3600

MISSING_SERVICE_ACCOUNT_KEY_ERROR = "Missing Google Drive service account key"
INVALID_SERVICE_ACCOUNT_KEY_ERROR = (
    "Invalid Google Drive service account key: expected the JSON key file contents, "
    "including client_email and private_key"
)
AUTH_FAILED_ERROR_PREFIX = "Google Drive authentication failed"
RATE_LIMIT_ERROR_PREFIX = "Google Drive rate limit"

# Drive reports quota exhaustion as a 403 with a rate-limit reason rather than a 429, so the
# transport's status-code retries never see it. These reasons clear on their own, unlike every
# other 403 (missing scope, API not enabled, no access to the file).
_RETRYABLE_403_REASONS = frozenset(
    {
        "ratelimitexceeded",
        "userratelimitexceeded",
        "quotaexceeded",
        "sharingratelimitexceeded",
        "backenderror",
        "internalerror",
    }
)

logger = structlog.get_logger(__name__)


class GoogleDriveAuthError(Exception):
    pass


class GoogleDriveRetryableError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class GoogleDriveAuth:
    """Either a service account JSON key (optionally impersonating a Workspace user through
    domain-wide delegation) or a Google account connected to PostHog's OAuth app, referenced by its
    integration row so the token is read fresh rather than captured at config time."""

    service_account_key: Optional[str] = None
    impersonated_user_email: Optional[str] = None
    integration_id: Optional[int] = None
    team_id: Optional[int] = None


@dataclasses.dataclass
class GoogleDriveResumeConfig:
    # Drive's opaque nextPageToken. None means "start this list from its first page".
    page_token: Optional[str] = None
    # Fan-out bookmark: the shared drive currently being processed. A stable id (not a positional
    # index) so drives added or removed between a crash and the retry can't resume the wrong drive.
    drive_id: Optional[str] = None


def _parse_service_account_key(raw: str) -> dict[str, Any]:
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as e:
        raise GoogleDriveAuthError(INVALID_SERVICE_ACCOUNT_KEY_ERROR) from e

    if not isinstance(info, dict) or not info.get("client_email") or not info.get("private_key"):
        raise GoogleDriveAuthError(INVALID_SERVICE_ACCOUNT_KEY_ERROR)

    # Pin the token endpoint rather than honoring a caller-supplied one: google-auth calls it
    # during credential refresh, so a submitted key naming an internal URL would turn this worker
    # into an SSRF vector. This source only ever talks to Google's token endpoint.
    info["token_uri"] = GOOGLE_TOKEN_URL
    return info


def _format_drive_datetime(value: Any) -> str:
    """Format an incremental cursor value as the RFC 3339 string Drive's search syntax expects."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    else:
        return str(value)

    parsed = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _error_reason(response: requests.Response) -> str:
    """Lowercased `error.errors[0].reason` from a Google error envelope, or ""."""
    try:
        payload = response.json()
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if not isinstance(error, dict):
        return ""
    errors = error.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        reason = errors[0].get("reason")
        if isinstance(reason, str):
            return reason.lower()
    status = error.get("status")
    return status.lower() if isinstance(status, str) else ""


class GoogleDriveClient:
    """Bearer-token Drive client over the tracked session.

    Both auth methods produce a short-lived bearer token, so the client owns fetching, caching, and
    re-fetching it: minted locally from the service account key, or read (and refreshed) off the
    integration row for the OAuth path. Neither session captures HTTP samples: the token exchange
    body is the access token itself, and Drive responses carry tenant metadata the name-based
    scrubbers can't recognise.
    """

    def __init__(
        self,
        auth: GoogleDriveAuth,
        api_version: str = GOOGLE_DRIVE_API_VERSION_V3,
        request_logger: Optional[FilteringBoundLogger] = None,
    ) -> None:
        self._auth = auth
        self._logger: FilteringBoundLogger = request_logger or logger
        self._base_url = f"{GOOGLE_DRIVE_API_BASE}/{api_version}"
        self._service_account_info: Optional[dict[str, Any]] = (
            _parse_service_account_key(auth.service_account_key) if auth.service_account_key else None
        )
        redact_values = self._redact_values()
        # Both sessions disable sample capture. Drive responses carry tenant file names, owner and
        # sharing identities, permission email addresses, and access URLs that the name-based
        # scrubbers can't recognise, so keeping them out of the shared sample prefix is the only way
        # to hold them to the warehouse table's access controls. The token exchange is excluded for
        # the same reason: its body is the access token itself.
        self._session = make_tracked_session(
            headers={"Accept": "application/json"}, redact_values=redact_values, capture=False
        )
        self._token_session = make_tracked_session(redact_values=redact_values, capture=False)
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    def _redact_values(self) -> tuple[str, ...]:
        # The OAuth path's only secret is the bearer token, and it only ever rides the Authorization
        # header, which the tracked transport already scrubs by name.
        private_key = (self._service_account_info or {}).get("private_key")
        return (private_key,) if isinstance(private_key, str) and private_key else ()

    def _fetch_access_token(self, force_refresh: bool) -> tuple[str, float]:
        if self._service_account_info is not None:
            return self._mint_service_account_token(self._service_account_info)
        return self._integration_access_token(force_refresh)

    def _mint_service_account_token(self, info: dict[str, Any]) -> tuple[str, float]:
        try:
            credentials = service_account.Credentials.from_service_account_info(
                info,
                scopes=list(DRIVE_READONLY_SCOPES),
                subject=self._auth.impersonated_user_email or None,
            )
        except ValueError as e:
            raise GoogleDriveAuthError(INVALID_SERVICE_ACCOUNT_KEY_ERROR) from e

        try:
            credentials.refresh(GoogleAuthRequest(session=self._token_session))
        except Exception as e:
            raise GoogleDriveAuthError(f"{AUTH_FAILED_ERROR_PREFIX}: {e}") from e

        token = credentials.token
        if not isinstance(token, str) or not token:
            raise GoogleDriveAuthError(f"{AUTH_FAILED_ERROR_PREFIX}: no access token was returned")

        expiry = credentials.expiry
        if isinstance(expiry, datetime):
            # google-auth stores expiry as a naive UTC datetime.
            aware = expiry.replace(tzinfo=UTC) if expiry.tzinfo is None else expiry
            return token, aware.timestamp()
        return token, time.time() + DEFAULT_TOKEN_LIFETIME_SECONDS

    def _integration_access_token(self, force_refresh: bool) -> tuple[str, float]:
        if self._auth.integration_id is None or self._auth.team_id is None:
            raise GoogleDriveAuthError(MISSING_INTEGRATION_ID_ERROR)

        try:
            token = resolve_google_drive_oauth_token(
                self._auth.integration_id, self._auth.team_id, force_refresh=force_refresh
            )
        except ValueError as e:
            raise GoogleDriveAuthError(str(e)) from e

        return token, time.time() + INTEGRATION_TOKEN_RECHECK_SECONDS

    def access_token(self, force_refresh: bool = False) -> str:
        if (
            force_refresh
            or self._access_token is None
            or time.time() >= self._token_expires_at - TOKEN_EXPIRY_MARGIN_SECONDS
        ):
            self._access_token, self._token_expires_at = self._fetch_access_token(force_refresh)
        return self._access_token

    def _send(self, url: str, params: dict[str, str], timeout: float, force_token_refresh: bool) -> requests.Response:
        token = self.access_token(force_refresh=force_token_refresh)
        return self._session.get(url, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=timeout)

    def get(self, path: str, params: dict[str, str], timeout: float = REQUEST_TIMEOUT_SECONDS) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        response = self._send(url, params, timeout, force_token_refresh=False)

        if response.status_code == 401:
            # A cached token can be invalidated before its stated expiry (key rotated, grant
            # revoked, impersonation withdrawn mid-sync). Re-mint once before calling it fatal.
            response = self._send(url, params, timeout, force_token_refresh=True)

        if response.status_code == 403:
            reason = _error_reason(response)
            if reason in _RETRYABLE_403_REASONS:
                raise GoogleDriveRetryableError(f"{RATE_LIMIT_ERROR_PREFIX} (retryable): reason={reason}, url={url}")

        if not response.ok:
            self._logger.error(
                f"Google Drive API error: status={response.status_code}, body={response.text[:500]}, url={url}"
            )
            response.raise_for_status()

        payload = response.json()
        return payload if isinstance(payload, dict) else {}


@retry(
    # Only the app-level 403 rate-limit condition is retried here: the tracked session already
    # retries 429 and 5xx, so wrapping those again would compound the attempts.
    retry=retry_if_exception_type(GoogleDriveRetryableError),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _fetch_page(client: GoogleDriveClient, path: str, params: dict[str, str]) -> dict[str, Any]:
    return client.get(path, params)


def validate_credentials(
    auth: GoogleDriveAuth, api_version: str = GOOGLE_DRIVE_API_VERSION_V3
) -> tuple[bool, str | None]:
    """Probe `about.get` — the cheapest call that proves the minted token really reaches Drive."""
    try:
        client = GoogleDriveClient(auth, api_version)
        client.get("/about", {"fields": "user,storageQuota"}, timeout=VALIDATION_TIMEOUT_SECONDS)
    except GoogleDriveAuthError as e:
        return False, str(e)
    except GoogleDriveRetryableError:
        return False, "Google Drive is rate limiting this account right now. Please try again in a moment."
    except requests.HTTPError as e:
        response = e.response
        status = response.status_code if response is not None else None
        if status == 401:
            return False, "Google Drive rejected these credentials. Reconnect the account or check the key."
        if status == 403:
            reason = _error_reason(response) if response is not None else ""
            if reason == "accessnotconfigured":
                return (
                    False,
                    "The Google Drive API is not enabled for this Google Cloud project. Enable it, then try again.",
                )
            return (
                False,
                "These credentials cannot read Drive. Grant the drive.readonly scope "
                "(and, for a service account, share the files or set up domain-wide delegation).",
            )
        return False, f"Google Drive returned status {status}"
    except requests.exceptions.RequestException as e:
        return False, str(e)

    return True, None


def _build_initial_params(
    config: GoogleDriveEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
    drive_id: str | None,
) -> dict[str, str]:
    params: dict[str, str] = {"pageSize": str(config.page_size), "fields": config.response_fields}
    params.update(config.extra_params)

    if config.applies_drive_scope:
        params["supportsAllDrives"] = "true"
        params["includeItemsFromAllDrives"] = "true"
        if drive_id:
            params["corpora"] = "drive"
            params["driveId"] = drive_id

    cursor_field = incremental_field or config.default_incremental_field
    is_incremental_run = (
        cursor_field is not None
        and cursor_field in config.search_filter_fields
        and should_use_incremental_field
        and db_incremental_field_last_value is not None
    )

    if is_incremental_run and cursor_field is not None:
        params["q"] = f"{cursor_field} > '{_format_drive_datetime(db_incremental_field_last_value)}'"
        if config.supports_order_by:
            # Ascending on the cursor field, so new rows append past the walk instead of shifting
            # pages we've already fetched.
            params["orderBy"] = cursor_field
    elif config.supports_order_by and config.stable_order_by:
        params["orderBy"] = config.stable_order_by

    return params


def _page_items(data: dict[str, Any], config: GoogleDriveEndpointConfig) -> list[dict[str, Any]]:
    items = data.get(config.data_path)
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _normalize_permission_row(row: dict[str, Any], drive: dict[str, Any]) -> dict[str, Any]:
    # Permission rows carry no reference back to the file they belong to, and the composite
    # primary key needs the parent drive as a stable top-level column.
    return {**row, "drive_id": drive.get("id"), "drive_name": drive.get("name")}


def _iter_shared_drives(client: GoogleDriveClient) -> Iterator[dict[str, Any]]:
    """Page through the shared drives the credentials can see, in Drive's own order (stable
    enough across attempts: the fan-out bookmark is the drive id, not a position)."""
    params = {"pageSize": "100", "fields": f"nextPageToken,drives({','.join(DRIVE_FIELDS)})"}
    page_token: str | None = None
    while True:
        page_params = dict(params)
        if page_token:
            page_params["pageToken"] = page_token
        data = _fetch_page(client, "/drives", page_params)
        drives = data.get("drives")
        if isinstance(drives, list):
            yield from (drive for drive in drives if isinstance(drive, dict) and drive.get("id"))
        next_token = data.get("nextPageToken")
        if not isinstance(next_token, str) or not next_token:
            break
        page_token = next_token


def _get_top_level_rows(
    client: GoogleDriveClient,
    config: GoogleDriveEndpointConfig,
    params: dict[str, str],
    resumable_source_manager: ResumableSourceManager[GoogleDriveResumeConfig],
    source_logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page_token = resume.page_token if resume is not None else None
    if page_token:
        source_logger.debug(f"Google Drive: resuming {config.name} from a saved page token")

    while True:
        page_params = dict(params)
        if page_token:
            page_params["pageToken"] = page_token

        data = _fetch_page(client, config.path, page_params)
        items = _page_items(data, config)
        next_token = data.get("nextPageToken")
        next_token = next_token if isinstance(next_token, str) and next_token else None

        if items:
            yield items
            # Save AFTER yielding (and only while pages remain) so a crash re-yields the last page
            # rather than skipping it — the merge dedupes on the primary key.
            if next_token:
                resumable_source_manager.save_state(GoogleDriveResumeConfig(page_token=next_token))

        if not next_token:
            break
        page_token = next_token


def _get_fan_out_rows(
    client: GoogleDriveClient,
    config: GoogleDriveEndpointConfig,
    params: dict[str, str],
    resumable_source_manager: ResumableSourceManager[GoogleDriveResumeConfig],
    source_logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    drives = list(_iter_shared_drives(client))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = drives
    resume_page_token: str | None = None
    if resume is not None and resume.drive_id is not None:
        drive_ids = [drive["id"] for drive in drives]
        if resume.drive_id in drive_ids:
            remaining = drives[drive_ids.index(resume.drive_id) :]
            resume_page_token = resume.page_token
            source_logger.debug(f"Google Drive: resuming {config.name} from drive={resume.drive_id}")

    for index, drive in enumerate(remaining):
        drive_id = str(drive["id"])
        path = config.path.format(drive_id=drive_id)
        page_token = resume_page_token
        resume_page_token = None  # only the resumed-into drive starts mid-list

        try:
            while True:
                page_params = dict(params)
                if page_token:
                    page_params["pageToken"] = page_token

                data = _fetch_page(client, path, page_params)
                items = _page_items(data, config)
                next_token = data.get("nextPageToken")
                next_token = next_token if isinstance(next_token, str) and next_token else None

                if items:
                    yield [_normalize_permission_row(item, drive) for item in items]
                    if next_token:
                        resumable_source_manager.save_state(
                            GoogleDriveResumeConfig(page_token=next_token, drive_id=drive_id)
                        )

                if not next_token:
                    break
                page_token = next_token
        except requests.HTTPError as e:
            # A drive deleted between enumeration and this fetch 404s, and a drive whose permissions
            # the credentials can't read 403s. Skip that drive instead of failing every other one;
            # anything else is a real failure.
            status = e.response.status_code if e.response is not None else None
            if status in (403, 404):
                source_logger.warning(
                    f"Google Drive: {config.name} not readable for drive {drive_id} (status {status}), skipping"
                )
            else:
                raise

        # Advance the bookmark to the next drive so a crash between drives resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(GoogleDriveResumeConfig(drive_id=str(remaining[index + 1]["id"])))


def get_rows(
    auth: GoogleDriveAuth,
    endpoint: str,
    api_version: str,
    source_logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GoogleDriveResumeConfig],
    drive_id: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = GOOGLE_DRIVE_ENDPOINTS[endpoint]
    # One client (and one minted token) reused across every page and, for fan-out, every drive.
    client = GoogleDriveClient(auth, api_version, request_logger=source_logger)
    params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field, drive_id
    )

    if config.fan_out_over_drives:
        yield from _get_fan_out_rows(client, config, params, resumable_source_manager, source_logger)
    else:
        yield from _get_top_level_rows(client, config, params, resumable_source_manager, source_logger)


def google_drive_source(
    auth: GoogleDriveAuth,
    endpoint: str,
    api_version: str,
    source_logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GoogleDriveResumeConfig],
    drive_id: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = GOOGLE_DRIVE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            auth=auth,
            endpoint=endpoint,
            api_version=api_version,
            source_logger=source_logger,
            resumable_source_manager=resumable_source_manager,
            drive_id=drive_id,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=list(config.primary_keys),
        # files.list is asked to order ascending on the cursor field, so per-batch watermark
        # checkpointing is safe. Drive documents one caveat: for accounts with roughly a million
        # or more files the requested order can be dropped. The resume state keeps a restarted
        # attempt on the same page, so the exposure is limited to that extreme case.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
