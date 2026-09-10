import re
import hmac
import json
import hashlib
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
import structlog
from dateutil import parser as dateutil_parser
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen
from posthog.models.integration import (
    ERROR_TOKEN_REFRESH_FAILED,
    FacebookPagesIntegration,
    Integration,
    OauthIntegration,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.facebook_pages.settings import (
    DEFAULT_API_VERSION,
    DEFAULT_INSIGHTS_LOOKBACK_DAYS,
    FACEBOOK_PAGES_ENDPOINTS,
    GRAPH_API_HOST,
    INSIGHTS_WINDOW_DAYS,
    PAGE_INSIGHTS_METRICS,
    FacebookPagesEndpointConfig,
)

# The credential probe runs outside a job context, so it logs to the module logger rather than
# the per-job one the pipeline threads through.
PROBE_LOGGER: FilteringBoundLogger = structlog.get_logger(__name__)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
MAX_RETRY_AFTER_SECONDS = 60
EDGE_PAGE_SIZE = 100

# `/me/accounts` is paginated, and an agency user can administer a lot of Pages. Cap the walk so
# the account picker can never spin forever on a pathological account.
MAX_ACCOUNT_PAGES = 20
ACCOUNTS_PAGE_SIZE = 100

# How many times an insights window may be re-requested after dropping metrics Meta rejected.
MAX_METRIC_DROP_ATTEMPTS = 3

SECONDS_PER_DAY = 24 * 60 * 60

# Stable prefixes so `get_non_retryable_errors` can match on them — Graph answers an expired
# token with HTTP 400, not 401, so the HTTP status alone can't drive the classification.
AUTH_ERROR_PREFIX = "Facebook Graph API authentication failed"
PERMISSION_ERROR_PREFIX = "Facebook Graph API permission denied"

# The OAuth kind whose app registration backs this source. The app secret it carries is what
# `appsecret_proof` is derived from.
INTEGRATION_KIND = "facebook-pages"

# A Graph node ID is a bare decimal string. `page_id` is interpolated straight into the request
# path, so anything else — a slash, a `?`, an escaped delimiter — would let a config author point
# the stored token at an arbitrary Graph endpoint (e.g. `/me/accounts?fields=access_token`) and
# have the response written into the warehouse.
PAGE_ID_RE = re.compile(r"\A[0-9]{1,64}\Z")

INVALID_PAGE_ID_ERROR = "Facebook Pages: the configured Page must be a numeric Facebook Page ID"

TOKEN_REFRESH_ERROR_MESSAGE = (
    "Facebook rejected the stored credentials for this integration. Please reconnect your Facebook Pages integration."
)

# https://developers.facebook.com/docs/graph-api/guides/error-handling
AUTH_ERROR_CODES = frozenset({102, 190, 458, 459, 460, 463, 464, 467})
PERMISSION_ERROR_CODES = frozenset({3, 10, 200, 299, 803})
# Throttling (4/17/32/613/341) and Meta-side blips (1/2) — all worth another attempt.
RETRYABLE_ERROR_CODES = frozenset({1, 2, 4, 17, 32, 341, 613})


class FacebookPagesRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class FacebookPagesAuthError(Exception):
    pass


class FacebookPagesPermissionError(Exception):
    pass


class FacebookPagesAPIError(Exception):
    pass


class FacebookPagesTokenRefreshError(Exception):
    """Meta refused to re-mint the integration's user token — only re-authorization fixes it."""


class FacebookPagesInvalidPageIdError(Exception):
    """The configured `page_id` isn't a Graph node ID, so no request may be built from it."""


def validated_page_id(page_id: str | None) -> str:
    """Return `page_id` once it is known to be a bare Graph node ID.

    Every Graph path this source builds interpolates the Page ID, so this runs before the first
    request on both the validation and the pipeline path — a value persisted before this check
    existed, or written straight to the model, still can't redirect a request.
    """
    candidate = (page_id or "").strip()
    if not candidate:
        raise FacebookPagesInvalidPageIdError("Select the Facebook Page you want to sync")
    if not PAGE_ID_RE.match(candidate):
        raise FacebookPagesInvalidPageIdError(INVALID_PAGE_ID_ERROR)
    return candidate


def _meta_app_secret() -> str | None:
    """The Meta app secret behind the Facebook Pages OAuth app, or None when it isn't configured.

    Read from the OAuth config rather than the source config: the app registration is PostHog's,
    so the secret must never be something a source author can supply or read back.
    """
    try:
        return OauthIntegration.oauth_config_for_kind(INTEGRATION_KIND).client_secret or None
    except NotImplementedError:
        return None


def appsecret_proof(access_token: str) -> str | None:
    """HMAC-SHA256 of the access token, keyed by the Meta app secret.

    Meta verifies this alongside the token, so a leaked user or Page token can't be replayed
    against Graph from outside PostHog without also knowing the app secret.
    https://developers.facebook.com/docs/facebook-login/security#appsecret_proof
    """
    secret = _meta_app_secret()
    if not secret:
        return None
    return hmac.new(secret.encode("utf-8"), access_token.encode("utf-8"), hashlib.sha256).hexdigest()


@frozen
class FacebookPagesResumeConfig:
    # Edges: the `paging.cursors.after` cursor and the `since` filter pinned at sync start.
    after: str | None = None
    since: int | None = None
    # Insights: start of the next window to fetch, and the end of the overall range (both
    # unix seconds). The range end is pinned at sync start so resumes stay deterministic.
    window_since: int | None = None
    range_until: int | None = None


def graph_url(api_version: str, path: str) -> str:
    return f"{GRAPH_API_HOST}/{api_version}/{path.lstrip('/')}"


def _parse_retry_after(response: requests.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if raw and raw.strip().isdigit():
        return min(float(raw.strip()), MAX_RETRY_AFTER_SECONDS)
    return None


def _retry_wait(retry_state: RetryCallState) -> float:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, FacebookPagesRetryableError) and exc.retry_after is not None:
        return exc.retry_after
    return wait_exponential_jitter(initial=1, max=30)(retry_state)


def raise_for_graph_error(response: requests.Response, logger: FilteringBoundLogger) -> None:
    """Turn a failed Graph response into the right exception class.

    Classification is driven by Meta's numeric error code rather than the HTTP status or the
    `type` field: Graph returns 400 with `type: "OAuthException"` for throttling, expired
    tokens, and plain bad parameters alike, so only the code separates them.
    """
    if response.ok:
        return

    try:
        body = response.json()
    except ValueError:
        body = {}

    error = (body or {}).get("error") or {}
    code = error.get("code")
    subcode = error.get("error_subcode")
    message = error.get("message") or response.text

    if response.status_code == 429 or response.status_code >= 500 or code in RETRYABLE_ERROR_CODES:
        retry_after = _parse_retry_after(response) if response.status_code == 429 else None
        raise FacebookPagesRetryableError(
            f"Facebook Graph API error (retryable): status={response.status_code}, code={code}, message={message}",
            retry_after=retry_after,
        )

    if response.status_code == 401 or code in AUTH_ERROR_CODES:
        raise FacebookPagesAuthError(f"{AUTH_ERROR_PREFIX}: {message} (code={code}, subcode={subcode})")

    if response.status_code == 403 or code in PERMISSION_ERROR_CODES:
        raise FacebookPagesPermissionError(f"{PERMISSION_ERROR_PREFIX}: {message} (code={code})")

    logger.error(f"Facebook Graph API error: status={response.status_code}, code={code}, message={message}")
    raise FacebookPagesAPIError(
        f"Facebook Graph API error: status={response.status_code}, code={code}, message={message}"
    )


def _fetch_json_once(
    session: requests.Session,
    url: str,
    params: dict[str, str],
    access_token: str,
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    # The token rides in the Authorization header, never the query string, so it stays out of
    # request logs and captured samples. The proof has to travel as a query param — Meta reads
    # it from there — but `appsecret_proof` is on the transport's redaction denylist.
    proof = appsecret_proof(access_token)
    signed_params = {**params, "appsecret_proof": proof} if proof else params

    response = session.get(
        f"{url}?{urlencode(signed_params)}",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    raise_for_graph_error(response, logger)
    data = response.json()
    return data if isinstance(data, dict) else {"data": data}


_fetch_json = retry(
    retry=retry_if_exception_type((FacebookPagesRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=_retry_wait,
    reraise=True,
)(_fetch_json_once)


def get_user_access_token(integration: Integration) -> str:
    """Return the Meta user access token stored on the integration, re-minting it when it is due.

    Meta issues no refresh token, so the long-lived user token is re-minted with `fb_exchange_token`
    instead. `refresh_access_token` is a no-op while more than 7 days of the token's life remain,
    so calling it on every sync is cheap.
    """
    facebook = FacebookPagesIntegration(integration)
    facebook.refresh_access_token()

    access_token = facebook.integration.access_token
    if facebook.integration.errors == ERROR_TOKEN_REFRESH_FAILED or not access_token:
        raise FacebookPagesTokenRefreshError(TOKEN_REFRESH_ERROR_MESSAGE)

    return access_token


def list_pages(
    session: requests.Session, api_version: str, access_token: str, logger: FilteringBoundLogger
) -> list[dict[str, Any]]:
    """The Pages the connected Meta user administers, as `/me/accounts` returns them."""
    pages: list[dict[str, Any]] = []
    url = graph_url(api_version, "me/accounts")
    params = {"fields": "id,name,category", "limit": str(ACCOUNTS_PAGE_SIZE)}

    for _ in range(MAX_ACCOUNT_PAGES):
        data = _fetch_json(session, url, params, access_token, logger)
        pages.extend(page for page in (data.get("data") or []) if isinstance(page, dict) and page.get("id"))

        after = ((data.get("paging") or {}).get("cursors") or {}).get("after")
        if not (data.get("paging") or {}).get("next") or not after:
            break
        params = {**params, "after": after}

    return pages


def resolve_page_access_token(
    session: requests.Session,
    api_version: str,
    page_id: str,
    access_token: str,
    logger: FilteringBoundLogger,
) -> str:
    """Swap the connected user's token for the Page's own access token.

    Page-level reads (insights in particular) want a Page token rather than the user token that
    authorized the connection. It's a best-effort upgrade: if the Page node won't hand one over,
    the user token stays in place and the real data request reports the problem.
    """
    token = access_token

    try:
        page = _fetch_json(session, graph_url(api_version, page_id), {"fields": "access_token"}, token, logger)
        if page.get("access_token"):
            token = str(page["access_token"])
    except Exception as e:
        # Log only the exception class: requests' exception text can echo the request URL back,
        # and Graph error bodies quote the values they choked on.
        logger.debug(
            "Facebook Pages: could not read a Page access token, using the user token",
            error_type=type(e).__name__,
        )

    return token


def _to_epoch_seconds(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError(f"Cannot interpret incremental value as a timestamp: {value!r}")
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(aware.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    if isinstance(value, str) and value.strip():
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
        parsed = dateutil_parser.parse(stripped)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return int(parsed.timestamp())
    raise ValueError(f"Cannot interpret incremental value as a timestamp: {value!r}")


def _row_epoch(item: dict[str, Any], field_name: str) -> int | None:
    raw = item.get(field_name)
    if raw is None:
        return None
    try:
        return _to_epoch_seconds(raw)
    except (ValueError, TypeError, OverflowError):
        return None


def _now_seconds() -> int:
    return int(datetime.now(UTC).timestamp())


def unsupported_metrics(message: str, metrics: Sequence[str]) -> list[str]:
    """Metric names the error message calls out, matched on whole tokens.

    `page_impressions` is a prefix of `page_impressions_unique`, so a substring test would drop
    metrics Meta never complained about.
    """
    return [m for m in metrics if re.search(rf"(?<![A-Za-z0-9_]){re.escape(m)}(?![A-Za-z0-9_])", message)]


def flatten_insights(payload: dict[str, Any], page_id: str) -> list[dict[str, Any]]:
    """One row per metric/period/end_time.

    Graph nests a `values` time series under each metric. Breakdown metrics carry a dict value
    instead of a number; those go to `value_json` so `value` stays a clean numeric column.
    """
    rows: list[dict[str, Any]] = []
    for metric in payload.get("data") or []:
        if not isinstance(metric, dict):
            continue
        for point in metric.get("values") or []:
            if not isinstance(point, dict) or not point.get("end_time"):
                continue
            raw_value: Any = point.get("value")
            is_numeric = isinstance(raw_value, int | float) and not isinstance(raw_value, bool)
            rows.append(
                {
                    "page_id": page_id,
                    "name": metric.get("name"),
                    "period": metric.get("period"),
                    "title": metric.get("title"),
                    "description": metric.get("description"),
                    "end_time": point.get("end_time"),
                    "value": float(raw_value) if is_numeric else None,
                    "value_json": None if is_numeric or raw_value is None else json.dumps(raw_value),
                }
            )
    return rows


def _get_object_rows(
    session: requests.Session,
    api_version: str,
    page_id: str,
    access_token: str,
    config: FacebookPagesEndpointConfig,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    data = _fetch_json(
        session,
        graph_url(api_version, page_id),
        {"fields": ",".join(config.fields)},
        access_token,
        logger,
    )
    if data:
        yield [data]


def _get_edge_rows(
    session: requests.Session,
    api_version: str,
    page_id: str,
    access_token: str,
    config: FacebookPagesEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FacebookPagesResumeConfig],
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Walk a Page edge newest-first with the `after` cursor, bounded by `since`.

    Graph only guarantees the `since` filter on the first request of a cursor walk, so the loop
    also stops client-side once a whole page predates the watermark — otherwise every
    incremental run would page back through the Page's entire history.
    """
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if resume is not None and resume.after:
        after: str | None = resume.after
        since = resume.since
        logger.debug(f"Facebook Pages: resuming {config.name} from cursor after={after}")
    else:
        after = None
        since = _to_epoch_seconds(db_incremental_field_last_value) if db_incremental_field_last_value else None

    url = graph_url(api_version, f"{page_id}/{config.edge}")
    timestamp_field = config.timestamp_field

    while True:
        params: dict[str, str] = {"fields": ",".join(config.fields), "limit": str(EDGE_PAGE_SIZE)}
        if since is not None:
            params["since"] = str(since)
        if after:
            params["after"] = after

        data = _fetch_json(session, url, params, access_token, logger)
        items = [item for item in (data.get("data") or []) if isinstance(item, dict)]

        if since is not None and timestamp_field is not None:
            # `>=` keeps the boundary row; merge dedupes it on the primary key.
            fresh = [item for item in items if (_row_epoch(item, timestamp_field) or 0) >= since]
        else:
            fresh = items

        if fresh:
            yield [{**item, "page_id": page_id} for item in fresh]

        if since is not None and not fresh:
            break

        paging = data.get("paging") or {}
        after = (paging.get("cursors") or {}).get("after")
        if not paging.get("next") or not after or not items:
            break

        # Saved AFTER yielding so a crash re-yields the last page instead of skipping it.
        resumable_source_manager.save_state(FacebookPagesResumeConfig(after=after, since=since))


def _fetch_insights_window(
    session: requests.Session,
    url: str,
    metrics: list[str],
    since: int,
    until: int,
    access_token: str,
    logger: FilteringBoundLogger,
) -> tuple[dict[str, Any], list[str]]:
    """Fetch one insights window, dropping metrics Meta rejects and retrying.

    Meta retires Page metrics on its own schedule and rejects the whole request when one is no
    longer available, naming it in the error. Dropping the named metrics keeps the rest of the
    table syncing instead of failing every run until the pin is updated.
    """
    remaining = list(metrics)

    for _ in range(MAX_METRIC_DROP_ATTEMPTS):
        if not remaining:
            return {}, remaining
        try:
            payload = _fetch_json(
                session,
                url,
                {
                    "metric": ",".join(remaining),
                    "period": "day",
                    "since": str(since),
                    "until": str(until),
                },
                access_token,
                logger,
            )
            return payload, remaining
        except FacebookPagesAPIError as e:
            rejected = unsupported_metrics(str(e), remaining)
            if not rejected:
                raise
            logger.warning(f"Facebook Pages: dropping metrics Meta no longer supports: {', '.join(rejected)}")
            remaining = [m for m in remaining if m not in rejected]

    return {}, remaining


def _get_insights_rows(
    session: requests.Session,
    api_version: str,
    page_id: str,
    access_token: str,
    config: FacebookPagesEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FacebookPagesResumeConfig],
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Walk the metric time series forward in windows Meta will accept (<= 93 days each)."""
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if resume is not None and resume.window_since is not None and resume.range_until is not None:
        window_since, range_until = resume.window_since, resume.range_until
        logger.debug(f"Facebook Pages: resuming {config.name} from window_since={window_since}")
    else:
        range_until = _now_seconds()
        if db_incremental_field_last_value:
            window_since = min(_to_epoch_seconds(db_incremental_field_last_value), range_until)
        else:
            window_since = range_until - DEFAULT_INSIGHTS_LOOKBACK_DAYS * SECONDS_PER_DAY

    url = graph_url(api_version, f"{page_id}/{config.edge}")
    metrics = list(PAGE_INSIGHTS_METRICS)

    while window_since < range_until:
        window_until = min(window_since + INSIGHTS_WINDOW_DAYS * SECONDS_PER_DAY, range_until)
        payload, metrics = _fetch_insights_window(
            session, url, metrics, window_since, window_until, access_token, logger
        )

        if not metrics:
            logger.warning("Facebook Pages: no supported Page insights metrics remain, stopping")
            return

        rows = flatten_insights(payload, page_id)
        if rows:
            yield rows

        window_since = window_until
        if window_since >= range_until:
            break

        resumable_source_manager.save_state(
            FacebookPagesResumeConfig(window_since=window_since, range_until=range_until)
        )


def get_rows(
    page_id: str,
    access_token: str,
    endpoint: str,
    api_version: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FacebookPagesResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = FACEBOOK_PAGES_ENDPOINTS[endpoint]
    last_value = db_incremental_field_last_value if should_use_incremental_field else None
    # Re-checked here, not just at the call site, so a config persisted before this validation
    # existed can't reach the request layer.
    page_id = validated_page_id(page_id)

    # capture=False: Graph responses carry arbitrary Page content (post text, stories,
    # descriptions) the name-based sample scrubber can't recognise, so keep them out of the
    # shared HTTP sample bucket. Requests stay metered and logged.
    session = make_tracked_session(redact_values=(access_token,), capture=False)
    token = resolve_page_access_token(session, api_version, page_id, access_token, logger)
    # The Page token is minted mid-flight, so it needs its own session to be redacted from logs.
    session = make_tracked_session(redact_values=(access_token, token), capture=False)

    if config.style == "object":
        yield from _get_object_rows(session, api_version, page_id, token, config, logger)
    elif config.style == "edge":
        yield from _get_edge_rows(
            session, api_version, page_id, token, config, logger, resumable_source_manager, last_value
        )
    else:
        yield from _get_insights_rows(
            session, api_version, page_id, token, config, logger, resumable_source_manager, last_value
        )


def validate_credentials(
    page_id: str,
    access_token: str,
    api_version: str,
    schema_name: Optional[str] = None,
) -> tuple[bool, str | None]:
    """Probe the Page node to confirm the token can actually see the configured Page.

    A scoped probe (``schema_name`` set) hits that endpoint's own edge instead, so the schema
    picker reports the missing permission for the table the user is about to sync rather than a
    generic failure.
    """
    try:
        page_id = validated_page_id(page_id)
    except FacebookPagesInvalidPageIdError as e:
        return False, str(e)

    logger = PROBE_LOGGER
    # capture=False for the same reason as the sync path: the probe reads Page fields whose
    # values the scrubber can't recognise. See get_rows.
    session = make_tracked_session(redact_values=(access_token,), capture=False)

    try:
        token = resolve_page_access_token(session, api_version, page_id, access_token, logger)

        config = FACEBOOK_PAGES_ENDPOINTS.get(schema_name) if schema_name else None
        if config is not None and config.style == "edge":
            _fetch_json(
                session,
                graph_url(api_version, f"{page_id}/{config.edge}"),
                {"fields": "id", "limit": "1"},
                token,
                logger,
            )
        elif config is not None and config.style == "insights":
            _fetch_json(
                session,
                graph_url(api_version, f"{page_id}/{config.edge}"),
                {"metric": PAGE_INSIGHTS_METRICS[0], "period": "day"},
                token,
                logger,
            )
        else:
            _fetch_json(session, graph_url(api_version, page_id), {"fields": "id,name"}, token, logger)
    except FacebookPagesAuthError:
        return False, "Facebook rejected the connected account. Please reconnect your Facebook Pages integration."
    except (FacebookPagesPermissionError, FacebookPagesAPIError, FacebookPagesRetryableError) as e:
        return False, str(e)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    return True, None


def facebook_pages_source(
    page_id: str,
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FacebookPagesResumeConfig],
    api_version: str = DEFAULT_API_VERSION,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = FACEBOOK_PAGES_ENDPOINTS[endpoint]
    # Fail the job before any row is requested rather than inside the `items` generator.
    page_id = validated_page_id(page_id)

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            page_id=page_id,
            access_token=access_token,
            endpoint=endpoint,
            api_version=api_version,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # Page edges come back newest-first and cursor pagination can't be reordered; insights
        # are walked forward window by window.
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format=config.partition_format if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
