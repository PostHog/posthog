import re
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from typing import Any, ClassVar, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from tenacity import RetryCallState, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.sources.newsbreak.settings import (
    BASE_URL,
    DEFAULT_BACKFILL_DAYS,
    DEFAULT_TIMEZONE,
    NEWSBREAK_ENDPOINTS,
    PAGE_SIZE,
    REPORT_METRICS,
    REPORT_WINDOW_DAYS,
    NewsBreakEndpointConfig,
)
from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceCursorManager,
    SourceResponse,
    frozen,
    interruptible_wait,
    make_tracked_session,
    retry_with_deadline,
)

INVALID_TOKEN_ERROR = (
    "NewsBreak rejected the access token. Generate a new token in NewsBreak Ads Manager under "
    "Tools > Resources > API Access Tokens, then reconnect the source."
)
PERMISSION_ERROR = (
    "NewsBreak denied access. Check that the user who owns the access token can view the organizations "
    "and ad accounts you want to sync."
)
NO_ORGANIZATIONS_ERROR = (
    "NewsBreak found no organizations where this access token's user is an admin. "
    "Enter your organization IDs in the source settings."
)
INVALID_TIMEZONE_ERROR = (
    "The report time zone is not valid. Use an IANA time zone name, such as UTC or America/New_York."
)
UNREACHABLE_ERROR = "PostHog couldn't reach NewsBreak to check your access token. Wait a few minutes, then try again."

# Codes NewsBreak sends in the `code` field of the body. https://advertising-api.newsbreak.com/hc/en-us/articles/37869109014541
CODE_OK = 0
CODE_PERMISSION_DENIED = 403
CODE_NOT_LOGGED_IN = 4031
CODE_INVALID_TOKEN = 4033
CODE_RATE_LIMITED = 4034

REQUEST_TIMEOUT = (10, 120)
MAX_ATTEMPTS = 6
# NewsBreak suspends a throttled app for 5 minutes (https://advertising-api.newsbreak.com/hc/en-us/articles/40262642898701).
# A throttled request retries once a minute until the shared request deadline (5 minutes). If it is
# still throttled, the attempt fails with a retryable error, and the next attempt resumes from the
# staged cursor after the suspension ends.
RATE_LIMIT_RETRY_SECONDS = 60


class NewsBreakAPIError(Exception):
    pass


class NewsBreakRetryableError(Exception):
    pass


class NewsBreakRateLimitError(NewsBreakRetryableError):
    def __init__(self, message: str, retry_after: Optional[float] = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@frozen
class NewsBreakResumeConfig:
    # The ad account the next request reads, and its next page or report window.
    account_id: Optional[str] = None
    page: Optional[int] = None
    window_start: Optional[str] = None
    # Report tables: the accounts this job has read in full, so a retried attempt can mark them backfilled.
    completed_account_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # The JSON round trip gives a list.
        object.__setattr__(self, "completed_account_ids", tuple(self.completed_account_ids))


@frozen
class NewsBreakReportCursor:
    cursor_kind: ClassVar[str] = "newsbreak_report_backfill"
    # An account that is not in the list reads its full history, also on an incremental run.
    backfilled_account_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "backfilled_account_ids", tuple(self.backfilled_account_ids))


def parse_org_ids(value: Optional[str]) -> list[str]:
    ids: list[str] = []
    for part in re.split(r"[\s,]+", value or ""):
        if part and part not in ids:
            ids.append(part)
    return ids


def resolve_timezone(value: Optional[str]) -> ZoneInfo:
    name = (value or "").strip() or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise NewsBreakAPIError(INVALID_TIMEZONE_ERROR) from error


def _data_of(body: Any, path: str) -> Any:
    if not isinstance(body, dict):
        raise NewsBreakAPIError(f"NewsBreak returned an unexpected response for {path}")
    code = body.get("code")
    if code is None or code == CODE_OK:
        return body.get("data")
    if code == CODE_RATE_LIMITED:
        raise NewsBreakRateLimitError(f"NewsBreak rate limit reached for {path}")
    if code in (CODE_NOT_LOGGED_IN, CODE_INVALID_TOKEN):
        raise NewsBreakAPIError(INVALID_TOKEN_ERROR)
    if code == CODE_PERMISSION_DENIED:
        raise NewsBreakAPIError(PERMISSION_ERROR)
    raise NewsBreakAPIError(f"NewsBreak API error {code} for {path}: {body.get('errMsg') or 'no message'}")


