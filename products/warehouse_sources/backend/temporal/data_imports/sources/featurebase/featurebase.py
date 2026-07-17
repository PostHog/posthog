import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import orjson
import pyarrow as pa
import requests
from asgiref.sync import async_to_sync
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SortMode, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookCreationResult,
    WebhookDeletionResult,
    WebhookSyncResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.featurebase.settings import (
    FEATUREBASE_API_VERSION,
    FEATUREBASE_BASE_URL,
    FEATUREBASE_ENDPOINTS,
    FEATUREBASE_OBJECT_TYPE_TO_TOPICS,
    FEATUREBASE_PAGE_SIZE,
    FeaturebaseEndpointConfig,
)

POSTHOG_WEBHOOK_NAME = "PostHog data warehouse"

# Hard cap on voters pages fetched per post to bound runaway pagination in the fan-out.
MAX_VOTER_PAGES_PER_POST = 100


class FeaturebaseRetryableError(Exception):
    pass


@dataclasses.dataclass
class FeaturebaseResumeConfig:
    # Cursor of the next page to fetch. None means "start from the first page" — used when the
    # fan-out bookmark advances to a post whose first page has no cursor yet.
    cursor: str | None = None
    # The post currently being processed in the post_voters fan-out. A stable post-ID bookmark
    # (not a positional index) so posts created/deleted between a crash and the retry can't
    # resume us into the wrong post. None for the standard endpoints.
    post_id: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Featurebase-Version": FEATUREBASE_API_VERSION,
        "Accept": "application/json",
    }


def _build_url(path: str, params: dict[str, Any]) -> str:
    base = f"{FEATUREBASE_BASE_URL}{path}"
    if not params:
        return base
    return f"{base}?{urlencode(params)}"


def _format_datetime(value: datetime | date) -> str:
    """Format as ISO 8601 with a Z suffix, matching the timestamps Featurebase returns."""
    if isinstance(value, datetime):
        utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    else:
        utc_value = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    return utc_value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _parse_row_datetime(value: Any) -> datetime | None:
    """Parse an ISO 8601 timestamp from a response row; None for missing/unparseable values."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _coerce_cutoff(value: Any) -> datetime | None:
    """Normalize the DB watermark to a tz-aware datetime for row comparisons."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str):
        return _parse_row_datetime(value)
    return None


def _page_predates_cutoff(items: list[dict[str, Any]], field: str, cutoff: datetime | None) -> bool:
    """True when every row on a descending-sorted page is strictly older than the watermark.

    Rows without a parseable timestamp don't count as older — an unexpected field shape must
    degrade to a full sweep, never to silently skipped data.
    """
    if cutoff is None or not items:
        return False
    values = [_parse_row_datetime(item.get(field)) for item in items]
    return all(value is not None and value < cutoff for value in values)


