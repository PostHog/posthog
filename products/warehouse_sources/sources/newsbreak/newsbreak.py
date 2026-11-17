import re
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
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
    SourceResponse,
    frozen,
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
MAX_ATTEMPTS = 5


class NewsBreakAPIError(Exception):
    pass


class NewsBreakRetryableError(Exception):
    pass


@frozen
class NewsBreakResumeConfig:
    # The ad account the next request reads, and its next page or report window.
    account_id: Optional[str] = None
    page: Optional[int] = None
    window_start: Optional[str] = None


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
        raise NewsBreakRetryableError(f"NewsBreak rate limit reached for {path}")
    if code in (CODE_NOT_LOGGED_IN, CODE_INVALID_TOKEN):
        raise NewsBreakAPIError(INVALID_TOKEN_ERROR)
    if code == CODE_PERMISSION_DENIED:
        raise NewsBreakAPIError(PERMISSION_ERROR)
    raise NewsBreakAPIError(f"NewsBreak API error {code} for {path}: {body.get('errMsg') or 'no message'}")


def _list_of(data: Any, key: str) -> list[dict[str, Any]]:
    items = data.get(key) if isinstance(data, dict) else None
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


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
        if response.status_code == 429 or response.status_code >= 500:
            raise NewsBreakRetryableError(f"NewsBreak returned HTTP {response.status_code} for {path}")
        response.raise_for_status()
        try:
            body = response.json()
        except ValueError as error:
            raise NewsBreakAPIError(f"NewsBreak returned a response that is not JSON for {path}") from error
        return _data_of(body, path)

    # A rate-limited call must wait minutes before NewsBreak accepts the next one, so the waits are long.
    _request_with_retries = retry_with_deadline(
        retry=retry_if_exception_type((NewsBreakRetryableError, requests.ConnectionError, requests.Timeout)),
        stop=stop_after_attempt(MAX_ATTEMPTS),
        wait=wait_exponential_jitter(initial=15, max=120),
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
    if created > 0:
        return min(datetime.fromtimestamp(created, tz).date(), today)
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
            has_next = bool(rows) and isinstance(data, dict) and data.get("hasNext") is True
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
) -> Iterator[list[dict[str, Any]]]:
    today = datetime.now(tz).date()
    start_index, resume = _resume_position(accounts, resume)
    for index in range(start_index, len(accounts)):
        account_id = accounts[index]["id"]
        start = _account_start(accounts[index], tz, today)
        if watermark is not None and watermark > start:
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
                manager.save_state(NewsBreakResumeConfig(account_id=account_id, window_start=next_start.isoformat()))
            elif index + 1 < len(accounts):
                manager.save_state(NewsBreakResumeConfig(account_id=accounts[index + 1]["id"]))
            if rows:
                # The request asks for the AD_ACCOUNT dimension, so the id is in the row. The default keeps
                # the primary key whole if a row comes back without it.
                yield [{**row, "adAccountId": row.get("adAccountId") or account_id} for row in rows]
            else:
                manager.safe_point()
            start = next_start


def get_rows(
    access_token: str,
    org_ids: list[str],
    tz: ZoneInfo,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[NewsBreakResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
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
    yield from _report_rows(client, config, accounts, tz, resumable_source_manager, resume, watermark)


def newsbreak_source(
    access_token: str,
    org_ids: Optional[str],
    report_timezone: Optional[str],
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[NewsBreakResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
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
        ),
        primary_keys=list(config.primary_keys),
        partition_count=1,
        partition_size=1,
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
