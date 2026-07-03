import datetime as dt
import dataclasses
import collections.abc
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.db import close_old_connections

import structlog
from requests import Response

from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, InstagramIntegration, Integration

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import InstagramSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.instagram.settings import (
    INSTAGRAM_ENDPOINTS,
    MEDIA_FIELDS,
    STORY_FIELDS,
    USER_FIELDS,
    USER_INSIGHT_METRICS,
)

logger = structlog.get_logger(__name__)

GRAPH_API_BASE = f"https://graph.facebook.com/{InstagramIntegration.api_version}"

PAGE_LIMIT = 100  # Graph API caps most Instagram edges at 100 rows per page

# Account-level insights accept at most a 30-day since/until range per request.
INSIGHTS_WINDOW_DAYS = 30
# Recent daily metrics can be restated for a short period; re-fetch a small
# window on incremental syncs and let merge-mode dedupe replace stale rows.
INSIGHTS_LOOKBACK_DAYS = 2

# Permanent auth/permission failures, keyed off the numeric Graph API error
# code (the `type` field flags transient errors as OAuthException too):
#   190 — access token expired/invalid/revoked; 102 — invalid session;
#   10 and 200-299 — permission denied.
GRAPH_AUTH_ERROR_CODES = {102, 190}
GRAPH_PERMISSION_ERROR_CODES = {10, *range(200, 300)}
# Transient throttling: 4 (app-level), 17 (user-level), 32 (page-level),
# 613 (custom rate limit). Raised as plain retryable errors so Temporal backs
# off and the resumable state picks up where the sync left off.
GRAPH_RATE_LIMIT_ERROR_CODES = {4, 17, 32, 613}

INSTAGRAM_AUTH_ERROR_MESSAGE = (
    "Instagram access token is invalid, expired, or lacks the required permissions. "
    "Please re-authorize the integration."
)
INSTAGRAM_TOKEN_REFRESH_ERROR_MESSAGE = (
    "Failed to refresh token for Instagram integration. Please re-authorize the integration."
)


@dataclasses.dataclass
class InstagramResumeConfig:
    account_id: str  # Instagram business account currently being fetched
    next_url: str | None = None  # next page URL (access_token stripped) for media/stories
    metric: str | None = None  # user_insights metric currently being fetched
    window_start: str | None = None  # ISO date of the next insights window for that metric


def _strip_access_token(url: str) -> str:
    """Remove the access_token query param so tokens never sit in Redis resume state."""
    parts = urlsplit(url)
    filtered = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "access_token"]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(filtered), parts.fragment))


def _is_permanent_auth_error(error: dict[str, Any]) -> bool:
    code = error.get("code")
    if not isinstance(code, int):
        return False
    return code in GRAPH_AUTH_ERROR_CODES or code in GRAPH_PERMISSION_ERROR_CODES


def _is_rate_limit_error(error: dict[str, Any]) -> bool:
    return error.get("code") in GRAPH_RATE_LIMIT_ERROR_CODES


def _raise_graph_api_error(response: Response) -> None:
    """Raise a descriptive error for a non-200 Graph API response.

    Auth/permission failures raise the exact message matched by
    `InstagramSource.get_non_retryable_errors`, so the job fails fast. Rate
    limits and everything else raise plain (retryable) exceptions.
    """
    try:
        error = response.json().get("error", {})
    except (ValueError, AttributeError):
        error = {}

    if _is_permanent_auth_error(error):
        raise Exception(
            f"{INSTAGRAM_AUTH_ERROR_MESSAGE} (Graph API response: {response.status_code} - {response.text})"
        )
    if _is_rate_limit_error(error):
        raise Exception(f"Instagram Graph API rate limit reached, will retry: {response.status_code} - {response.text}")
    raise Exception(f"Instagram Graph API request failed: {response.status_code} - {response.text}")


def _graph_get(url: str, params: dict[str, Any]) -> dict[str, Any]:
    response = make_tracked_session().get(url, params=params)
    if response.status_code != 200:
        logger.warning("Instagram Graph API request failed", url=url, status_code=response.status_code)
        _raise_graph_api_error(response)
    return response.json()


def get_access_token(integration_id: int, team_id: int) -> str:
    """Load the integration and exchange for a fresh long-lived token if close to expiry."""
    # Invoked lazily from inside `get_rows` on a worker thread, so the pooled
    # Django connection has often been idle long enough for Postgres to close it
    # server-side — drop any stale connection before the ORM read.
    close_old_connections()
    integration = Integration.objects.get(id=integration_id, team_id=team_id)
    instagram_integration = InstagramIntegration(integration)
    instagram_integration.refresh_access_token()

    if instagram_integration.integration.errors == ERROR_TOKEN_REFRESH_FAILED:
        raise Exception(INSTAGRAM_TOKEN_REFRESH_ERROR_MESSAGE)

    return instagram_integration.integration.sensitive_config["access_token"]


