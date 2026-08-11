import time
import dataclasses
from collections.abc import AsyncIterable, Iterable, Iterator
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Optional
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

import orjson
import pyarrow as pa
import requests
import structlog
from asgiref.sync import async_to_sync
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookCreationResult,
    WebhookDeletionResult,
    WebhookSyncResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.settings import (
    MAILGUN_ENDPOINTS,
    WEBHOOK_EVENTS_ENDPOINT,
    WEBHOOK_TYPES,
    MailgunEndpointConfig,
)

REGION_BASE_URLS = {
    "us": "https://api.mailgun.net",
    "eu": "https://api.eu.mailgun.net",
}
REQUEST_TIMEOUT_SECONDS = 60
WEBHOOK_REQUEST_TIMEOUT_SECONDS = 30
# Mailgun rejects a fourth URL on a webhook type, so a domain already fanned out to three
# other consumers has to have one removed by hand before PostHog can be added.
MAX_WEBHOOK_URLS_PER_TYPE = 3
# Registration is one listing plus up to len(WEBHOOK_TYPES) writes per domain, so a very large
# account is bounded rather than left to issue thousands of calls inside one request.
MAX_WEBHOOK_DOMAINS = 100
# Webhook management runs outside a sync, so there is no per-job logger to thread through.
_WEBHOOK_LOGGER: FilteringBoundLogger = structlog.get_logger(__name__)
MAX_RETRIES = 5
MAX_RETRY_AFTER_SECONDS = 120
# Mailgun events are eventually consistent — the docs recommend treating the trailing
# ~30 minutes as incomplete. Bounding `end` keeps the incremental watermark behind the
# consistency horizon so late-arriving events aren't skipped on the next sync.
EVENTS_CONSISTENCY_LAG_SECONDS = 30 * 60
# Backstop for a `paging.next` chain that never terminates and never repeats a URL, which the
# seen-URL guard below can't catch. Sized far above any real page count (the largest paging
# endpoint fetches 1000 rows a page) so it only trips on a runaway.
MAX_PAGES_PER_CHAIN = 100_000


class MailgunRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


@dataclasses.dataclass
class MailgunResumeConfig:
    # URL of the next page to fetch for the in-flight chain (None = start the next domain).
    next_url: Optional[str] = None
    # Domain the in-flight chain belongs to, injected into each row of the resumed pages.
    current_domain: Optional[str] = None
    # Domains not yet started, in fan-out order.
    pending_domains: list[str] = dataclasses.field(default_factory=list)


def base_url_for_region(region: str) -> str:
    return REGION_BASE_URLS.get(region.lower(), REGION_BASE_URLS["us"])


def _to_epoch(value: Any) -> Optional[int]:
    """Coerce an incremental cursor value to UNIX epoch seconds for the `begin` filter."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _epoch_to_datetime(value: Any) -> Any:
    """Convert Mailgun's float-epoch event timestamps into timezone-aware datetimes.

    Raw floats can't be used for datetime partitioning or DateTime incremental cursors,
    so the column is normalized; unparseable values pass through unchanged."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, tz=UTC)
    return value


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(float(value), 0)
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(value)
        return max((retry_at - datetime.now(UTC)).total_seconds(), 0)
    except (TypeError, ValueError):
        return None


_exponential_wait = wait_exponential_jitter(initial=1, max=60)


def _retry_wait(retry_state: RetryCallState) -> float:
    exception = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exception, MailgunRetryableError) and exception.retry_after is not None:
        return min(exception.retry_after, MAX_RETRY_AFTER_SECONDS)
    return _exponential_wait(retry_state)


def _build_url(base_url: str, path: str, params: dict[str, Any]) -> str:
    clean_params = {key: value for key, value in params.items() if value is not None}
    if not clean_params:
        return f"{base_url}{path}"
    return f"{base_url}{path}?{urlencode(clean_params)}"


def _endpoint_path(config: MailgunEndpointConfig, domain: Optional[str]) -> str:
    if not config.domain_scoped:
        return config.path
    if domain is None:
        raise ValueError(f"Mailgun endpoint {config.name} requires a domain")
    return config.path.format(domain=quote(domain, safe=""))


def _initial_url(
    base_url: str,
    config: MailgunEndpointConfig,
    domain: Optional[str],
    begin: Optional[int] = None,
) -> Optional[str]:
    params: dict[str, Any] = {"limit": config.page_size}

    if config.pagination == "skip":
        params["skip"] = 0

    if config.name == "events":
        # Ascending creation order keeps fetched pages stable and lets the incremental
        # watermark advance monotonically.
        params["ascending"] = "yes"
        end = int(time.time()) - EVENTS_CONSISTENCY_LAG_SECONDS
        if begin is not None and begin >= end:
            # Watermark is already inside the consistency lag window; nothing safe to fetch.
            return None
        params["begin"] = begin
        params["end"] = end

    return _build_url(base_url, _endpoint_path(config, domain), params)


