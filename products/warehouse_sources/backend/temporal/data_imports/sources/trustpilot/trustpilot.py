import re
import logging
import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ApiKeyAuthConfig,
    OAuth2AuthConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.settings import (
    BASE_URL,
    MAX_PAGES,
    PER_PAGE,
    TOKEN_URL,
    TRUSTPILOT_ENDPOINTS,
)

logger = logging.getLogger(__name__)

VALIDATE_TIMEOUT = 15

# Stable substrings for get_non_retryable_errors; keep them in the raised messages below.
BUSINESS_UNIT_NOT_FOUND_ERROR = "No Trustpilot business unit found"
CREDENTIALS_REJECTED_ERROR = "Trustpilot rejected the API"

# Trustpilot business unit IDs are 24-hex Mongo-style object IDs (e.g. 507f191e810c19729de860ea).
_BUSINESS_UNIT_ID_RE = re.compile(r"^[0-9a-f]{24}$")
# Bare hostname characters only, so the configured value can never retarget or malform a request.
_DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9.\-]*[a-z0-9])?$")


class TrustpilotBusinessUnitError(Exception):
    pass


class TrustpilotAuthError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class TrustpilotResumeConfig:
    # Next page to fetch, 1-indexed.
    page: int
    # The startDateTime the interrupted run queried with. The incremental watermark advances per
    # batch mid-run and a retry re-reads it, so a resumed attempt must re-issue the original query
    # for its saved page number to point at the same rows; re-yielded rows are deduped by the merge.
    start_date_time: str | None = None


def normalize_business_unit(value: str) -> str:
    """Reduce user input to a bare domain name or a business unit ID.

    Accepts the bare domain (example.com), a URL (https://example.com/), a Trustpilot review page
    URL (https://www.trustpilot.com/review/example.com), or a raw 24-hex business unit ID. Raises
    ValueError on anything else so the caller can surface a precise message.
    """
    cleaned = value.strip().lower()
    cleaned = re.sub(r"^https?://", "", cleaned)
    host, _, path = cleaned.partition("/")
    host = host.strip()
    # A pasted Trustpilot review URL names the business unit in its path, not its host.
    if host == "trustpilot.com" or host.endswith(".trustpilot.com"):
        match = re.match(r"review/([^/?#]+)", path)
        if match:
            host = match.group(1)
    if host and (_BUSINESS_UNIT_ID_RE.match(host) or _DOMAIN_RE.match(host)):
        return host
    raise ValueError(
        f"Invalid Trustpilot business unit: {value!r}. Enter your website domain as it appears on "
        "your Trustpilot profile (for example 'example.com'), or your business unit ID."
    )


def is_business_unit_id(value: str) -> bool:
    return bool(_BUSINESS_UNIT_ID_RE.match(value))


def _raise_for_auth(response: Response) -> None:
    if response.status_code in (401, 403):
        raise TrustpilotAuthError(
            f"{CREDENTIALS_REJECTED_ERROR} key (HTTP {response.status_code}). "
            "Check the API key in your Trustpilot Business account."
        )


def resolve_business_unit_id(api_key: str, business_unit: str) -> str:
    """Resolve the configured business unit (domain or raw ID) to a verified business unit ID.

    Domains resolve through the public find endpoint; a raw ID is confirmed to exist with the
    public business unit endpoint. Either way a bad value fails here with a precise message
    instead of a 404 deep inside the paginated fetch.
    """
    normalized = normalize_business_unit(business_unit)
    session = make_tracked_session(redact_values=(api_key,))

    if is_business_unit_id(normalized):
        response = session.get(
            f"{BASE_URL}/business-units/{normalized}",
            headers={"apikey": api_key},
            timeout=VALIDATE_TIMEOUT,
        )
        _raise_for_auth(response)
        if response.status_code == 404:
            raise TrustpilotBusinessUnitError(
                f"{BUSINESS_UNIT_NOT_FOUND_ERROR} for ID '{normalized}'. Check the business unit ID "
                "in your Trustpilot Business account."
            )
        response.raise_for_status()
        return normalized

    candidates = [normalized]
    # Profiles are usually keyed on the bare domain, so fall back without the www prefix.
    if normalized.startswith("www."):
        candidates.append(normalized.removeprefix("www."))

    for candidate in candidates:
        response = session.get(
            f"{BASE_URL}/business-units/find",
            params={"name": candidate},
            headers={"apikey": api_key},
            timeout=VALIDATE_TIMEOUT,
        )
        _raise_for_auth(response)
        if response.status_code == 404:
            continue
        response.raise_for_status()
        business_unit_id = response.json().get("id")
        if not isinstance(business_unit_id, str) or not business_unit_id:
            # A 200 without an id is a broken response contract, not a user typo — fail loud
            # instead of falling through to the misleading not-found message.
            raise TrustpilotBusinessUnitError(
                "Trustpilot returned an unexpected business unit lookup response. Try again."
            )
        return business_unit_id

    raise TrustpilotBusinessUnitError(
        f"{BUSINESS_UNIT_NOT_FOUND_ERROR} for '{normalized}'. Enter your domain exactly as it "
        "appears on your Trustpilot profile, or use your business unit ID."
    )