def discover_instagram_accounts(access_token: str) -> list[dict[str, Any]]:
    """List Instagram professional accounts reachable through the user's Facebook Pages.

    Returns one entry per linked account: {"id", "username", "page_name"}, sorted by id
    so per-account iteration order is stable for resume state.
    """
    accounts: dict[str, dict[str, Any]] = {}
    url = f"{GRAPH_API_BASE}/me/accounts"
    params: dict[str, Any] = {
        "fields": "name,instagram_business_account{id,username}",
        "limit": PAGE_LIMIT,
        "access_token": access_token,
    }

    while url:
        payload = _graph_get(url, params)
        for page in payload.get("data", []):
            ig_account = page.get("instagram_business_account")
            if not ig_account:
                continue
            accounts[ig_account["id"]] = {
                "id": ig_account["id"],
                "username": ig_account.get("username"),
                "page_name": page.get("name"),
            }
        next_url = payload.get("paging", {}).get("next")
        url = _strip_access_token(next_url) if next_url else ""
        params = {"access_token": access_token}

    return sorted(accounts.values(), key=lambda account: account["id"])


def _parse_graph_datetime(value: Any) -> Any:
    """Graph API timestamps look like 2026-04-15T10:30:00+0000."""
    if not isinstance(value, str):
        return value
    try:
        return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return value


