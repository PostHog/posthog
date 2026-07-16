import re
import dataclasses
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import pyarrow as pa
import requests
from asgiref.sync import async_to_sync
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookCreationResult,
    WebhookDeletionResult,
    WebhookSyncResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.gitea.settings import (
    GITEA_ENDPOINTS,
    PAGE_SIZE,
    GiteaEndpointConfig,
)

GITEA_API_PATH = "/api/v1"
REQUEST_TIMEOUT_SECONDS = 60
# Gitea instances have no rate limiting by default, but admins can enable it and
# self-hosted boxes are often small — back off on 429/5xx.
MAX_RETRY_ATTEMPTS = 5

# Managing repo webhooks needs admin rights on the repository; a read-scoped token gets
# 403 (or 404 when the instance hides the resource entirely).
_WEBHOOK_PERMISSION_HINT = "admin access to the repository (or a token with the `write:repository` scope)"


class GiteaRetryableError(Exception):
    pass


@dataclasses.dataclass
class GiteaResumeConfig:
    next_url: str


def normalize_host(host: str) -> str:
    """Normalize the instance URL and reject anything that isn't HTTPS.

    The access token travels in a header to a user-supplied host, so plaintext
    http:// is rejected to keep it off the wire in the clear. Bare hosts default
    to https.
    """
    host = host.strip()
    if not host:
        raise ValueError("Gitea instance URL is required")
    if "://" not in host:
        host = f"https://{host}"
    host = host.rstrip("/")
    parsed = urlparse(host)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"Invalid Gitea instance URL (must be https): {host}")
    return host


def hostname_of(host: str) -> str:
    return urlparse(normalize_host(host)).hostname or ""


def _api_url(base_url: str, path: str) -> str:
    return f"{normalize_host(base_url)}{GITEA_API_PATH}{path}"


def _get_session(access_token: str) -> requests.Session:
    # No-redirect session is an SSRF boundary: a user-supplied base_url must not be able
    # to bounce API calls (and the token header) to an internal host via a 3xx.
    return make_tracked_session(
        redact_values=(access_token,),
        headers={"Authorization": f"token {access_token}", "Accept": "application/json"},
        allow_redirects=False,
    )


def _pinned_url(base_url: str, url: str) -> str:
    """Pin a pagination URL to the validated Gitea origin.

    next_url comes from the response's Link header (and is persisted in resume state), so a
    tampered response must not be able to redirect the token-bearing request to another host,
    port, or a plaintext http:// URL. Anything off the configured https origin is rejected.
    """
    base, target = urlparse(normalize_host(base_url)), urlparse(url)
    if target.scheme != "https" or target.netloc.lower() != base.netloc.lower():
        raise ValueError(f"Gitea pagination URL {url!r} is not on the configured instance {base_url!r}")
    return url


def _parse_next_url(link_header: str) -> str | None:
    """Return the URL with rel="next" from Gitea's Link header, if any."""
    if not link_header:
        return None
    for part in link_header.split(","):
        part = part.strip()
        match = re.match(r'<([^>]+)>;\s*rel="next"', part)
        if match:
            return match.group(1)
    return None