@retry(
    retry=retry_if_exception_type(
        (
            FeaturebaseRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any] | list[Any]:
    response = session.get(url, headers=headers, timeout=60)

    # Featurebase documents rate limiting via 429s; back off on those and transient 5xx.
    if response.status_code == 429 or response.status_code >= 500:
        raise FeaturebaseRetryableError(f"Featurebase API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # 404 is expected during the post_voters fan-out (a post deleted mid-sync).
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"Featurebase API error: status={response.status_code}, body={response.text[:500]}, url={url}")
        response.raise_for_status()

    return response.json()


def _make_session(api_key: str) -> requests.Session:
    """Tracked session for every Featurebase call — metered and logged, never sample-captured.

    ``capture=False``: pulled bodies carry free-form customer content (post/comment HTML,
    admin-only comments via ``privacy=all``, contact PII) and the webhook create/list/refresh
    responses carry the ``whsec_`` signing secret in a bare ``secret`` field that the
    name-based scrubbers don't recognise. ``redact_values`` masks the API key anywhere it
    appears in logged URLs.
    """
    return make_tracked_session(redact_values=(api_key,), capture=False)


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """One cheap probe to confirm the API key is genuine.

    Featurebase returns 403 (not 401) with {"success": false, "message": "..."} for both
    missing and invalid keys, verified against the live API.
    """
    url = _build_url("/admins", {})
    try:
        response = _make_session(api_key).get(url, headers=_get_headers(api_key), timeout=10)
    except Exception as e:
        return False, f"Could not reach Featurebase: {e}"

    if response.ok:
        return True, None

    try:
        message = response.json().get("message")
    except Exception:
        message = None
    return False, message or f"Featurebase returned status {response.status_code}"


def _build_initial_params(
    config: FeaturebaseEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if config.paginated:
        params["limit"] = FEATUREBASE_PAGE_SIZE

    field = incremental_field or (config.incremental_fields[0]["field"] if config.incremental_fields else None)

    if should_use_incremental_field and config.incremental_mode and field:
        params.update(config.incremental_params_for_field.get(field, {}))
        if config.incremental_mode == "server_filter" and config.server_filter_param:
            cutoff = _coerce_cutoff(db_incremental_field_last_value)
            if cutoff is not None:
                params[config.server_filter_param] = _format_datetime(cutoff)
    else:
        params.update(config.full_refresh_params)

    params.update(config.extra_params)
    return params


def _iter_pages(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    path: str,
    params: dict[str, Any],
    start_cursor: str | None = None,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    """Walk a cursor-paginated endpoint, yielding (page_items, next_cursor) tuples.

    Boards and post statuses return a bare JSON array with no envelope; everything else wraps
    rows in {"object": "list", "data": [...], "nextCursor": ...}.
    """
    cursor = start_cursor
    while True:
        page_params = {**params, **({"cursor": cursor} if cursor else {})}
        data = _fetch_page(session, _build_url(path, page_params), headers, logger)

        if isinstance(data, list):
            yield data, None
            return

        items = data.get("data", [])
        next_cursor = data.get("nextCursor")
        yield items, next_cursor

        if not next_cursor:
            return
        cursor = next_cursor


def _get_top_level_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    config: FeaturebaseEndpointConfig,
    resumable_source_manager: ResumableSourceManager[FeaturebaseResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> Iterator[list[dict[str, Any]]]:
    params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_cursor = resume.cursor if resume else None
    if start_cursor:
        logger.debug(f"Featurebase: resuming {config.name} from cursor={start_cursor}")

    cutoff: datetime | None = None
    cutoff_field = incremental_field or (config.incremental_fields[0]["field"] if config.incremental_fields else None)
    if should_use_incremental_field and config.incremental_mode == "desc_cutoff":
        cutoff = _coerce_cutoff(db_incremental_field_last_value)

    for items, next_cursor in _iter_pages(session, headers, logger, config.path, params, start_cursor):
        if items:
            yield items
        # Save AFTER yielding (and only when more pages remain) so a crash re-yields the last
        # page rather than skipping it — merge dedupes on the primary key.
        if next_cursor:
            resumable_source_manager.save_state(FeaturebaseResumeConfig(cursor=next_cursor))
        # Descending sweep short-circuit: once a whole page predates the watermark, every later
        # page is older still, so stop instead of re-walking full history each incremental sync.
        if cutoff_field and _page_predates_cutoff(items, cutoff_field, cutoff):
            logger.debug(f"Featurebase: {config.name} reached incremental watermark, stopping sweep")
            return


def _iter_post_ids(session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger) -> Iterator[str]:
    params = {"limit": FEATUREBASE_PAGE_SIZE, "sortBy": "createdAt", "sortOrder": "asc"}
    for items, _ in _iter_pages(session, headers, logger, "/posts", params):
        for item in items:
            if item.get("id"):
                yield item["id"]


def _get_post_voter_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    config: FeaturebaseEndpointConfig,
    resumable_source_manager: ResumableSourceManager[FeaturebaseResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every post, materializing upvoters as {postId, ...contact} rows.

    Voter removal has no timestamp on the API, so this table is full-refresh only; the resumable
    bookmark just lets a crashed sync pick up at the post it was processing.
    """
    post_ids = list(_iter_post_ids(session, headers, logger))

    # Resolve the saved post-ID bookmark to the slice of posts still to process. If the
    # bookmarked post no longer exists (deleted between attempts), start over from the first
    # post — merge dedupes the re-pulled rows on the composite primary key.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = post_ids
    resume_cursor: str | None = None
    if resume is not None and resume.post_id is not None and resume.post_id in post_ids:
        remaining = post_ids[post_ids.index(resume.post_id) :]
        resume_cursor = resume.cursor
        logger.debug(f"Featurebase: resuming post_voters from post_id={resume.post_id}")

    for index, post_id in enumerate(remaining):
        path = config.path.format(post_id=post_id)
        pages_fetched = 0
        try:
            for items, next_cursor in _iter_pages(
                session, headers, logger, path, {"limit": FEATUREBASE_PAGE_SIZE}, resume_cursor
            ):
                rows = [{**item, "postId": post_id} for item in items]
                if rows:
                    yield rows
                if next_cursor:
                    resumable_source_manager.save_state(FeaturebaseResumeConfig(cursor=next_cursor, post_id=post_id))
                pages_fetched += 1
                if pages_fetched >= MAX_VOTER_PAGES_PER_POST:
                    logger.warning(
                        f"Featurebase: post_voters page cap reached, truncating. post_id={post_id}, "
                        f"pages={pages_fetched}"
                    )
                    break
        except requests.HTTPError as exc:
            # A post deleted between enumeration and this fetch 404s. Skip it rather than
            # failing the whole sync — the votes are genuinely gone.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Featurebase: post {post_id} not found while fetching voters, skipping")
            else:
                raise
        finally:
            resume_cursor = None  # only the resumed-into post uses the saved cursor

        # Advance the bookmark to the next post so a crash between posts resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(FeaturebaseResumeConfig(cursor=None, post_id=remaining[index + 1]))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FeaturebaseResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = FEATUREBASE_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across every page (and, for the fan-out, every post) so urllib3 keeps
    # the connection alive instead of re-handshaking per request.
    session = _make_session(api_key)

    if config.fan_out_over_posts:
        yield from _get_post_voter_rows(session, headers, logger, config, resumable_source_manager)
        return

    yield from _get_top_level_rows(
        session,
        headers,
        logger,
        config,
        resumable_source_manager,
        should_use_incremental_field,
        db_incremental_field_last_value,
        incremental_field,
    )


def _resolve_sort_mode(config: FeaturebaseEndpointConfig, should_use_incremental_field: bool) -> SortMode:
    """The order rows are actually emitted in — SourceResponse.sort_mode must match it.

    Full-refresh runs sort ascending on the stable creation field. Incremental runs on
    "desc_cutoff" endpoints sweep newest-first, so the pipeline must only persist the
    watermark at successful job end. "server_filter" (changelogs) stays ascending.
    """
    if should_use_incremental_field and config.incremental_mode == "desc_cutoff":
        return "desc"
    return "asc"


def _webhook_table_transformer(table: pa.Table) -> pa.Table:
    """Collapse a webhook batch to the latest version of each object.

    Webhook payloads are the full notification envelope ({topic, createdAt, data: {item}}).
    Several events for the same object (e.g. post.created then post.updated) can land in one
    batch, and delta merge doesn't dedupe within a batch — keep only the newest per item id,
    shaped like the underlying API object so it merges cleanly with polled rows.
    """
    if "data" not in table.column_names:
        return table_from_py_list([])

    data_col = table.column("data").to_pylist()
    created_col = (
        table.column("createdAt").to_pylist() if "createdAt" in table.column_names else [None] * table.num_rows
    )

    best_by_id: dict[str, tuple[datetime, dict[str, Any]]] = {}
    for data, event_created in zip(data_col, created_col):
        if data is None:
            continue
        # `data` typically arrives as a nested dict (pyarrow struct), but defensively handle
        # the case where it's been serialized as a JSON string upstream.
        payload = orjson.loads(data) if isinstance(data, (str, bytes)) else dict(data)
        item = payload.get("item")
        if not isinstance(item, dict) or item.get("id") is None:
            continue
        ts = _parse_row_datetime(event_created) or datetime.min.replace(tzinfo=UTC)
        existing = best_by_id.get(item["id"])
        if existing is None or ts > existing[0]:
            best_by_id[item["id"]] = (ts, item)

    return table_from_py_list([item for _, item in best_by_id.values()])


def featurebase_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FeaturebaseResumeConfig],
    webhook_source_manager: WebhookSourceManager,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = FEATUREBASE_ENDPOINTS[endpoint]
    webhook_enabled = async_to_sync(webhook_source_manager.webhook_enabled)()

    def items():
        if webhook_enabled:
            return webhook_source_manager.get_items(table_transformer=_webhook_table_transformer)
        return get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        )

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        sort_mode=_resolve_sort_mode(config, should_use_incremental_field),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


# --- Webhook management -------------------------------------------------------------------


def _format_http_error(error: requests.HTTPError) -> str:
    response = error.response
    if response is None:
        return str(error)
    try:
        message = response.json().get("message")
    except Exception:
        message = None
    return message or f"Featurebase returned status {response.status_code}"


def all_desired_webhook_topics() -> list[str]:
    return [topic for topics in FEATUREBASE_OBJECT_TYPE_TO_TOPICS.values() for topic in topics]


def _list_webhooks(session: requests.Session, headers: dict[str, str]) -> list[dict[str, Any]]:
    webhooks: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": FEATUREBASE_PAGE_SIZE, **({"cursor": cursor} if cursor else {})}
        response = session.get(_build_url("/webhooks", params), headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        webhooks.extend(data.get("data", []))
        cursor = data.get("nextCursor")
        if not cursor:
            return webhooks


def _find_webhook_by_url(webhooks: list[dict[str, Any]], webhook_url: str) -> dict[str, Any] | None:
    for webhook in webhooks:
        if webhook.get("url") == webhook_url:
            return webhook
    return None


def create_webhook(api_key: str, webhook_url: str) -> WebhookCreationResult:
    session = _make_session(api_key)
    headers = _get_headers(api_key)
    payload = {
        "name": POSTHOG_WEBHOOK_NAME,
        "url": webhook_url,
        "description": "Streams Featurebase events into the PostHog data warehouse",
        "topics": all_desired_webhook_topics(),
    }
    try:
        response = session.post(_build_url("/webhooks", {}), headers=headers, json=payload, timeout=30)
        response.raise_for_status()
    except requests.HTTPError as e:
        # Featurebase caps webhooks per organization (default 10) and returns 400 at the cap.
        return WebhookCreationResult(success=False, error=_format_http_error(e))
    except requests.RequestException as e:
        return WebhookCreationResult(success=False, error=f"Could not reach Featurebase: {e}")

    # The create response includes the signing secret; persist it onto the hog function so the
    # template can verify X-Webhook-Signature without any manual setup.
    secret = response.json().get("secret")
    extra_inputs: dict[str, Any] = {"signing_secret": secret} if secret else {}
    return WebhookCreationResult(
        success=True, extra_inputs=extra_inputs, pending_inputs=[] if secret else ["signing_secret"]
    )


def sync_webhook_events(api_key: str, webhook_url: str, desired_topics: list[str]) -> WebhookSyncResult:
    session = _make_session(api_key)
    headers = _get_headers(api_key)
    try:
        webhook = _find_webhook_by_url(_list_webhooks(session, headers), webhook_url)
        if webhook is None:
            return WebhookSyncResult(success=False, error="No Featurebase webhook found for this source")
        if set(webhook.get("topics", [])) == set(desired_topics):
            return WebhookSyncResult(success=True)
        response = session.patch(
            _build_url(f"/webhooks/{webhook['id']}", {}),
            headers=headers,
            json={"topics": desired_topics},
            timeout=30,
        )
        response.raise_for_status()
    except requests.HTTPError as e:
        return WebhookSyncResult(success=False, error=_format_http_error(e))
    except requests.RequestException as e:
        return WebhookSyncResult(success=False, error=f"Could not reach Featurebase: {e}")
    return WebhookSyncResult(success=True)


def get_external_webhook_info(api_key: str, webhook_url: str) -> ExternalWebhookInfo:
    session = _make_session(api_key)
    headers = _get_headers(api_key)
    try:
        webhook = _find_webhook_by_url(_list_webhooks(session, headers), webhook_url)
    except requests.HTTPError as e:
        return ExternalWebhookInfo(exists=False, error=_format_http_error(e))
    except requests.RequestException as e:
        return ExternalWebhookInfo(exists=False, error=f"Could not reach Featurebase: {e}")

    if webhook is None:
        return ExternalWebhookInfo(exists=False)

    return ExternalWebhookInfo(
        exists=True,
        url=webhook.get("url"),
        enabled_events=webhook.get("topics"),
        status=webhook.get("status"),
        description=webhook.get("description"),
        created_at=webhook.get("createdAt"),
    )


def delete_webhook(api_key: str, webhook_url: str) -> WebhookDeletionResult:
    session = _make_session(api_key)
    headers = _get_headers(api_key)
    try:
        webhook = _find_webhook_by_url(_list_webhooks(session, headers), webhook_url)
        if webhook is None:
            # Nothing to delete — treat as success, matching the Stripe/GitHub sources.
            return WebhookDeletionResult(success=True)
        response = session.delete(_build_url(f"/webhooks/{webhook['id']}", {}), headers=headers, timeout=30)
        if response.status_code == 404:
            return WebhookDeletionResult(success=True)
        response.raise_for_status()
    except requests.HTTPError as e:
        return WebhookDeletionResult(success=False, error=_format_http_error(e))
    except requests.RequestException as e:
        return WebhookDeletionResult(success=False, error=f"Could not reach Featurebase: {e}")
    return WebhookDeletionResult(success=True)