def _flatten_media_row(row: dict[str, Any], account: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    owner = out.pop("owner", None)
    if isinstance(owner, dict):
        out["owner_id"] = owner.get("id")
    if "timestamp" in out:
        out["timestamp"] = _parse_graph_datetime(out["timestamp"])
    out["account_id"] = account["id"]
    out["account_username"] = account.get("username")
    return out


def _to_unix_timestamp(value: Any) -> int:
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, dt.date):
        parsed = dt.datetime.combine(value, dt.time.min)
    else:
        parsed = dt.datetime.fromisoformat(str(value).replace("+0000", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return int(parsed.timestamp())


def _today() -> dt.date:
    return dt.datetime.now(tz=dt.UTC).date()


def _iter_account_edge(
    account: dict[str, Any],
    edge: str,
    fields: list[str],
    access_token: str,
    resume_next_url: str | None,
    save_state: collections.abc.Callable[[str | None], None],
    since: int | None = None,
) -> collections.abc.Iterator[list[dict[str, Any]]]:
    """Page through an account edge (media/stories), yielding flattened row batches."""
    if resume_next_url:
        url = resume_next_url
        params: dict[str, Any] = {"access_token": access_token}
    else:
        url = f"{GRAPH_API_BASE}/{account['id']}/{edge}"
        params = {"fields": ",".join(fields), "limit": PAGE_LIMIT, "access_token": access_token}
        if since is not None:
            params["since"] = since

    while url:
        payload = _graph_get(url, params)
        rows = [_flatten_media_row(row, account) for row in payload.get("data", [])]

        next_url = payload.get("paging", {}).get("next")
        stripped_next = _strip_access_token(next_url) if next_url else None

        if rows:
            yield rows

        save_state(stripped_next)
        url = stripped_next or ""
        params = {"access_token": access_token}


def _resolve_insights_start(
    today: dt.date,
    history_days: int,
    db_incremental_field_last_value: Any,
) -> dt.date:
    floor = today - dt.timedelta(days=history_days)
    if db_incremental_field_last_value is None:
        return floor

    if isinstance(db_incremental_field_last_value, dt.datetime):
        last = db_incremental_field_last_value.date()
    elif isinstance(db_incremental_field_last_value, dt.date):
        last = db_incremental_field_last_value
    else:
        last = dt.date.fromisoformat(str(db_incremental_field_last_value)[:10])

    return max(last - dt.timedelta(days=INSIGHTS_LOOKBACK_DAYS), floor)


def _insight_values_to_rows(
    payload: dict[str, Any],
    account: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for series in payload.get("data", []):
        metric = series["name"]
        period = series.get("period")
        for value in series.get("values", []):
            end_time = _parse_graph_datetime(value["end_time"])
            # `end_time` marks the close of the daily period in the account's
            # timezone; we key rows on its calendar date, consistently per day.
            date = end_time.date() if isinstance(end_time, dt.datetime) else None
            rows.append(
                {
                    "account_id": account["id"],
                    "account_username": account.get("username"),
                    "metric": metric,
                    "period": period,
                    "date": date,
                    "end_time": end_time,
                    "value": value.get("value"),
                }
            )
    return rows


def _iter_account_insights(
    account: dict[str, Any],
    access_token: str,
    today: dt.date,
    db_incremental_field_last_value: Any,
    resume_metric: str | None,
    resume_window_start: str | None,
    save_state: collections.abc.Callable[[str, str], None],
) -> collections.abc.Iterator[list[dict[str, Any]]]:
    metric_names = [m["name"] for m in USER_INSIGHT_METRICS]
    skip_until_metric = resume_metric if resume_metric in metric_names else None

    for metric_config in USER_INSIGHT_METRICS:
        metric = metric_config["name"]
        if skip_until_metric is not None:
            if metric != skip_until_metric:
                continue
            skip_until_metric = None

        start = _resolve_insights_start(today, metric_config["history_days"], db_incremental_field_last_value)
        if resume_metric == metric and resume_window_start is not None:
            start = max(start, dt.date.fromisoformat(resume_window_start))

        current = start
        while current < today:
            window_end = min(current + dt.timedelta(days=INSIGHTS_WINDOW_DAYS), today)
            payload = _graph_get(
                f"{GRAPH_API_BASE}/{account['id']}/insights",
                {
                    "metric": metric,
                    "period": "day",
                    "since": _to_unix_timestamp(current),
                    "until": _to_unix_timestamp(window_end),
                    "access_token": access_token,
                },
            )
            rows = _insight_values_to_rows(payload, account)
            if rows:
                yield rows

            save_state(metric, window_end.isoformat())
            current = window_end


def instagram_source(
    config: InstagramSourceConfig,
    resource_name: str,
    team_id: int,
    resumable_source_manager: ResumableSourceManager[InstagramResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    endpoint = INSTAGRAM_ENDPOINTS.get(resource_name)
    if endpoint is None:
        raise ValueError(f"Unknown Instagram schema: {resource_name}")

    name = NamingConvention.normalize_identifier(resource_name)

    def get_rows() -> collections.abc.Iterator[list[dict[str, Any]]]:
        access_token = get_access_token(config.instagram_integration_id, team_id)
        accounts = discover_instagram_accounts(access_token)
        if not accounts:
            raise Exception(
                "No Instagram professional account is linked to the connected Facebook account. "
                "Link an Instagram professional account to a Facebook Page and re-authorize."
            )

        resume: InstagramResumeConfig | None = None
        if resumable_source_manager.can_resume():
            resume = resumable_source_manager.load_state()
            # If the saved account no longer exists, restart from the beginning.
            if resume is not None and resume.account_id not in {account["id"] for account in accounts}:
                resume = None

        last_value = db_incremental_field_last_value if should_use_incremental_field else None

        for account in accounts:
            account_id = account["id"]
            if resume is not None and account_id < resume.account_id:
                continue
            is_resume_account = resume is not None and account_id == resume.account_id

            if resource_name == "users":
                payload = _graph_get(
                    f"{GRAPH_API_BASE}/{account_id}",
                    {"fields": ",".join(USER_FIELDS), "access_token": access_token},
                )
                row = dict(payload)
                row["page_name"] = account.get("page_name")
                yield [row]

            elif resource_name in ("media", "stories"):
                is_media = resource_name == "media"

                def save_page_state(
                    next_url: str | None, current_account_id: str = account_id, save: bool = is_media
                ) -> None:
                    # Stories are a 24h rolling snapshot — not worth resume tracking.
                    if save:
                        resumable_source_manager.save_state(
                            InstagramResumeConfig(account_id=current_account_id, next_url=next_url)
                        )

                yield from _iter_account_edge(
                    account=account,
                    edge=resource_name,
                    fields=MEDIA_FIELDS if is_media else STORY_FIELDS,
                    access_token=access_token,
                    resume_next_url=resume.next_url if (is_resume_account and resume is not None) else None,
                    save_state=save_page_state,
                    since=_to_unix_timestamp(last_value) if (is_media and last_value is not None) else None,
                )

            elif resource_name == "user_insights":

                def save_window_state(metric: str, window_start: str, current_account_id: str = account_id) -> None:
                    resumable_source_manager.save_state(
                        InstagramResumeConfig(account_id=current_account_id, metric=metric, window_start=window_start)
                    )

                yield from _iter_account_insights(
                    account=account,
                    access_token=access_token,
                    today=_today(),
                    db_incremental_field_last_value=last_value,
                    resume_metric=resume.metric if (is_resume_account and resume is not None) else None,
                    resume_window_start=resume.window_start if (is_resume_account and resume is not None) else None,
                    save_state=save_window_state,
                )

    return SourceResponse(
        name=name,
        items=get_rows,
        primary_keys=list(endpoint["primary_key"]),
        partition_count=1 if endpoint["partition_mode"] else None,
        partition_size=1 if endpoint["partition_mode"] else None,
        partition_mode=endpoint["partition_mode"],
        partition_format=endpoint["partition_format"],
        partition_keys=endpoint["partition_keys"],
        sort_mode=endpoint["sort_mode"],
    )