def _list_of(data: Any, key: str) -> list[dict[str, Any]]:
    items = data.get(key) if isinstance(data, dict) else None
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _retry_after(response: requests.Response) -> Optional[float]:
    try:
        return float(response.headers.get("Retry-After", ""))
    except ValueError:
        return None


def _client_error_message(response: requests.Response, path: str, body: Any) -> str:
    err_msg = body.get("errMsg") if isinstance(body, dict) else None
    if err_msg:
        return f"NewsBreak returned HTTP {response.status_code} for {path}: {err_msg}"
    return f"NewsBreak returned HTTP {response.status_code} for {path}"


_backoff = wait_exponential_jitter(initial=5, max=60)


def _retry_wait(state: RetryCallState) -> float:
    error = state.outcome.exception() if state.outcome is not None else None
    if isinstance(error, NewsBreakRateLimitError):
        return max(RATE_LIMIT_RETRY_SECONDS, error.retry_after or 0)
    return _backoff(state)


class NewsBreakClient:
    def __init__(self, access_token: str, retry: bool = True) -> None:
        self.access_token = access_token.strip()
        self.retry = retry
        # The calls below own their retries, so the adapter must not retry as well.
        self.session = make_tracked_session(
            retry=Retry(total=0), redact_values=(self.access_token,), allow_redirects=False
        )

    def get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        return self._call("GET", path, params=params)

    def post(self, path: str, body: dict[str, Any]) -> Any:
        return self._call("POST", path, json=body)

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        if self.retry:
            return self._request_with_retries(method, path, **kwargs)
        return self._request(method, path, **kwargs)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.session.request(
            method,
            f"{BASE_URL}{path}",
            headers={"Access-Token": self.access_token, "Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT,
            **kwargs,
        )
        if response.status_code == 401:
            raise NewsBreakAPIError(INVALID_TOKEN_ERROR)
        if response.status_code == 403:
            raise NewsBreakAPIError(PERMISSION_ERROR)
        if response.status_code == 429:
            raise NewsBreakRateLimitError(f"NewsBreak returned HTTP 429 for {path}", retry_after=_retry_after(response))
        if response.status_code >= 500:
            raise NewsBreakRetryableError(f"NewsBreak returned HTTP {response.status_code} for {path}")
        if response.status_code == 404:
            # `_handle_import_error` classifies any `requests.HTTPError` with a 404 status as
            # non-retryable by type, regardless of source. Raising our own error type here would
            # bypass that and retry a missing endpoint until the budget runs out.
            response.raise_for_status()
        try:
            body = response.json()
        except ValueError:
            body = None
        # NewsBreak sometimes answers a token, permission, or rate-limit error with HTTP 400 and its
        # own `code` in the body, instead of the HTTP status this client otherwise relies on above.
        if isinstance(body, dict) and body.get("code") is not None:
            return _data_of(body, path)
        if response.status_code >= 400:
            # `raise_for_status()` would discard the body and leave only a generic "Bad Request" for the
            # customer, even though NewsBreak's own body often names what was wrong with the request.
            raise NewsBreakAPIError(_client_error_message(response, path, body))
        if body is None:
            raise NewsBreakAPIError(f"NewsBreak returned a response that is not JSON for {path}")
        return _data_of(body, path)

    _request_with_retries = retry_with_deadline(
        retry=retry_if_exception_type((NewsBreakRetryableError, requests.ConnectionError, requests.Timeout)),
        stop=stop_after_attempt(MAX_ATTEMPTS),
        wait=_retry_wait,
        sleep=interruptible_wait,
        reraise=True,
    )(_request)


def list_ad_accounts(client: NewsBreakClient, org_ids: list[str]) -> list[dict[str, Any]]:
    """Every ad account of the organizations, one row per account, sorted by id."""
    if not org_ids:
        orgs = _list_of(client.get("/org/admin-orgs"), "list")
        org_ids = [str(org["id"]) for org in orgs if org.get("id") is not None]
        if not org_ids:
            raise NewsBreakAPIError(NO_ORGANIZATIONS_ERROR)

    accounts: dict[str, dict[str, Any]] = {}
    for org in _list_of(client.get("/ad-account/getGroupsByOrgIds", {"orgIds": org_ids}), "list"):
        for account in _list_of(org, "adAccounts"):
            if account.get("id") is None:
                continue
            account_id = str(account["id"])
            org_id = org.get("id")
            accounts.setdefault(
                account_id,
                {
                    **account,
                    "id": account_id,
                    "orgId": str(org_id) if org_id is not None else None,
                    "orgName": org.get("name"),
                },
            )
    return [accounts[account_id] for account_id in sorted(accounts)]


def _to_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def _account_start(account: dict[str, Any], tz: ZoneInfo, today: date) -> date:
    try:
        created = int(account.get("createTime") or 0)
    except (TypeError, ValueError):
        created = 0
    if created > 10**11:
        created //= 1000
    if created > 0:
        try:
            return min(datetime.fromtimestamp(created, tz).date(), today)
        except (OverflowError, OSError, ValueError):
            pass
    return today - timedelta(days=DEFAULT_BACKFILL_DAYS)


def _resume_position(
    accounts: list[dict[str, Any]], resume: Optional[NewsBreakResumeConfig]
) -> tuple[int, Optional[NewsBreakResumeConfig]]:
    """The index of the account to start from, and the saved state when it belongs to that account."""
    if resume is not None and resume.account_id is not None:
        for index, account in enumerate(accounts):
            if account["id"] == resume.account_id:
                return index, resume
    return 0, None


def _filter_id(account_id: str) -> int | str:
    return int(account_id) if account_id.isdigit() else account_id


def _list_rows(
    client: NewsBreakClient,
    config: NewsBreakEndpointConfig,
    accounts: list[dict[str, Any]],
    manager: ResumableSourceManager[NewsBreakResumeConfig],
    resume: Optional[NewsBreakResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    start_index, resume = _resume_position(accounts, resume)
    for index in range(start_index, len(accounts)):
        account_id = accounts[index]["id"]
        page = resume.page if index == start_index and resume and resume.page else 1
        while True:
            data = client.get(config.path, {"adAccountId": account_id, "pageNo": page, "pageSize": PAGE_SIZE})
            rows = _list_of(data, "rows")
            # A page with no rows ends the walk, also when `hasNext` says otherwise.
            has_next = bool(rows) and isinstance(data, dict) and str(data.get("hasNext")).lower() in ("true", "1")
            if has_next:
                manager.save_state(NewsBreakResumeConfig(account_id=account_id, page=page + 1))
            elif index + 1 < len(accounts):
                manager.save_state(NewsBreakResumeConfig(account_id=accounts[index + 1]["id"], page=1))
            if rows:
                yield rows
            else:
                manager.safe_point()
            if not has_next:
                break
            page += 1


def _report_rows(
    client: NewsBreakClient,
    config: NewsBreakEndpointConfig,
    accounts: list[dict[str, Any]],
    tz: ZoneInfo,
    manager: ResumableSourceManager[NewsBreakResumeConfig],
    resume: Optional[NewsBreakResumeConfig],
    watermark: Optional[date],
    cursor_manager: Optional[SourceCursorManager[NewsBreakReportCursor]],
) -> Iterator[list[dict[str, Any]]]:
    today = datetime.now(tz).date()
    start_index, resume = _resume_position(accounts, resume)
    stored = cursor_manager.load() if cursor_manager is not None else None
    backfilled = set(stored.backfilled_account_ids) if stored is not None else set()
    completed = list(resume.completed_account_ids) if resume is not None else []
    backfilled.update(completed)
    for index in range(start_index, len(accounts)):
        account_id = accounts[index]["id"]
        start = _account_start(accounts[index], tz, today)
        # The watermark covers only the accounts that were already read back to their creation, so an
        # account that the token can newly see still gets its full history.
        if watermark is not None and watermark > start and account_id in backfilled:
            start = watermark
        if index == start_index and resume is not None:
            resumed = _to_date(resume.window_start)
            if resumed is not None and resumed > start:
                start = resumed

        while start <= today:
            end = min(start + timedelta(days=REPORT_WINDOW_DAYS - 1), today)
            data = client.post(
                "/reports/getIntegratedReport",
                {
                    "name": f"PostHog {config.name}",
                    "timezone": tz.key,
                    "dateRange": "FIXED",
                    "startDate": start.isoformat(),
                    "endDate": end.isoformat(),
                    "filter": "AD_ACCOUNT",
                    "filterIds": [_filter_id(account_id)],
                    "dimensions": config.dimensions,
                    "metrics": REPORT_METRICS,
                },
            )
            rows = _list_of(data, "rows")
            next_start = end + timedelta(days=1)
            if next_start <= today:
                manager.save_state(
                    NewsBreakResumeConfig(
                        account_id=account_id,
                        window_start=next_start.isoformat(),
                        completed_account_ids=tuple(completed),
                    )
                )
            elif index + 1 < len(accounts):
                manager.save_state(
                    NewsBreakResumeConfig(
                        account_id=accounts[index + 1]["id"], completed_account_ids=(*completed, account_id)
                    )
                )
            if rows:
                # The request asks for the AD_ACCOUNT dimension, so the id is in the row. The default keeps
                # the primary key whole if a row comes back without it.
                yield [{**row, "adAccountId": row.get("adAccountId") or account_id} for row in rows]
            else:
                manager.safe_point()
            start = next_start

        completed.append(account_id)
        backfilled.add(account_id)
        if cursor_manager is not None:
            cursor_manager.stage(NewsBreakReportCursor(backfilled_account_ids=tuple(sorted(backfilled))))


def get_rows(
    access_token: str,
    org_ids: list[str],
    tz: ZoneInfo,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[NewsBreakResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    cursor_manager: Optional[SourceCursorManager[NewsBreakReportCursor]],
) -> Iterator[list[dict[str, Any]]]:
    config = NEWSBREAK_ENDPOINTS[endpoint]
    client = NewsBreakClient(access_token)
    accounts = list_ad_accounts(client, org_ids)

    if config.kind == "ad_accounts":
        if accounts:
            yield accounts
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if config.kind == "list":
        yield from _list_rows(client, config, accounts, resumable_source_manager, resume)
        return

    watermark = _to_date(db_incremental_field_last_value) if should_use_incremental_field else None
    yield from _report_rows(client, config, accounts, tz, resumable_source_manager, resume, watermark, cursor_manager)


def newsbreak_source(
    access_token: str,
    org_ids: Optional[str],
    report_timezone: Optional[str],
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[NewsBreakResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    cursor_manager: Optional[SourceCursorManager[NewsBreakReportCursor]] = None,
) -> SourceResponse:
    config = NEWSBREAK_ENDPOINTS.get(endpoint)
    if config is None:
        raise ValueError(f"Unknown NewsBreak endpoint: {endpoint}")
    tz = resolve_timezone(report_timezone)

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token=access_token,
            org_ids=parse_org_ids(org_ids),
            tz=tz,
            endpoint=endpoint,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            cursor_manager=cursor_manager,
        ),
        primary_keys=list(config.primary_keys),
        # Without a partition key, a partition count would put the whole table into one md5 bucket.
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Reports are read one ad account after another, so the dates do not arrive in one ascending series.
        sort_mode=None,
    )


def validate_credentials(
    access_token: str, org_ids: Optional[str], report_timezone: Optional[str]
) -> tuple[bool, str | None]:
    """One request that NewsBreak answers only for a valid token.

    An empty organization list is not an error here: the sync reports it, with the same message.
    """
    if not access_token.strip():
        return False, INVALID_TOKEN_ERROR
    try:
        resolve_timezone(report_timezone)
        client = NewsBreakClient(access_token, retry=False)
        ids = parse_org_ids(org_ids)
        if ids:
            client.get("/ad-account/getGroupsByOrgIds", {"orgIds": ids})
        else:
            client.get("/org/admin-orgs")
    except NewsBreakAPIError as error:
        return False, str(error)
    except (NewsBreakRetryableError, requests.RequestException):
        return False, UNREACHABLE_ERROR
    return True, None