def _format_timestamp(value: Any) -> str:
    """Format an incremental cursor as the RFC 3339 Z form Gitea's `since` expects."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return str(value)


def _build_initial_url(
    config: GiteaEndpointConfig,
    base_url: str,
    repository: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> str:
    params: dict[str, Any] = {"limit": PAGE_SIZE, **config.extra_params}
    # `since` is inclusive, so the boundary row is re-fetched and deduped by primary key
    # on merge — safer than missing a row updated in the same second as the watermark.
    if config.supports_since and should_use_incremental_field and db_incremental_field_last_value is not None:
        params["since"] = _format_timestamp(db_incremental_field_last_value)
    path = config.path.format(repository=repository)
    return f"{_api_url(base_url, path)}?{urlencode(params)}"


def validate_credentials(base_url: str, access_token: str, repository: str) -> tuple[bool, str | None]:
    """Confirm the token can read the configured repository."""
    url = _api_url(base_url, f"/repos/{repository}")
    try:
        response = _get_session(access_token).get(url, timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Gitea access token"
    if response.status_code == 404:
        return False, f"Repository '{repository}' not found or not accessible with this token"
    if 300 <= response.status_code < 400:
        return False, "The Gitea instance URL redirected the request; enter the instance's canonical https URL"

    try:
        message = response.json().get("message", response.text)
    except Exception:
        message = response.text
    return False, message


def _flatten_commit(item: dict[str, Any]) -> dict[str, Any]:
    """Lift the nested git author/committer info to top-level columns for easy querying."""
    commit_data = item.get("commit")
    if isinstance(commit_data, dict):
        item["message"] = commit_data.get("message")
        author = commit_data.get("author")
        if isinstance(author, dict):
            item["author_name"] = author.get("name")
            item["author_email"] = author.get("email")
        committer = commit_data.get("committer")
        if isinstance(committer, dict):
            item["committer_name"] = committer.get("name")
            item["committer_email"] = committer.get("email")

    # Top-level author/committer are Gitea user objects (null when the git identity
    # doesn't map to an instance account).
    user = item.get("author")
    if isinstance(user, dict):
        item["author_id"] = user.get("id")
        item["author_login"] = user.get("login")
    user = item.get("committer")
    if isinstance(user, dict):
        item["committer_id"] = user.get("id")
        item["committer_login"] = user.get("login")

    return item


def _get_item_mapper(endpoint: str) -> Callable[[dict[str, Any]], dict[str, Any]] | None:
    if endpoint == "commits":
        return _flatten_commit
    return None


@retry(
    retry=retry_if_exception_type(
        (
            GiteaRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, logger: FilteringBoundLogger) -> requests.Response:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise GiteaRetryableError(f"Gitea API error (retryable): status={response.status_code}, url={url}")

    # The session never follows redirects (SSRF boundary); a 3xx means the instance is
    # pointing us elsewhere, so treat it as a hard upstream error.
    if 300 <= response.status_code < 400:
        raise ValueError(f"Gitea API returned an unexpected redirect: status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Gitea API error: status={response.status_code}, body={response.text[:500]}, url={url}")
        response.raise_for_status()

    return response


def get_rows(
    base_url: str,
    access_token: str,
    repository: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GiteaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = GITEA_ENDPOINTS[endpoint]
    session = _get_session(access_token)
    item_mapper = _get_item_mapper(endpoint)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        url: str = _pinned_url(base_url, resume_config.next_url)
        logger.debug(f"Gitea: resuming from URL: {url}")
    else:
        url = _build_initial_url(
            config, base_url, repository, should_use_incremental_field, db_incremental_field_last_value
        )

    while True:
        response = _fetch_page(session, url, logger)
        data = response.json()
        if not isinstance(data, list) or not data:
            return

        rows = [item_mapper(item) if item_mapper else item for item in data if isinstance(item, dict)]
        next_url = _parse_next_url(response.headers.get("Link", ""))
        if next_url is not None:
            next_url = _pinned_url(base_url, next_url)

        if rows:
            yield rows

        if not next_url:
            return

        # Save state AFTER yielding so a crash re-yields the in-flight page
        # (merge dedupes on primary key).
        resumable_source_manager.save_state(GiteaResumeConfig(next_url=next_url))
        url = next_url


def _make_webhook_dedupe_transformer(primary_key: str, version_keys: list[str]) -> Callable[[pa.Table], pa.Table]:
    """Collapse a webhook batch to one row per ``primary_key`` — the one ranking newest by
    ``version_keys`` (newest first, NULLs last). Gitea emits one issue/PR as separate
    opened -> edited -> closed events sharing an id, and the delta merge doesn't dedupe
    within a source batch, so without this it keeps whichever event landed last in batch
    order and can freeze rows at a stale state."""

    def transform(table: pa.Table) -> pa.Table:
        present_version_keys = [key for key in version_keys if key in table.column_names]
        if table.num_rows == 0 or primary_key not in table.column_names or not present_version_keys:
            return table

        ids = table.column(primary_key).to_pylist()
        version_columns = [table.column(key).to_pylist() for key in present_version_keys]

        def rank(row_index: int) -> tuple[tuple[int, Any], ...]:
            # A present value beats NULL (NULLS LAST); among present values a larger one is
            # newer (ISO-8601 timestamps compare correctly as strings). The leading flag keeps
            # NULLs from ever being order-compared against a real value.
            return tuple(
                (1, column[row_index]) if column[row_index] is not None else (0, "") for column in version_columns
            )

        best_index_by_id: dict[Any, int] = {}
        for index, object_id in enumerate(ids):
            if object_id is None:
                continue
            best = best_index_by_id.get(object_id)
            # On a tie (>=, not >) the later-arriving row wins: timestamps are second-coarse,
            # and rows arrive in delivery order, so the later index is the newer event.
            if best is None or rank(index) >= rank(best):
                best_index_by_id[object_id] = index

        # Preserve input order among the survivors. Explicit int64 so an empty result doesn't
        # infer a null-typed index array.
        return table.take(pa.array(sorted(best_index_by_id.values()), type=pa.int64()))

    return transform


def gitea_source(
    base_url: str,
    access_token: str,
    repository: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GiteaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    webhook_source_manager: Optional[WebhookSourceManager] = None,
) -> SourceResponse:
    endpoint_config = GITEA_ENDPOINTS[endpoint]

    # Steady-state webhook ingestion replaces the poll once the initial backfill is
    # complete and the schema is in webhook sync mode; otherwise the poll path runs.
    webhook_enabled = (
        async_to_sync(webhook_source_manager.webhook_enabled)() if webhook_source_manager is not None else False
    )

    def items() -> Iterator[Any] | AsyncIterator[Any]:
        if webhook_enabled:
            assert webhook_source_manager is not None
            # The Hog template lands the nested issue/pull_request object as the row, which
            # matches the polled REST shape (Gitea serializes one struct per resource for
            # both). Collapse each drain batch to the latest event per id.
            transformer = (
                _make_webhook_dedupe_transformer(endpoint_config.primary_key, endpoint_config.version_keys)
                if endpoint_config.version_keys
                else None
            )
            return webhook_source_manager.get_items(table_transformer=transformer)

        return get_rows(
            base_url=base_url,
            access_token=access_token,
            repository=repository,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=[endpoint_config.primary_key],
        # Incremental endpoints (issues, commits) arrive newest-first while filtering
        # server-side on `since`, so the watermark persists at end of run (desc). See
        # settings.py for the per-endpoint verification notes.
        sort_mode=endpoint_config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def _is_repo_hook_permission_error(response: requests.Response) -> bool:
    """A token without repo admin rights can't manage webhooks — Gitea returns 403 (or 404
    when the resource is hidden from the token). Treat both as the permission case so
    callers fall back to manual setup instead of retrying."""
    return response.status_code in (403, 404)


def create_repo_webhook(
    base_url: str, access_token: str, repository: str, webhook_url: str, events: list[str], secret: str
) -> WebhookCreationResult:
    """Create a repo webhook via POST /repos/{repository}/hooks.

    Returns a failed (not raised) result when the token lacks admin rights so the caller
    can surface a manual-setup caption instead of hard-failing.
    """
    payload = {
        "type": "gitea",
        "active": True,
        "branch_filter": "*",
        "events": events,
        "config": {
            "url": webhook_url,
            "content_type": "json",
            "secret": secret,
        },
    }

    try:
        response = _get_session(access_token).post(
            _api_url(base_url, f"/repos/{repository}/hooks"), json=payload, timeout=30
        )
    except requests.exceptions.RequestException as e:
        return WebhookCreationResult(success=False, error=f"Failed to create webhook automatically: {e}")

    if response.status_code in (200, 201):
        # Gitea never echoes the secret back, so return the one we generated as
        # extra_inputs — the framework persists it onto the hog function's signing_secret
        # input, which the template uses to verify X-Gitea-Signature.
        return WebhookCreationResult(success=True, extra_inputs={"signing_secret": secret})

    if _is_repo_hook_permission_error(response):
        return WebhookCreationResult(
            success=False,
            error=(
                f"Your Gitea token lacks {_WEBHOOK_PERMISSION_HINT} needed to create a repository webhook. "
                "Add it and reconnect, or set up the webhook manually following the steps below."
            ),
        )

    return WebhookCreationResult(
        success=False, error=f"Failed to create webhook automatically: {response.status_code} {response.text}"
    )


def _list_repo_hooks(
    base_url: str, access_token: str, repository: str
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """List repo webhooks via GET /repos/{repository}/hooks. Returns (hooks, error); error is
    ``"permission"`` when the token lacks admin rights so callers can fall back to manual setup."""
    try:
        response = _get_session(access_token).get(
            _api_url(base_url, f"/repos/{repository}/hooks?limit={PAGE_SIZE}"), timeout=30
        )
    except requests.exceptions.RequestException as e:
        return None, str(e)

    if _is_repo_hook_permission_error(response):
        return None, "permission"
    if not response.ok:
        return None, f"{response.status_code} {response.text}"

    hooks = response.json()
    return (hooks if isinstance(hooks, list) else []), None


def _match_hook_by_url(hooks: list[dict[str, Any]], webhook_url: str) -> dict[str, Any] | None:
    for hook in hooks:
        # `config` can be present-but-null on some hook shapes; `or {}` guards the null case.
        if (hook.get("config") or {}).get("url") == webhook_url:
            return hook
    return None


def delete_repo_webhook(base_url: str, access_token: str, repository: str, webhook_url: str) -> WebhookDeletionResult:
    """Find the repo webhook matching webhook_url and DELETE /repos/{repository}/hooks/{id}."""
    hooks, error = _list_repo_hooks(base_url, access_token, repository)
    if error == "permission":
        return WebhookDeletionResult(
            success=False,
            error=f"Your Gitea token lacks {_WEBHOOK_PERMISSION_HINT}. Please delete the webhook manually.",
        )
    if error is not None:
        return WebhookDeletionResult(success=False, error=f"Failed to delete webhook: {error}")

    hook = _match_hook_by_url(hooks or [], webhook_url)
    if hook is None:
        # Nothing to delete — the end state we wanted.
        return WebhookDeletionResult(success=True)

    try:
        response = _get_session(access_token).delete(
            _api_url(base_url, f"/repos/{repository}/hooks/{hook['id']}"), timeout=30
        )
    except requests.exceptions.RequestException as e:
        return WebhookDeletionResult(success=False, error=f"Failed to delete webhook: {e}")

    # 404 here means the hook vanished between the list and the DELETE — also the end
    # state we wanted, so don't map it to the permission case.
    if response.status_code in (200, 204, 404):
        return WebhookDeletionResult(success=True)
    if response.status_code == 403:
        return WebhookDeletionResult(
            success=False,
            error=f"Your Gitea token lacks {_WEBHOOK_PERMISSION_HINT}. Please delete the webhook manually.",
        )
    return WebhookDeletionResult(
        success=False, error=f"Failed to delete webhook: {response.status_code} {response.text}"
    )


def update_repo_webhook_events(
    base_url: str, access_token: str, repository: str, webhook_url: str, events: list[str]
) -> WebhookSyncResult:
    """Add ``events`` to the repo webhook matching ``webhook_url``, writing only on drift.

    Additive on purpose: the PATCH sends the union of current and desired events, so
    events the user subscribed themselves are never dropped. Permission errors return a
    failed (not raised) result so schema-enable can proceed with a warning."""
    if not events:
        return WebhookSyncResult(success=True)

    hooks, error = _list_repo_hooks(base_url, access_token, repository)
    if error == "permission":
        return WebhookSyncResult(
            success=False,
            error=(
                f"Your Gitea token lacks {_WEBHOOK_PERMISSION_HINT} needed to update the repository webhook. "
                f"Add it and reconnect, or add these events to the webhook manually: {', '.join(events)}."
            ),
        )
    if error is not None:
        return WebhookSyncResult(success=False, error=f"Failed to update webhook events: {error}")

    hook = _match_hook_by_url(hooks or [], webhook_url)
    if hook is None:
        # No matching webhook, so nothing to reconcile (creation is handled elsewhere).
        return WebhookSyncResult(success=True)

    current = set(hook.get("events") or [])
    if all(event in current for event in events):
        return WebhookSyncResult(success=True)

    merged = sorted(current | set(events))
    try:
        response = _get_session(access_token).patch(
            _api_url(base_url, f"/repos/{repository}/hooks/{hook['id']}"), json={"events": merged}, timeout=30
        )
    except requests.exceptions.RequestException as e:
        return WebhookSyncResult(success=False, error=f"Failed to update webhook events: {e}")

    if response.ok:
        return WebhookSyncResult(success=True)
    return WebhookSyncResult(
        success=False, error=f"Failed to update webhook events: {response.status_code} {response.text}"
    )


def get_repo_webhook_info(base_url: str, access_token: str, repository: str, webhook_url: str) -> ExternalWebhookInfo:
    """List repo webhooks and match config.url == webhook_url."""
    hooks, error = _list_repo_hooks(base_url, access_token, repository)
    if error == "permission":
        return ExternalWebhookInfo(
            exists=False,
            error=f"Your Gitea token lacks {_WEBHOOK_PERMISSION_HINT} needed to read repository webhooks.",
        )
    if error is not None:
        return ExternalWebhookInfo(exists=False, error=f"Failed to check webhook status: {error}")

    hook = _match_hook_by_url(hooks or [], webhook_url)
    if hook is None:
        return ExternalWebhookInfo(exists=False)
    return ExternalWebhookInfo(
        exists=True,
        url=webhook_url,
        enabled_events=hook.get("events"),
        status="active" if hook.get("active") else "disabled",
        created_at=hook.get("created_at"),
    )