def mint_access_token(api_key: str, api_secret: str) -> str:
    """Mint a client-credentials access token to confirm the API secret is genuine.

    Only used at credential validation; sync-time requests mint through the framework's OAuth2
    auth, which re-mints on expiry (client-credentials tokens cannot be refreshed, Trustpilot
    expects the same request again).
    """
    # capture=False keeps the token response body out of HTTP samples; allow_redirects=False so a
    # 3xx can't bounce the secret off the token host.
    session = make_tracked_session(redact_values=(api_secret,), capture=False, allow_redirects=False)
    response = session.post(
        TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(api_key, api_secret),
        timeout=VALIDATE_TIMEOUT,
    )
    if response.status_code != 200:
        raise TrustpilotAuthError(
            f"{CREDENTIALS_REJECTED_ERROR} key and secret (HTTP {response.status_code}). "
            "Check both values in your Trustpilot Business account."
        )
    try:
        token = response.json().get("access_token")
    except ValueError:
        raise TrustpilotAuthError("The Trustpilot token endpoint returned an unexpected response. Try again.")
    if not isinstance(token, str) or not token:
        raise TrustpilotAuthError("The Trustpilot token endpoint returned no access token. Try again.")
    return token


def validate_credentials(api_key: str, api_secret: str, business_unit: str) -> tuple[bool, str | None]:
    """Resolve the business unit with the API key, then mint a token to confirm the secret.

    Both probes are cheap and fetch no review data. There is no per-endpoint scope probe because a
    Trustpilot API application grants the same access to every endpoint this source syncs.
    """
    try:
        resolve_business_unit_id(api_key, business_unit)
        mint_access_token(api_key, api_secret)
    except (ValueError, TrustpilotBusinessUnitError, TrustpilotAuthError) as e:
        return False, str(e)
    except Exception:  # noqa: BLE001 — a credential probe must never raise; any failure means "not validated"
        return False, "Could not connect to Trustpilot. Check the API key, secret and business unit, then try again."
    return True, None


def _format_start_datetime(value: Any) -> str:
    """Format the incremental watermark as the `2013-09-07T13:37:00` shape startDateTime expects.

    Trustpilot timestamps are UTC, so emit UTC without an offset suffix (the endpoint rejects
    neither, but documents the bare shape).
    """
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S")
    return str(value)


class TrustpilotPaginator(PageNumberPaginator):
    """Page-number paginator that logs when it stops at Trustpilot's 100,000-record query cap.

    The review list endpoints don't page past 100,000 records per query. Stopping silently would
    read as a complete sync, so log what was left behind instead.
    """

    def __init__(self) -> None:
        super().__init__(base_page=1, page_param="page", total_path=None, maximum_page=MAX_PAGES)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        # Only the cap branch leaves `page` pointing past `maximum_page`; an empty-page stop
        # returns before incrementing.
        if not self._has_next_page and self.maximum_page is not None and self.page > self.maximum_page:
            logger.warning(
                "Trustpilot pagination stopped at the 100,000-record query cap; rows past it were not fetched",
                extra={"maximum_page": self.maximum_page},
            )


def _build_auth(api_key: str, api_secret: str, requires_oauth: bool) -> ApiKeyAuthConfig | OAuth2AuthConfig:
    if not requires_oauth:
        return {"type": "api_key", "name": "apikey", "location": "header", "api_key": api_key}
    return {
        "type": "oauth2",
        "token_url": TOKEN_URL,
        "client_id": api_key,
        "client_secret": api_secret,
        "grant_type": "client_credentials",
        # Trustpilot's token endpoint takes the key/secret as HTTP Basic (its recommended form).
        "client_auth_method": "basic",
    }


def trustpilot_source(
    api_key: str,
    api_secret: str,
    business_unit: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TrustpilotResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = TRUSTPILOT_ENDPOINTS[endpoint]
    business_unit_id = resolve_business_unit_id(api_key, business_unit)
    path = config.path.format(business_unit_id=business_unit_id)

    resume: TrustpilotResumeConfig | None = None
    if config.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()

    start_date_time: str | None = None
    if config.incremental_fields and should_use_incremental_field:
        if resume is not None:
            # Re-issue the interrupted run's query window; see TrustpilotResumeConfig.
            start_date_time = resume.start_date_time
        elif db_incremental_field_last_value is not None:
            start_date_time = _format_start_datetime(db_incremental_field_last_value)

    params: dict[str, Any] = {}
    if config.paginated:
        params["perPage"] = PER_PAGE
    if config.order_by:
        params["orderBy"] = config.order_by
    if start_date_time:
        params["startDateTime"] = start_date_time

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "headers": {"Accept": "application/json"},
            "auth": _build_auth(api_key, api_secret, config.requires_oauth),
            "paginator": TrustpilotPaginator() if config.paginated else "single_page",
            # capture=False: private review rows carry consumer emails, order references and
            # review text, which must stay out of HTTP sample capture (still metered and logged).
            "session": make_tracked_session(redact_values=(api_key, api_secret), capture=False),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": path,
                    "params": params,
                    # response_key None means the whole body is the single row (business unit).
                    **({"data_selector": config.response_key} if config.response_key else {}),
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume is not None and resume.page > 1:
        initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Saved AFTER each page is yielded, so a crash re-fetches the last page (merge dedupes)
        # rather than skipping it.
        if state and state.get("page"):
            resumable_source_manager.save_state(
                TrustpilotResumeConfig(page=int(state["page"]), start_date_time=start_date_time)
            )

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint if config.paginated else None,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # service_reviews requests orderBy=createdat.asc, so the watermark can checkpoint per
        # batch. The other endpoints are full refresh, where sort order carries no meaning.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
