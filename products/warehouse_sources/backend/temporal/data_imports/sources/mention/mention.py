import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode, urljoin

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.mention.settings import MENTION_ENDPOINTS

MENTION_HOST = "https://api.mention.net"
MENTION_BASE_URL = f"{MENTION_HOST}/api"
# Pinned API version, sent on every request as recommended by the Mention docs.
API_VERSION = "1.19"
# Mentions accept up to limit=1000; 100 keeps pages small while staying well inside the documented
# 3600 list calls per alert per 24h quota.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm an access token is genuine. The token is account-wide, so one
# probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/accounts/me"


class MentionRetryableError(Exception):
    pass


@dataclasses.dataclass
class MentionResumeConfig:
    # Remaining alert ids for the per-alert fan-out endpoints (current alert first). None means the
    # endpoint is not a fan-out one (or the alert list hasn't been captured yet).
    alert_ids: list[str] | None = None
    # Absolute URL of the next page to fetch, taken from the API's ``_links.more.href``. Cursor
    # pagination is deterministic, so a crashed full-refresh sync resumes from the page after the
    # last one yielded; merge dedupes the re-pulled page on the primary key.
    next_url: str | None = None


def _headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Accept-Version": API_VERSION,
    }


def _list_url(path: str, limit: int | None = PAGE_SIZE) -> str:
    if limit is None:
        return f"{MENTION_BASE_URL}{path}"
    return f"{MENTION_BASE_URL}{path}?{urlencode({'limit': limit})}"


def _more_url(payload: dict[str, Any]) -> Optional[str]:
    # ``_links.more.href`` points at the next page of older items and is present only when more
    # exist. The href is host-relative (``/api/...``), so resolve it against the API host.
    links = payload.get("_links")
    if not isinstance(links, dict):
        return None
    more = links.get("more")
    if not (isinstance(more, dict) and isinstance(more.get("href"), str) and more["href"]):
        return None
    # urljoin honours an absolute href, so a tampered response could point the session (which
    # carries the bearer token in its default headers) at another host. Pin the resolved URL to
    # the Mention API before we ever fetch it.
    resolved = urljoin(MENTION_HOST, more["href"])
    if resolved != MENTION_BASE_URL and not resolved.startswith((f"{MENTION_BASE_URL}/", f"{MENTION_BASE_URL}?")):
        raise MentionRetryableError(f"Mention pagination URL {resolved!r} is not on the Mention API host")
    return resolved