def _increment_skip(current_url: str, page_size: int) -> str:
    scheme, netloc, path, query, fragment = urlsplit(current_url)
    params = {key: values[-1] for key, values in parse_qs(query).items()}
    try:
        skip = int(params.get("skip", "0"))
    except ValueError:
        skip = 0
    params["skip"] = str(skip + page_size)
    return urlunsplit((scheme, netloc, path, urlencode(params), fragment))


def _next_page_url(
    config: MailgunEndpointConfig, current_url: str, data: dict[str, Any], items_count: int
) -> Optional[str]:
    if config.pagination == "skip":
        if items_count < config.page_size:
            return None
        return _increment_skip(current_url, config.page_size)

    # Paging-style endpoints terminate with an empty `items` page; the `next` URL of that
    # empty page would just return another empty page (or, for events, later events that
    # are out of this sync's scope).
    if items_count == 0:
        return None
    next_url = (data.get("paging") or {}).get("next")
    if not next_url or next_url == current_url:
        # Some endpoints (tags is the known one) hand back a stable cursor that points at the
        # page we just read instead of an empty page, so following it re-serves the same rows.
        return None
    return next_url


def _normalize_row(config: MailgunEndpointConfig, domain: Optional[str], item: dict[str, Any]) -> dict[str, Any]:
    row = dict(item)
    if config.domain_scoped:
        # Rows from different sending domains can collide on their natural key (e.g. the
        # same suppressed address), so the fan-out domain is part of every primary key.
        row["domain"] = domain
    if config.name == "events":
        row["timestamp"] = _epoch_to_datetime(row.get("timestamp"))
    return row


