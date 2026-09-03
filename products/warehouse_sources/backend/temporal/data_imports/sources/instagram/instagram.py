import re
import dataclasses
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.instagram.settings import (
    ACCOUNT_INSIGHT_METRICS,
    ACCOUNT_INSIGHTS_WINDOW_DAYS,
    DEFAULT_INSIGHTS_LOOKBACK_DAYS,
    DEFAULT_MEDIA_INSIGHT_METRICS,
    GRAPH_API_HOST,
    INSTAGRAM_ENDPOINTS,
    MAX_INSIGHTS_LOOKBACK_DAYS,
    MEDIA_INSIGHT_METRICS,
    MEDIA_PARENT_FIELDS,
    PAGE_FIELDS,
    PAGE_SIZE,
    InstagramEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5

# Instagram account node IDs are plain integers. Anything else spliced into the Graph path
# risks retargeting the request at a different object or injecting path/query segments.
_NUMERIC_ACCOUNT_ID = re.compile(r"^[0-9]+$")

# The media edge tops out at 10K posts; at PAGE_SIZE per page that is 100 pages. The cap
# is a runaway guard for a paginator that never signals the end, not a real limit.
MAX_PAGES_PER_STREAM = 500
# Comment threads are unbounded, so each parent post gets its own page budget.
MAX_PAGES_PER_PARENT = 50
# Ceiling on the Graph calls a single sync may issue, drawn down by every request the run
# makes. The two page caps above each bound one loop in isolation, which bounds nothing on
# the fan-out endpoints because they multiply: a parent listing of N posts each paging its
# own child edge is N * MAX_PAGES_PER_PARENT requests. This budget is what actually bounds
# a sync's share of the account's Meta rate limit and of the worker's time. It sits well
# above what a full sync of the documented 10K-post media edge needs, so it only bites on a
# runaway fan-out; whatever it cuts short is picked up by the next sync.
MAX_REQUESTS_PER_SYNC = 25_000

# Substrings the source's `get_non_retryable_errors` matches on. Meta reports an expired
# token as an HTTP 400 with `error.code` 190 as often as it does a 401, so the source
# can't key its permanent failures off the status line alone.
AUTH_ERROR_PREFIX = "Instagram API authentication failed"
PERMISSION_ERROR_PREFIX = "Instagram API permission denied"

# https://developers.facebook.com/docs/graph-api/guides/error-handling
META_AUTH_ERROR_CODES = frozenset({102, 190, 458, 459, 460, 463, 464, 467})
META_THROTTLE_ERROR_CODES = frozenset({4, 17, 32, 613})
META_TRANSIENT_ERROR_CODES = frozenset({1, 2})
META_PERMISSION_ERROR_CODE = 10


class InstagramAPIError(Exception):
    pass


class InstagramRetryableError(InstagramAPIError):
    pass


class InstagramAuthError(InstagramAPIError):
    pass


class InstagramPermissionError(InstagramAPIError):
    pass


class InstagramBadRequestError(InstagramAPIError):
    pass


class InstagramRequestBudgetError(InstagramAPIError):
    pass


@dataclasses.dataclass
class InstagramResumeConfig:
    # Fully-built next request URL. Every stream — plain edges, the parent listing of a
    # fan-out, and the per-metric insight windows — checkpoints as a URL, so one field
    # covers all of them.
    next_url: str


def _is_permission_code(code: Any) -> bool:
    if not isinstance(code, int):
        return False
    return code == META_PERMISSION_ERROR_CODE or 200 <= code < 300


def _normalize_timestamp(value: Any) -> Any:
    """Rewrite Meta's `2024-03-01T18:10:00+0000` into ISO 8601 with an offset colon.

    These columns are the incremental cursors and partition keys, and the compact-offset
    form is not what downstream Arrow/Delta type inference recognises as a timestamp.
    """
    if not isinstance(value, str) or not value:
        return value
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(value, fmt).astimezone(UTC).isoformat()
        except ValueError:
            continue
    return value


def _normalize_row(row: dict[str, Any], timestamp_fields: Sequence[str]) -> dict[str, Any]:
    normalized = dict(row)
    for name in timestamp_fields:
        if name in normalized:
            normalized[name] = _normalize_timestamp(normalized[name])
    return normalized


def _to_unix_seconds(value: Any) -> Optional[int]:
    """Coerce an incremental watermark or a user-supplied start date to Unix seconds."""
    if value is None:
        return None
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(aware.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        parsed = _normalize_timestamp(text)
        try:
            return int(datetime.fromisoformat(parsed).timestamp())
        except ValueError:
            pass
        try:
            return int(datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC).timestamp())
        except ValueError:
            return None
    return None


def _with_query_param(url: str, name: str, value: str) -> str:
    parts = urlparse(url)
    params = [(key, item) for key, item in parse_qsl(parts.query, keep_blank_values=True) if key != name]
    params.append((name, value))
    return urlunparse(parts._replace(query=urlencode(params)))


class InstagramClient:
    """Thin Graph API client.

    Hand-rolled rather than declarative because a single Instagram sync has to walk insight
    windows and demote a metric Meta has retired, neither of which the shared `rest_source`
    endpoint config can express.
    """

    def __init__(
        self,
        access_token: str,
        api_version: str,
        logger: FilteringBoundLogger,
        max_requests: Optional[int] = None,
    ) -> None:
        self._base_url = f"{GRAPH_API_HOST}/{api_version}"
        self._access_token = access_token
        self._logger = logger
        # One client is built per stream, so its counter is the whole sync's request budget.
        self._max_requests = MAX_REQUESTS_PER_SYNC if max_requests is None else max_requests
        self._requests_made = 0
        self._budget_exhausted_logged = False
        # The transport's status retries are disabled so they don't compound with the
        # tenacity loop below, which also has to catch Meta's throttling error codes
        # (delivered as HTTP 400 bodies, invisible to a status-code retry).
        self._session = make_tracked_session(
            headers={"Accept": "application/json"},
            retry=Retry(total=0),
            redact_values=(access_token,),
            # Graph API responses carry user-authored content — bios, captions, comments,
            # usernames — that the name-based scrubbers can't recognise, so keep these
            # bodies out of the shared HTTP sample bucket while still metering the calls.
            capture=False,
        )

    def build_url(self, path: str, params: Optional[dict[str, str]] = None) -> str:
        query = urlencode(dict(params or {}))
        url = f"{self._base_url}/{path.strip('/')}"
        return f"{url}?{query}" if query else url

    @property
    def requests_made(self) -> int:
        return self._requests_made

    def has_request_budget(self) -> bool:
        """Whether this sync may still spend Graph calls.

        Every loop that can fan out asks before issuing a request and stops cleanly when the
        answer is no, leaving the last checkpoint pointing at the page it was draining.
        """
        if self._requests_made < self._max_requests:
            return True

        if not self._budget_exhausted_logged:
            self._budget_exhausted_logged = True
            self._logger.warning(
                f"Instagram: this sync has spent its budget of {self._max_requests} Graph API requests, "
                "stopping early. The rows it did not reach are picked up by the next sync."
            )
        return False

    @retry(
        retry=retry_if_exception_type((InstagramRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=120),
        reraise=True,
    )
    def get(self, url: str) -> dict[str, Any]:
        if self._requests_made >= self._max_requests:
            # Backstop only: every loop that can fan out checks `has_request_budget` and
            # stops cleanly before it gets here, so reaching this is a caller bug and the
            # sync should fail loudly rather than keep drawing on the account's quota.
            raise InstagramRequestBudgetError(f"Instagram API request budget of {self._max_requests} requests spent")
        # Counted per attempt, retries included: a retry costs the account's quota too.
        self._requests_made += 1

        response = self._session.get(
            url,
            headers={"Authorization": f"Bearer {self._access_token}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        self._raise_for_error(response)
        body = response.json()
        return body if isinstance(body, dict) else {"data": body}

    def _raise_for_error(self, response: requests.Response) -> None:
        if response.ok:
            return

        error: dict[str, Any] = {}
        try:
            payload = response.json()
            if isinstance(payload, dict):
                error = payload.get("error") or {}
        except ValueError:
            error = {}

        code = error.get("code")
        message = error.get("message") or response.text[:500]
        detail = f"status={response.status_code}, code={code}, message={message}"

        if (
            response.status_code == 429
            or response.status_code >= 500
            or code in META_THROTTLE_ERROR_CODES
            or code in META_TRANSIENT_ERROR_CODES
        ):
            raise InstagramRetryableError(f"Instagram API error (retryable): {detail}")

        if response.status_code == 401 or code in META_AUTH_ERROR_CODES:
            raise InstagramAuthError(f"{AUTH_ERROR_PREFIX}: {detail}")

        if response.status_code == 403 or _is_permission_code(code):
            raise InstagramPermissionError(f"{PERMISSION_ERROR_PREFIX}: {detail}")

        self._logger.error(f"Instagram API error: {detail}")
        raise InstagramBadRequestError(f"Instagram API error: {detail}")


def _iter_pages(
    client: InstagramClient,
    url: str,
    max_pages: int,
) -> Iterator[tuple[list[dict[str, Any]], Optional[str]]]:
    """Yield `(rows, next_url)` per page of a cursor-paginated edge.

    Meta hands back both a ready-made `paging.next` and the raw `after` cursor. We rebuild
    the URL from the cursor instead of following `paging.next`, so the resume checkpoint is
    a URL we constructed and Meta can't echo the access token into our saved state.
    """
    pages = 0
    current: Optional[str] = url
    while current is not None and pages < max_pages and client.has_request_budget():
        body = client.get(current)
        rows = body.get("data")
        rows = rows if isinstance(rows, list) else []
        paging = body.get("paging") or {}
        after = (paging.get("cursors") or {}).get("after")
        next_url = _with_query_param(current, "after", str(after)) if paging.get("next") and after else None

        yield rows, next_url

        current = next_url
        pages += 1


def _account_path(instagram_account_id: str, edge: str = "") -> str:
    # A Facebook Login token is scoped to a person, so `me` would resolve to the Facebook
    # user rather than the Instagram account. Every request names the account node.
    node = instagram_account_id.strip()
    return f"{node}/{edge}" if edge else node


def _insight_points(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten one insight entry into `(value, end_time)` points.

    Meta returns `time_series` for `metric_type=time_series`, `values` for the legacy
    shape, and a bare `total_value` for lifetime metrics.
    """
    for key in ("time_series", "values"):
        points = entry.get(key)
        if isinstance(points, list) and points:
            return [point for point in points if isinstance(point, dict)]

    total_value = entry.get("total_value")
    if isinstance(total_value, dict) and "value" in total_value:
        return [{"value": total_value["value"], "end_time": None}]

    return []


def _media_rows(
    client: InstagramClient,
    instagram_account_id: str,
    config: InstagramEndpointConfig,
    resumable_source_manager: ResumableSourceManager[InstagramResumeConfig],
    logger: FilteringBoundLogger,
    since: Optional[int],
) -> Iterator[list[dict[str, Any]]]:
    """Page a plain edge hung off the account node (media, stories)."""
    params: dict[str, str] = {"fields": config.fields, "limit": str(PAGE_SIZE)}
    if config.supports_time_window and since is not None:
        params["since"] = str(since)

    url = _resume_url(resumable_source_manager, logger, config.name) or client.build_url(
        _account_path(instagram_account_id, config.edge), params
    )

    for rows, next_url in _iter_pages(client, url, MAX_PAGES_PER_STREAM):
        if rows:
            yield [_normalize_row(row, config.timestamp_fields) for row in rows]
        # Checkpoint after the yield: a crash then re-yields the last page instead of
        # skipping it, and the merge dedupes on the primary key.
        if next_url is not None:
            resumable_source_manager.save_state(InstagramResumeConfig(next_url=next_url))


def _account_row(
    client: InstagramClient,
    instagram_account_id: str,
    config: InstagramEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    body = client.get(client.build_url(_account_path(instagram_account_id), {"fields": config.fields}))
    if body.get("id"):
        yield [_normalize_row(body, config.timestamp_fields)]


def _fanout_rows(
    client: InstagramClient,
    instagram_account_id: str,
    config: InstagramEndpointConfig,
    resumable_source_manager: ResumableSourceManager[InstagramResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Walk the media edge, then query one child edge per post.

    The checkpoint is the parent page, saved once its children are drained, so a resume
    replays at most one page of posts.
    """
    parent_params: dict[str, str] = {"fields": MEDIA_PARENT_FIELDS, "limit": str(PAGE_SIZE)}
    url = _resume_url(resumable_source_manager, logger, config.name) or client.build_url(
        _account_path(instagram_account_id, config.edge), parent_params
    )

    for media_page, next_url in _iter_pages(client, url, MAX_PAGES_PER_STREAM):
        for media in media_page:
            media_id = media.get("id")
            if not media_id:
                continue

            if not client.has_request_budget():
                # Return without checkpointing: the saved state still points at the page
                # being drained, so a resumed attempt replays it instead of skipping the
                # posts whose children were never fetched.
                return

            if config.child_edge == "insights":
                rows = _media_insight_rows(client, media, logger)
            else:
                rows = _media_comment_rows(client, media, config, logger)

            if rows:
                yield rows

        if next_url is not None:
            resumable_source_manager.save_state(InstagramResumeConfig(next_url=next_url))


def _media_comment_rows(
    client: InstagramClient,
    media: dict[str, Any],
    config: InstagramEndpointConfig,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    media_id = str(media["id"])
    url = client.build_url(f"{media_id}/comments", {"fields": config.fields, "limit": str(PAGE_SIZE)})

    rows: list[dict[str, Any]] = []
    try:
        for page, _ in _iter_pages(client, url, MAX_PAGES_PER_PARENT):
            rows.extend(_normalize_row({**comment, "media_id": media_id}, config.timestamp_fields) for comment in page)
    except InstagramBadRequestError as error:
        # Comments are disabled or the post was deleted mid-sync. Neither is fixable by
        # retrying and neither should sink the whole table.
        logger.warning(f"Instagram: skipping comments for media {media_id}: {error}")
        return []

    return rows


def _media_insight_rows(
    client: InstagramClient,
    media: dict[str, Any],
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    media_id = str(media["id"])
    product_type = str(media.get("media_product_type") or "")
    metrics = MEDIA_INSIGHT_METRICS.get(product_type, DEFAULT_MEDIA_INSIGHT_METRICS)
    media_timestamp = _normalize_timestamp(media.get("timestamp"))

    url = client.build_url(f"{media_id}/insights", {"metric": ",".join(metrics)})
    try:
        body = client.get(url)
    except InstagramBadRequestError as error:
        # Meta retires metrics per Graph version and rejects the whole request when one
        # of them doesn't apply to this post. Skip the post rather than the table.
        logger.warning(f"Instagram: skipping insights for media {media_id}: {error}")
        return []

    entries = body.get("data")
    entries = entries if isinstance(entries, list) else []

    rows: list[dict[str, Any]] = []
    for entry in entries:
        points = _insight_points(entry)
        if not points:
            continue
        rows.append(
            {
                "media_id": media_id,
                "media_timestamp": media_timestamp,
                "media_product_type": product_type or None,
                "metric": entry.get("name"),
                "period": entry.get("period"),
                "title": entry.get("title"),
                "description": entry.get("description"),
                # Media insights are lifetime totals, so there is exactly one point.
                "value": points[0].get("value"),
            }
        )

    return rows


def _insight_windows(since: int, until: int, window_days: int = ACCOUNT_INSIGHTS_WINDOW_DAYS) -> list[tuple[int, int]]:
    """Split a range into windows Meta will accept (it rejects spans over 30 days)."""
    if until <= since:
        return []

    step = window_days * 24 * 60 * 60
    windows: list[tuple[int, int]] = []
    start = since
    while start < until:
        end = min(start + step, until)
        windows.append((start, end))
        start = end
    return windows


def _account_insight_plan(
    client: InstagramClient,
    instagram_account_id: str,
    since: int,
    until: int,
) -> list[list[tuple[str, str]]]:
    """Build the request plan as one `(metric, url)` group per time window.

    Window-major, not metric-major: every metric for a window is fetched together so the
    rows for that window can be emitted in date order. Walking metric by metric instead
    would rewind the stream to the start of the range on each new metric, which breaks
    the ascending watermark the pipeline checkpoints after every batch.
    """
    path = _account_path(instagram_account_id, "insights")
    plan: list[list[tuple[str, str]]] = []
    for window_since, window_until in _insight_windows(since, until):
        plan.append(
            [
                (
                    metric,
                    client.build_url(
                        path,
                        {
                            "metric": metric,
                            "period": "day",
                            "metric_type": "time_series",
                            "since": str(window_since),
                            "until": str(window_until),
                        },
                    ),
                )
                for metric in ACCOUNT_INSIGHT_METRICS
            ]
        )
    return plan


def _account_insight_rows(
    client: InstagramClient,
    instagram_account_id: str,
    config: InstagramEndpointConfig,
    resumable_source_manager: ResumableSourceManager[InstagramResumeConfig],
    logger: FilteringBoundLogger,
    since: Optional[int],
) -> Iterator[list[dict[str, Any]]]:
    now = datetime.now(UTC)
    until = int(now.timestamp())
    # Clamp the (user-controlled) start date to Meta's retention horizon: a date like
    # `0001-01-01` would otherwise fan out into tens of thousands of empty 30-day windows.
    earliest = int((now - timedelta(days=MAX_INSIGHTS_LOOKBACK_DAYS)).timestamp())
    start = (
        max(since, earliest)
        if since is not None
        else int((now - timedelta(days=DEFAULT_INSIGHTS_LOOKBACK_DAYS)).timestamp())
    )

    plan = _account_insight_plan(client, instagram_account_id, start, until)

    resume_url = _resume_url(resumable_source_manager, logger, config.name)
    if resume_url is not None:
        # A window is identified by the URL of its first metric.
        heads = [window[0][1] for window in plan]
        if resume_url in heads:
            plan = plan[heads.index(resume_url) :]
        else:
            logger.warning("Instagram: saved account_insights checkpoint is outside this run's window, restarting")

    for index, window in enumerate(plan):
        if not client.has_request_budget():
            # The checkpoint saved by the previous window already points here, so a resumed
            # attempt carries on from this window rather than replaying the whole range.
            return

        rows: list[dict[str, Any]] = []
        for metric, url in window:
            try:
                body = client.get(url)
            except (InstagramBadRequestError, InstagramPermissionError) as error:
                # `impressions` was retired in v22.0 and Meta rejects the whole request
                # for a metric the account can't serve. Drop the metric, keep the window.
                logger.warning(f"Instagram: skipping account insight metric '{metric}': {error}")
                continue

            entries = body.get("data")
            entries = entries if isinstance(entries, list) else []

            for entry in entries:
                for point in _insight_points(entry):
                    end_time = point.get("end_time")
                    if end_time is None:
                        continue
                    rows.append(
                        {
                            "instagram_account_id": instagram_account_id,
                            "metric": entry.get("name") or metric,
                            "period": entry.get("period"),
                            "date": _normalize_timestamp(end_time),
                            "value": point.get("value"),
                            "title": entry.get("title"),
                            "description": entry.get("description"),
                        }
                    )

        if rows:
            # Sorted so the batch is genuinely ascending by date, which is what
            # `sort_mode="asc"` promises the pipeline.
            rows.sort(key=lambda row: (str(row["date"]), str(row["metric"])))
            yield rows

        next_index = index + 1
        if next_index < len(plan):
            resumable_source_manager.save_state(InstagramResumeConfig(next_url=plan[next_index][0][1]))


def _resume_url(
    resumable_source_manager: ResumableSourceManager[InstagramResumeConfig],
    logger: FilteringBoundLogger,
    endpoint: str,
) -> Optional[str]:
    if not resumable_source_manager.can_resume():
        return None

    state = resumable_source_manager.load_state()
    if state is None or not state.next_url:
        return None

    logger.debug(f"Instagram: resuming {endpoint} from saved checkpoint")
    return state.next_url


def list_professional_accounts(
    access_token: str,
    api_version: str,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    """Every Instagram professional account reachable through the connected Facebook user's pages.

    A page with no linked professional account is skipped rather than offered as a choice that
    can never sync.

    Accounts owned by a Business portfolio stay invisible here even when the page really is linked:
    Meta omits `instagram_business_account` rather than erroring unless the token carries
    `business_management`, which this integration deliberately does not request. Syncing such an
    account works once its ID is known, so the account field also accepts an ID typed by hand.
    """
    client = InstagramClient(access_token=access_token, api_version=api_version, logger=logger)
    url = client.build_url("me/accounts", {"fields": PAGE_FIELDS, "limit": str(PAGE_SIZE)})

    accounts: list[dict[str, Any]] = []
    for pages, _ in _iter_pages(client, url, MAX_PAGES_PER_STREAM):
        for page in pages:
            linked = page.get("instagram_business_account")
            if not isinstance(linked, dict) or not linked.get("id"):
                continue
            accounts.append(
                {
                    "id": str(linked["id"]),
                    "username": linked.get("username"),
                    "name": linked.get("name"),
                    "page_name": page.get("name"),
                }
            )

    return accounts


def validate_credentials(
    access_token: str,
    api_version: str,
    logger: FilteringBoundLogger,
    instagram_account_id: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """Probe the account node to confirm the token can read the chosen Instagram account."""
    account_id = (instagram_account_id or "").strip()
    if not account_id:
        return False, "Choose the Instagram account you want to sync."
    # The account ID is spliced straight into the Graph API path, so anything but the plain
    # numeric node ID could select a different object or inject extra path/query segments.
    if not _NUMERIC_ACCOUNT_ID.match(account_id):
        return False, "That is not a valid Instagram account. Pick the account again from the list."

    client = InstagramClient(access_token=access_token, api_version=api_version, logger=logger)

    try:
        body = client.get(client.build_url(_account_path(account_id), {"fields": "id,username"}))
    except InstagramAuthError:
        return False, "The Instagram connection has expired. Reconnect your Instagram account and try again."
    except InstagramPermissionError:
        return False, (
            "The Instagram connection is missing permissions this source needs. Reconnect it and grant "
            "access to your page, Instagram insights and comments."
        )
    except Exception:
        return False, "Could not reach the Instagram API with this connection."

    if not body.get("id"):
        return False, "That account is not an Instagram professional account. Pick a different account."

    return True, None


def get_rows(
    access_token: str,
    api_version: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[InstagramResumeConfig],
    instagram_account_id: str,
    start_date: Optional[str] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = INSTAGRAM_ENDPOINTS[endpoint]
    client = InstagramClient(access_token=access_token, api_version=api_version, logger=logger)

    since: Optional[int] = None
    if config.supports_time_window:
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            since = _to_unix_seconds(db_incremental_field_last_value)
        if since is None:
            since = _to_unix_seconds(start_date)

    if endpoint == "account":
        yield from _account_row(client, instagram_account_id, config)
    elif endpoint == "account_insights":
        yield from _account_insight_rows(
            client=client,
            instagram_account_id=instagram_account_id,
            config=config,
            resumable_source_manager=resumable_source_manager,
            logger=logger,
            since=since,
        )
    elif config.child_edge is not None:
        yield from _fanout_rows(client, instagram_account_id, config, resumable_source_manager, logger)
    else:
        yield from _media_rows(client, instagram_account_id, config, resumable_source_manager, logger, since)


def instagram_source(
    access_token: str,
    api_version: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[InstagramResumeConfig],
    instagram_account_id: str,
    start_date: Optional[str] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = INSTAGRAM_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token=access_token,
            api_version=api_version,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            instagram_account_id=instagram_account_id,
            start_date=start_date,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