@retry(
    retry=retry_if_exception_type((MentionRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    # ``url`` is already absolute — either an initial list URL or a resolved ``_links.more`` href,
    # so we never re-send paging params (they're baked into the cursor URL).
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        # 429 carries X-Rate-Limit-Reset (a unix timestamp); the per-alert quota window can be
        # hours long, so we back off briefly here and otherwise let the job-level retry policy
        # reschedule the sync.
        raise MentionRetryableError(f"Mention API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Mention API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict):
        raise MentionRetryableError(f"Mention returned an unexpected payload for {url}: {type(data).__name__}")

    return data


def _rows_from_payload(payload: dict[str, Any], key: str, url: str) -> list[dict[str, Any]]:
    rows = payload.get(key)
    if not isinstance(rows, list):
        raise MentionRetryableError(f"Mention returned an unexpected '{key}' field for {url}")
    return rows


def _unwrap_alert(item: dict[str, Any]) -> dict[str, Any]:
    # The docs state each listed alert "has the form it would if you did a get request on that
    # specific alert", whose body nests the object under ``alert`` — accept both shapes.
    inner = item.get("alert")
    return inner if isinstance(inner, dict) else item


def _get_account(session: requests.Session, logger: FilteringBoundLogger) -> dict[str, Any]:
    payload = _fetch_page(session, f"{MENTION_BASE_URL}/accounts/me", logger)
    account = payload.get("account")
    if not isinstance(account, dict) or account.get("id") is None:
        raise MentionRetryableError("Mention returned an unexpected payload for /accounts/me")
    return account


def _list_all_alert_ids(session: requests.Session, account_id: str, logger: FilteringBoundLogger) -> list[str]:
    alert_ids: list[str] = []
    url: Optional[str] = _list_url(f"/accounts/{account_id}/alerts")
    while url:
        payload = _fetch_page(session, url, logger)
        rows = [_unwrap_alert(row) for row in _rows_from_payload(payload, "alerts", url)]
        for row in rows:
            # ``id`` is the alert's primary key and the fan-out endpoints build their URLs from it,
            # so a missing id is a data error we surface rather than silently drop the alert.
            if row.get("id") is None:
                raise MentionRetryableError(f"Mention returned an alert without an id for {url}")
            alert_ids.append(str(row["id"]))
        url = None if not rows else _more_url(payload)
    return alert_ids


def _account_rows(session: requests.Session, logger: FilteringBoundLogger) -> Iterator[list[dict[str, Any]]]:
    yield [_get_account(session, logger)]


def _alert_rows(
    session: requests.Session,
    logger: FilteringBoundLogger,
    resume: MentionResumeConfig | None,
    resumable_source_manager: ResumableSourceManager[MentionResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    if resume and resume.next_url:
        url: Optional[str] = resume.next_url
        logger.debug(f"Mention: resuming alerts from cursor {url}")
    else:
        account_id = str(_get_account(session, logger)["id"])
        url = _list_url(f"/accounts/{account_id}/alerts")

    while url:
        payload = _fetch_page(session, url, logger)
        rows = [_unwrap_alert(row) for row in _rows_from_payload(payload, "alerts", url)]
        if rows:
            yield rows

        # A missing ``_links.more`` marks the end of the collection. An empty page also terminates
        # defensively so a lingering cursor can never produce an infinite loop.
        next_url = _more_url(payload)
        if not next_url or not rows:
            break

        url = next_url
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(MentionResumeConfig(next_url=next_url))


def _fan_out_alert_ids(
    session: requests.Session,
    account_id: str,
    logger: FilteringBoundLogger,
    resume: MentionResumeConfig | None,
) -> tuple[list[str], str | None]:
    if resume and resume.alert_ids is not None:
        logger.debug(
            f"Mention: resuming fan-out with {len(resume.alert_ids)} alerts remaining, cursor {resume.next_url}"
        )
        return list(resume.alert_ids), resume.next_url
    return _list_all_alert_ids(session, account_id, logger), None


def _mention_rows(
    session: requests.Session,
    logger: FilteringBoundLogger,
    resume: MentionResumeConfig | None,
    resumable_source_manager: ResumableSourceManager[MentionResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    account_id = str(_get_account(session, logger)["id"])
    alert_ids, next_url = _fan_out_alert_ids(session, account_id, logger, resume)

    while alert_ids:
        alert_id = alert_ids[0]
        url: Optional[str] = next_url or _list_url(f"/accounts/{account_id}/alerts/{alert_id}/mentions")

        while url:
            payload = _fetch_page(session, url, logger)
            rows = _rows_from_payload(payload, "mentions", url)
            for row in rows:
                # Normalized to a string so the merge key type is consistent across alerts.
                row["alert_id"] = alert_id
            if rows:
                yield rows

            more = _more_url(payload)
            if not more or not rows:
                break

            url = more
            resumable_source_manager.save_state(MentionResumeConfig(alert_ids=alert_ids, next_url=url))

        alert_ids = alert_ids[1:]
        next_url = None
        resumable_source_manager.save_state(MentionResumeConfig(alert_ids=alert_ids))


def _alert_tag_rows(
    session: requests.Session,
    logger: FilteringBoundLogger,
    resume: MentionResumeConfig | None,
    resumable_source_manager: ResumableSourceManager[MentionResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    account_id = str(_get_account(session, logger)["id"])
    alert_ids, _ = _fan_out_alert_ids(session, account_id, logger, resume)

    while alert_ids:
        alert_id = alert_ids[0]
        # The tags endpoint is not paginated (its ``_links`` is an empty list in the docs).
        url = _list_url(f"/accounts/{account_id}/alerts/{alert_id}/tags", limit=None)
        payload = _fetch_page(session, url, logger)
        rows = _rows_from_payload(payload, "tags", url)
        for row in rows:
            row["alert_id"] = alert_id
        if rows:
            yield rows

        alert_ids = alert_ids[1:]
        resumable_source_manager.save_state(MentionResumeConfig(alert_ids=alert_ids))


def get_rows(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MentionResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    session = make_tracked_session(headers=_headers(access_token), redact_values=(access_token,))
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if endpoint == "accounts":
        yield from _account_rows(session, logger)
    elif endpoint == "alerts":
        yield from _alert_rows(session, logger, resume, resumable_source_manager)
    elif endpoint == "alert_tags":
        yield from _alert_tag_rows(session, logger, resume, resumable_source_manager)
    elif endpoint == "mentions":
        yield from _mention_rows(session, logger, resume, resumable_source_manager)
    else:
        raise ValueError(f"Unknown Mention endpoint '{endpoint}'")


def mention_source(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MentionResumeConfig],
) -> SourceResponse:
    config = MENTION_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token=access_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def check_access(access_token: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the access token.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(access_token), redact_values=(access_token,))
    try:
        response = session.get(f"{MENTION_BASE_URL}{path}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Mention: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Mention returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(access_token: str) -> tuple[bool, str | None]:
    status, message = check_access(access_token)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Mention access token"
    return False, message or "Could not validate Mention access token"