@retry(
    retry=retry_if_exception_type((MailgunRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=_retry_wait,
    reraise=True,
)
def _fetch_page(url: str, api_key: str, logger: FilteringBoundLogger) -> dict[str, Any]:
    # Mailgun auth is HTTP basic with the literal username "api" and the private API key
    # as the password. Rate limits are plan-dependent; 429s honor Retry-After when present.
    response = make_tracked_session().get(
        url,
        auth=("api", api_key),
        headers={"Accept": "application/json"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise MailgunRetryableError(
            f"Mailgun API error (retryable): status={response.status_code}, url={url}",
            retry_after=_parse_retry_after(response.headers.get("Retry-After")),
        )

    if not response.ok:
        logger.error(f"Mailgun API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


# Per-domain statuses that skip the domain instead of failing the fan-out. The account lists
# every domain on it (`/v4/domains`), but individual domains may be unqueryable: 400 for
# disabled / unverified / sandbox-like domains, and 401/403 when the key lacks access to a
# specific domain (e.g. a subaccount domain, or a restricted key). A global credential failure
# 401s the `/v4/domains` listing itself, which never reaches this fan-out and stays non-retryable.
SKIPPABLE_DOMAIN_STATUS_CODES = frozenset({400, 401, 403})


def _is_skippable_domain_error(config: MailgunEndpointConfig, domain: Optional[str], error: requests.HTTPError) -> bool:
    """Whether a failed domain-scoped request should skip that domain instead of failing the sync.

    The domain fan-out lists every domain on the account (`/v4/domains`), including ones that
    can't be queried for events/suppressions — disabled, unverified, sandbox-like, or domains
    the key has no access to. Those reject the domain-scoped request with a 400/401/403, so one
    bad domain would otherwise abort the whole fan-out and strand every other domain on the
    account."""
    if not config.domain_scoped or domain is None:
        return False
    response = error.response
    return response is not None and response.status_code in SKIPPABLE_DOMAIN_STATUS_CODES


def get_domain_names(api_key: str, base_url: str, logger: FilteringBoundLogger) -> list[str]:
    config = MAILGUN_ENDPOINTS["domains"]
    names: list[str] = []
    skip = 0

    while True:
        url = _build_url(base_url, config.path, {"limit": config.page_size, "skip": skip})
        data = _fetch_page(url, api_key, logger)
        items = data.get("items") or []
        names.extend(item["name"] for item in items if item.get("name"))

        if len(items) < config.page_size:
            return names

        skip += config.page_size


def validate_credentials(api_key: str, region: str) -> bool:
    """Confirm the private API key is valid for the region. A 1-item domain listing is a cheap probe."""
    try:
        response = make_tracked_session().get(
            f"{base_url_for_region(region)}/v4/domains",
            params={"limit": 1},
            auth=("api", api_key),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    api_key: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MailgunResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = MAILGUN_ENDPOINTS[endpoint]
    base_url = base_url_for_region(region)

    begin: Optional[int] = None
    if should_use_incremental_field and (incremental_field is None or incremental_field == "timestamp"):
        begin = _to_epoch(db_incremental_field_last_value)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if resume_config is not None:
        pending_domains = list(resume_config.pending_domains)
        current_domain = resume_config.current_domain
        current_url = resume_config.next_url
        logger.debug(
            f"Mailgun: resuming {endpoint}. url={current_url}, domain={current_domain}, pending={len(pending_domains)}"
        )
    elif config.domain_scoped:
        pending_domains = get_domain_names(api_key, base_url, logger)
        current_domain = None
        current_url = None
    else:
        pending_domains = []
        current_domain = None
        current_url = _initial_url(base_url, config, None, begin)

    # Mailgun's `paging.next` cursors aren't guaranteed to advance — the tags endpoint returns a
    # stable `page=next&tag=<last>` URL that keeps re-serving the terminal page rather than an
    # empty one. Without this guard the chain re-yields the same rows until the activity is killed,
    # and every re-yielded row is billed as a synced row even though the merge dedupes them away.
    seen_urls: set[str] = set()

    while current_url is not None or pending_domains:
        if current_url is None:
            seen_urls.clear()
            current_domain = pending_domains.pop(0)
            current_url = _initial_url(base_url, config, current_domain, begin)
            if current_url is None:
                current_domain = None
                resumable_source_manager.save_state(MailgunResumeConfig(pending_domains=pending_domains))
                continue

        loop_reason: Optional[str] = None
        if current_url in seen_urls:
            loop_reason = "the page URL repeated"
        elif len(seen_urls) >= MAX_PAGES_PER_CHAIN:
            loop_reason = f"the chain exceeded {MAX_PAGES_PER_CHAIN} pages"

        if loop_reason is not None:
            logger.warning(
                f"Mailgun: stopping pagination for {endpoint} because {loop_reason}; "
                f"domain={current_domain}, url={current_url}"
            )
            current_url = None
            current_domain = None
            resumable_source_manager.save_state(MailgunResumeConfig(pending_domains=pending_domains))
            continue

        seen_urls.add(current_url)

        try:
            data = _fetch_page(current_url, api_key, logger)
        except requests.HTTPError as error:
            if not _is_skippable_domain_error(config, current_domain, error):
                raise
            logger.warning(
                f"Mailgun: skipping domain {current_domain} for {endpoint}; "
                f"request returned {error.response.status_code if error.response is not None else '?'}. "
                f"url={current_url}"
            )
            current_url = None
            current_domain = None
            resumable_source_manager.save_state(MailgunResumeConfig(pending_domains=pending_domains))
            continue

        items = data.get("items") or []

        if items:
            yield [_normalize_row(config, current_domain, item) for item in items]

        current_url = _next_page_url(config, current_url, data, len(items))
        if current_url is None:
            current_domain = None

        # Save after yielding so a crash re-yields the last batch (merge dedupes on
        # primary key) instead of skipping it.
        resumable_source_manager.save_state(
            MailgunResumeConfig(
                next_url=current_url,
                current_domain=current_domain,
                pending_domains=pending_domains,
            )
        )


# Mailgun posts `{"signature": {...}, "event-data": {...}}`; `event-data` is the same event
# object the Events API returns in its `items` array.
WEBHOOK_PAYLOAD_EVENT_KEY = "event-data"


def _webhook_table_transformer(table: pa.Table) -> pa.Table:
    """Unwrap Mailgun's delivery envelope and keep one row per event id.

    Delta merge only dedupes across syncs, so a batch carrying Mailgun's retry of a delivery it
    already made would otherwise land the same event twice. The signature block is dropped: its
    timestamp and token are per-delivery values with no meaning on the stored event."""
    if WEBHOOK_PAYLOAD_EVENT_KEY not in table.column_names:
        return table_from_py_list([])

    best_by_id: dict[str, tuple[float, dict[str, Any]]] = {}
    for event_data in table.column(WEBHOOK_PAYLOAD_EVENT_KEY).to_pylist():
        if event_data is None:
            continue
        # Normally a pyarrow struct, but tolerate a JSON string if one is ever produced upstream.
        row = orjson.loads(event_data) if isinstance(event_data, str | bytes) else dict(event_data)
        event_id = row.get("id")
        if not event_id:
            continue

        raw_timestamp = row.get("timestamp")
        ordering = (
            float(raw_timestamp)
            if isinstance(raw_timestamp, int | float) and not isinstance(raw_timestamp, bool)
            else 0.0
        )
        row["timestamp"] = _epoch_to_datetime(raw_timestamp)

        existing = best_by_id.get(event_id)
        if existing is None or ordering >= existing[0]:
            best_by_id[event_id] = (ordering, row)

    return table_from_py_list([row for _, row in best_by_id.values()])


def _webhook_collection_url(base_url: str, domain: str) -> str:
    return f"{base_url}/v3/domains/{quote(domain, safe='')}/webhooks"


def _webhook_urls(entry: Any) -> list[str]:
    """Read the URLs off one webhook entry. Mailgun returns `urls` today and `url` on older
    single-URL webhooks, and can return both."""
    if not isinstance(entry, dict):
        return []
    urls = [url for url in (entry.get("urls") or []) if url]
    single = entry.get("url")
    if single and single not in urls:
        urls.append(single)
    return urls


def _list_domain_webhooks(session: requests.Session, base_url: str, api_key: str, domain: str) -> dict[str, list[str]]:
    response = session.get(
        _webhook_collection_url(base_url, domain),
        auth=("api", api_key),
        headers={"Accept": "application/json"},
        timeout=WEBHOOK_REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    webhooks = (response.json() or {}).get("webhooks") or {}
    return {name: _webhook_urls(entry) for name, entry in webhooks.items()}


def _put_webhook_urls(
    session: requests.Session, base_url: str, api_key: str, domain: str, webhook_type: str, urls: list[str]
) -> None:
    response = session.put(
        f"{_webhook_collection_url(base_url, domain)}/{webhook_type}",
        auth=("api", api_key),
        data=[("url", url) for url in urls],
        timeout=WEBHOOK_REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()


def _register_webhook(
    session: requests.Session,
    base_url: str,
    api_key: str,
    domain: str,
    webhook_type: str,
    webhook_url: str,
    existing_urls: list[str],
) -> None:
    """Add `webhook_url` to one webhook type on one domain, preserving any URLs already there."""
    if not existing_urls:
        response = session.post(
            _webhook_collection_url(base_url, domain),
            auth=("api", api_key),
            data={"id": webhook_type, "url": webhook_url},
            timeout=WEBHOOK_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return

    if len(existing_urls) >= MAX_WEBHOOK_URLS_PER_TYPE:
        raise ValueError(f"already has {MAX_WEBHOOK_URLS_PER_TYPE} URLs, remove one in Mailgun before adding PostHog")

    _put_webhook_urls(session, base_url, api_key, domain, webhook_type, [*existing_urls, webhook_url])


def _webhook_domains(api_key: str, base_url: str) -> list[str]:
    return get_domain_names(api_key, base_url, _WEBHOOK_LOGGER)[:MAX_WEBHOOK_DOMAINS]


def create_webhook(api_key: str, region: str, webhook_url: str) -> WebhookCreationResult:
    """Register PostHog on every Mailgun webhook type, on every sending domain of the account.

    Mailgun scopes webhooks per domain, so a source that syncs a whole account has to fan the
    registration out. Re-running is safe: a type already pointing at `webhook_url` is left alone."""
    base_url = base_url_for_region(region)
    session = make_tracked_session(redact_values=(api_key,))

    try:
        domains = _webhook_domains(api_key, base_url)
    except Exception as e:
        return WebhookCreationResult(
            success=False,
            error=f"Could not list your Mailgun sending domains: {e}. Please set the webhook up manually.",
        )

    if not domains:
        return WebhookCreationResult(
            success=False,
            error="This Mailgun account has no sending domains, so there is nothing to register a webhook on.",
        )

    registered = 0
    errors: list[str] = []

    for domain in domains:
        try:
            existing = _list_domain_webhooks(session, base_url, api_key, domain)
        except Exception as e:
            errors.append(f"{domain}: {e}")
            continue

        for webhook_type in WEBHOOK_TYPES:
            urls = existing.get(webhook_type, [])
            if webhook_url in urls:
                registered += 1
                continue
            try:
                _register_webhook(session, base_url, api_key, domain, webhook_type, webhook_url, urls)
                registered += 1
            except Exception as e:
                errors.append(f"{domain} / {webhook_type}: {e}")

    if registered == 0:
        return WebhookCreationResult(
            success=False,
            error=f"Mailgun refused every webhook registration: {'; '.join(errors[:5])}. "
            "Please set the webhook up manually.",
        )

    if errors:
        _WEBHOOK_LOGGER.warning(f"Mailgun: some webhook registrations failed: {'; '.join(errors[:10])}")

    # Mailgun never returns the account's HTTP webhook signing key over the API, so deliveries
    # can't be verified until the user pastes it in.
    return WebhookCreationResult(success=True, pending_inputs=["signing_secret"])


def sync_webhook_events(api_key: str, region: str, webhook_url: str) -> WebhookSyncResult:
    """Re-run registration so domains added since setup, and any type that failed first time
    round, get picked up. Registration is idempotent."""
    result = create_webhook(api_key, region, webhook_url)
    return WebhookSyncResult(success=result.success, error=result.error)


def get_external_webhook_info(api_key: str, region: str, webhook_url: str) -> ExternalWebhookInfo:
    base_url = base_url_for_region(region)
    session = make_tracked_session(redact_values=(api_key,))

    try:
        domains = _webhook_domains(api_key, base_url)
        enabled_types: set[str] = set()
        registered_domains = 0

        for domain in domains:
            types = [
                webhook_type
                for webhook_type, urls in _list_domain_webhooks(session, base_url, api_key, domain).items()
                if webhook_url in urls
            ]
            if types:
                registered_domains += 1
                enabled_types.update(types)

        if not enabled_types:
            return ExternalWebhookInfo(exists=False)

        return ExternalWebhookInfo(
            exists=True,
            url=webhook_url,
            enabled_events=sorted(enabled_types),
            status="enabled",
            description=f"Registered on {registered_domains} of {len(domains)} sending domains",
        )
    except Exception as e:
        return ExternalWebhookInfo(exists=False, error=str(e))


def delete_webhook(api_key: str, region: str, webhook_url: str) -> WebhookDeletionResult:
    """Remove PostHog from every webhook type it was registered on, leaving other consumers'
    URLs in place."""
    base_url = base_url_for_region(region)
    session = make_tracked_session(redact_values=(api_key,))

    try:
        domains = _webhook_domains(api_key, base_url)
    except Exception as e:
        return WebhookDeletionResult(success=False, error=f"Could not list your Mailgun sending domains: {e}")

    errors: list[str] = []

    for domain in domains:
        try:
            existing = _list_domain_webhooks(session, base_url, api_key, domain)
        except Exception as e:
            errors.append(f"{domain}: {e}")
            continue

        for webhook_type, urls in existing.items():
            if webhook_url not in urls:
                continue
            remaining = [url for url in urls if url != webhook_url]
            try:
                if remaining:
                    _put_webhook_urls(session, base_url, api_key, domain, webhook_type, remaining)
                else:
                    response = session.delete(
                        f"{_webhook_collection_url(base_url, domain)}/{webhook_type}",
                        auth=("api", api_key),
                        timeout=WEBHOOK_REQUEST_TIMEOUT_SECONDS,
                    )
                    response.raise_for_status()
            except Exception as e:
                errors.append(f"{domain} / {webhook_type}: {e}")

    if errors:
        return WebhookDeletionResult(success=False, error="; ".join(errors[:5]))
    return WebhookDeletionResult(success=True)


def mailgun_webhook_source(webhook_source_manager: WebhookSourceManager, endpoint: str) -> SourceResponse:
    """Webhook-only table: the poll has nothing to fetch, so it yields nothing and lets the
    webhook manager take over once the schema's first (empty) sync completes."""
    webhook_enabled = async_to_sync(webhook_source_manager.webhook_enabled)(webhook_only=True)

    def items() -> Iterable[Any] | AsyncIterable[Any]:
        if webhook_enabled:
            return webhook_source_manager.get_items(table_transformer=_webhook_table_transformer)
        return iter([])

    return SourceResponse(
        name=endpoint,
        items=items,
        # Mailgun event ids come from a single account-wide event store, so they are unique
        # without the sending-domain qualifier the polled `events` table needs.
        primary_keys=["id"],
        sort_mode="asc",
        webhook_only=True,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="day",
        partition_keys=["timestamp"],
    )


def mailgun_source(
    api_key: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MailgunResumeConfig],
    webhook_source_manager: WebhookSourceManager,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    if endpoint == WEBHOOK_EVENTS_ENDPOINT:
        return mailgun_webhook_source(webhook_source_manager, endpoint)

    config = MAILGUN_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            region=region,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=list(config.primary_keys),
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format=config.partition_format if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
