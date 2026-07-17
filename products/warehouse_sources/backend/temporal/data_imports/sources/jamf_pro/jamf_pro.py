import re
import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Literal, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.jamf_pro.settings import (
    JAMF_PRO_ENDPOINTS,
    JamfProEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5

# Jamf Pro bearer tokens are short-lived (~20 minutes for basic-auth tokens; OAuth tokens report
# their own expires_in). Re-mint this many seconds before the deadline so a request never rides
# a token that expires mid-flight.
TOKEN_REFRESH_MARGIN_SECONDS = 60
DEFAULT_TOKEN_LIFETIME_SECONDS = 15 * 60

HOST_NOT_ALLOWED_ERROR = "Jamf Pro URL is not allowed"
INCOMPLETE_CREDENTIALS_ERROR = "Jamf Pro credentials are incomplete"


class JamfProRetryableError(Exception):
    pass


class JamfProHostNotAllowedError(Exception):
    pass


class JamfProConfigurationError(Exception):
    pass


@dataclasses.dataclass
class JamfProResumeConfig:
    # Zero-based page index to fetch next. Query params are rebuilt deterministically from the
    # schema inputs on resume, so the page number is the only state we need.
    page: int


@dataclasses.dataclass
class JamfProCredentials:
    method: Literal["client_credentials", "basic"]
    client_id: str | None = None
    client_secret: str | None = None
    username: str | None = None
    password: str | None = None


def normalize_host(host: str) -> str:
    """Turn whatever the user typed into a bare Jamf Pro host.

    Accepts values like ``company.jamfcloud.com``, ``https://company.jamfcloud.com/``,
    or ``company.jamfcloud.com/api`` and returns ``company.jamfcloud.com``.
    """
    host = host.strip()
    host = re.sub(r"^https?://", "", host, flags=re.IGNORECASE)
    host = host.split("/")[0]
    return host.strip().rstrip("/")


def _base_url(host: str) -> str:
    return f"https://{normalize_host(host)}"


def _format_datetime_z(dt: datetime) -> str:
    """Jamf Pro stores instants as ISO 8601 with millisecond precision and a ``Z`` suffix."""
    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _format_incremental_value(value: Any) -> str:
    if isinstance(value, datetime):
        return _format_datetime_z(value)
    if isinstance(value, date):
        return _format_datetime_z(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


class JamfProTokenManager:
    """Mints and caches the short-lived bearer token, re-minting before it expires.

    Supports the two Jamf Pro auth paths: OAuth2 client credentials (API Roles & Clients,
    ``POST /api/oauth/token``) and a user account over HTTP Basic (``POST /api/v1/auth/token``).
    """

    def __init__(self, session: requests.Session, host: str, credentials: JamfProCredentials) -> None:
        self._session = session
        self._base_url = _base_url(host)
        self._credentials = credentials
        self._token: str | None = None
        self._deadline: float = 0.0

    def get_token(self) -> str:
        if self._token is None or time.monotonic() >= self._deadline - TOKEN_REFRESH_MARGIN_SECONDS:
            self._mint()
        assert self._token is not None
        return self._token

    def _mint(self) -> None:
        response = self._request_token()

        if response.status_code == 429 or response.status_code >= 500:
            raise JamfProRetryableError(f"Jamf Pro token request failed (retryable): status={response.status_code}")

        # A 3xx isn't an error status, so reject it explicitly rather than following it to a
        # potentially internal Location (SSRF).
        if response.is_redirect or response.is_permanent_redirect:
            raise JamfProHostNotAllowedError(
                f"Jamf Pro API returned an unexpected redirect (status={response.status_code}); refusing to follow it"
            )

        response.raise_for_status()
        payload = response.json()

        if self._credentials.method == "client_credentials":
            self._token = payload["access_token"]
            lifetime = float(payload.get("expires_in") or DEFAULT_TOKEN_LIFETIME_SECONDS)
        else:
            self._token = payload["token"]
            lifetime = self._lifetime_from_expiry(payload.get("expires"))

        self._deadline = time.monotonic() + lifetime

    def _request_token(self) -> requests.Response:
        if self._credentials.method == "client_credentials":
            if not self._credentials.client_id or not self._credentials.client_secret:
                raise JamfProConfigurationError(f"{INCOMPLETE_CREDENTIALS_ERROR}: client ID and client secret required")
            return self._session.post(
                f"{self._base_url}/api/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._credentials.client_id,
                    "client_secret": self._credentials.client_secret,
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
                allow_redirects=False,
            )

        if not self._credentials.username or not self._credentials.password:
            raise JamfProConfigurationError(f"{INCOMPLETE_CREDENTIALS_ERROR}: username and password required")
        return self._session.post(
            f"{self._base_url}/api/v1/auth/token",
            auth=(self._credentials.username, self._credentials.password),
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=False,
        )

    @staticmethod
    def _lifetime_from_expiry(expires: str | None) -> float:
        if not expires:
            return DEFAULT_TOKEN_LIFETIME_SECONDS
        try:
            expiry = datetime.fromisoformat(expires.replace("Z", "+00:00"))
        except ValueError:
            return DEFAULT_TOKEN_LIFETIME_SECONDS
        return max((expiry - datetime.now(UTC)).total_seconds(), 0.0)


def _build_params(
    config: JamfProEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {"page-size": config.page_size}

    sort = config.sort
    if should_use_incremental_field and config.rsql_incremental_field:
        if config.incremental_sort:
            sort = config.incremental_sort
        if db_incremental_field_last_value:
            formatted = _format_incremental_value(db_incremental_field_last_value)
            # RSQL >= re-pulls the boundary row; merge dedupes it on the primary key. The value is
            # double-quoted because RSQL treats bare colons in timestamps as reserved characters.
            params["filter"] = f'{config.rsql_incremental_field}>="{formatted}"'

    if sort:
        params["sort"] = sort
    if config.sections:
        params["section"] = config.sections

    return params


def _build_url(host: str, config: JamfProEndpointConfig, params: dict[str, Any]) -> str:
    url = f"{_base_url(host)}{config.path}"
    if not params:
        return url
    return f"{url}?{urlencode(params, doseq=True)}"


def _hoist_cursor(config: JamfProEndpointConfig, row: dict[str, Any]) -> dict[str, Any]:
    """Copy the nested incremental cursor to a top-level column.

    The pipeline reads the watermark from a top-level column of the yielded rows, but Jamf
    nests its timestamps (e.g. ``general.reportDate``), so incremental endpoints expose the
    cursor under ``default_incremental_field`` as well.
    """
    if not (config.default_incremental_field and config.rsql_incremental_field):
        return row
    value: Any = row
    for part in config.rsql_incremental_field.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return {**row, config.default_incremental_field: value}


def validate_credentials(
    host: str, credentials: JamfProCredentials, schema_name: Optional[str] = None, team_id: Optional[int] = None
) -> tuple[bool, str | None]:
    """Mint a bearer token to confirm the credentials are genuine.

    Jamf Pro grants privileges per resource, so a valid API client may legitimately lack access
    to endpoints the user never intends to sync — at source-create (``schema_name is None``) a
    successful token mint is enough. A scoped probe (``schema_name`` set) additionally requests
    the endpoint and treats 403 as a hard failure.
    """
    try:
        normalized = normalize_host(host)
    except Exception:
        return False, "Invalid Jamf Pro URL"

    if not normalized or not re.match(r"^[A-Za-z0-9.\-]+$", normalized):
        return False, "Invalid Jamf Pro URL"

    # The host is fully customer-controlled (jamfcloud.com or self-hosted), so block hosts that
    # resolve to private/internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(normalized, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    # capture=False keeps the minted bearer token (returned in the response body) and any probed
    # row content out of opt-in HTTP sample capture — the name-based scrubbers can't recognise them.
    session = make_tracked_session(capture=False)
    token_manager = JamfProTokenManager(session, normalized, credentials)
    try:
        token = token_manager.get_token()
    except JamfProConfigurationError as e:
        return False, str(e)
    except JamfProHostNotAllowedError:
        return False, HOST_NOT_ALLOWED_ERROR
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 401:
            return False, "Invalid Jamf Pro credentials"
        return False, str(e)
    except (JamfProRetryableError, requests.exceptions.RequestException) as e:
        return False, str(e)

    if schema_name is None:
        return True, None

    config = JAMF_PRO_ENDPOINTS[schema_name]
    probe_params = {"page": 0, "page-size": 1} if config.paginated else {}
    try:
        response = session.get(
            _build_url(normalized, config, probe_params),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=10,
            allow_redirects=False,
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code == 200:
        return True, None

    if response.status_code == 403:
        return False, f"Your Jamf Pro API client lacks the read privilege for {schema_name}"

    return False, f"Jamf Pro API returned status {response.status_code} for {schema_name}"


def get_rows(
    host: str,
    credentials: JamfProCredentials,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JamfProResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    config = JAMF_PRO_ENDPOINTS[endpoint]

    # Re-check at run time (not just at source-create) in case the URL was edited or now
    # resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _is_host_safe(normalize_host(host), team_id)
    if not host_ok:
        raise JamfProHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

    # Token responses carry the bearer credential in the body, which the name-based sample
    # scrubbers can't recognise — keep auth exchanges out of sample capture entirely. The data
    # session is reused across every page so urllib3 keeps the connection alive; Jamf recommends
    # few concurrent connections rather than many short-lived ones.
    token_manager = JamfProTokenManager(make_tracked_session(capture=False), host, credentials)
    session = make_tracked_session(capture=config.capture_samples)

    @retry(
        retry=retry_if_exception_type((JamfProRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(page_url: str) -> Any:
        # get_token() inside the retry scope so an expired token or transient mint failure is
        # retried along with the page itself.
        headers = {"Authorization": f"Bearer {token_manager.get_token()}", "Accept": "application/json"}
        response = session.get(page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False)

        # Jamf has no server-side rate limiting or Retry-After headers; it recommends adaptive
        # backoff instead, which the exponential jitter above provides.
        if response.status_code == 429 or response.status_code >= 500:
            raise JamfProRetryableError(
                f"Jamf Pro API error (retryable): status={response.status_code}, url={page_url}"
            )

        if response.is_redirect or response.is_permanent_redirect:
            raise JamfProHostNotAllowedError(
                f"Jamf Pro API returned an unexpected redirect (status={response.status_code}); refusing to follow it"
            )

        if not response.ok:
            logger.error(f"Jamf Pro API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    if not config.paginated:
        data = fetch_page(_build_url(host, config, {}))
        rows = data if isinstance(data, list) else data.get("results", [])
        if rows:
            yield [_hoist_cursor(config, row) for row in rows]
        return

    params = _build_params(config, should_use_incremental_field, db_incremental_field_last_value)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume_config.page if resume_config is not None else 0
    if resume_config is not None:
        logger.debug(f"Jamf Pro: resuming {endpoint} from page {page}")

    while True:
        data = fetch_page(_build_url(host, config, {**params, "page": page}))

        results = data.get("results", [])
        if not results:
            break

        yield [_hoist_cursor(config, row) for row in results]

        total_count = data.get("totalCount")
        if total_count is not None and (page + 1) * config.page_size >= total_count:
            break

        # Save AFTER yielding (and only when more pages remain) so a crash re-yields the last
        # page rather than skipping it — merge dedupes on the primary key.
        resumable_source_manager.save_state(JamfProResumeConfig(page=page + 1))
        page += 1


def jamf_pro_source(
    host: str,
    credentials: JamfProCredentials,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JamfProResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = JAMF_PRO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            host=host,
            credentials=credentials,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            team_id=team_id,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[endpoint_config.primary_key],
        # Incremental runs request sort=general.reportDate:asc so the watermark can checkpoint
        # per batch; full refreshes sort by id for stable page boundaries.
        sort_mode="asc",
    )
