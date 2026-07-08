import re
import random
import dataclasses
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, Optional
from urllib.parse import urlencode

import pyarrow as pa
import requests
from asgiref.sync import async_to_sync
from dateutil import parser as dateutil_parser
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from posthog.egress.github.transport import (
    GitHubEgressBudgetExhausted,
    GitHubRateLimitError,
    github_request,
    raise_if_github_rate_limited,
)
from posthog.egress.limiter.policies import Priority

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookCreationResult,
    WebhookDeletionResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.github.settings import (
    GITHUB_ENDPOINTS,
    GithubEndpointConfig,
)

GITHUB_BASE_URL = "https://api.github.com"

# Managing repo webhooks needs the `admin:repo_hook` scope on a classic token, or the
# "Repository webhooks: read and write" permission on a fine-grained token. Name both so
# the error/setup guidance doesn't mislead whichever token type the user connected.
_WEBHOOK_PERMISSION_HINT = (
    "the `admin:repo_hook` scope (classic token) or the "
    '"Repository webhooks: read and write" permission (fine-grained token)'
)


class GithubRetryableError(Exception):
    pass


class GithubEmptyRepositoryError(Exception):
    """GitHub returns 409 "Git Repository is empty." on the commits endpoint for
    a freshly created repo with no commits. `fetch_page` raises this so the
    caller can sync zero rows without re-parsing the response body."""

    pass


@dataclasses.dataclass
class GithubResumeConfig:
    next_url: str


@dataclasses.dataclass(frozen=True)
class GithubEgressIdentity:
    """Identity threaded to the HTTP chokepoint (``_fetch_page``) so it can gate on the shared
    per-installation egress budget and label telemetry.

    ``installation_id`` is the GitHub App installation id — the limiter's budget owner and the
    telemetry key, matching every other consumer of the same installation so the shared budget is
    genuinely shared. ``None`` on the PAT path (no installation, token-blind), which skips the gate and
    records request volume only — the pre-limiter behavior."""

    installation_id: str | None = None


def _format_incremental_value(value: Any) -> str:
    """Format incremental field value as ISO string for GitHub API filters."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).isoformat()
    return str(value)


def _build_initial_params(
    config: GithubEndpointConfig,
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    # workflow_runs has a different param surface: it accepts neither
    # state/sort/direction nor `since`, and always returns newest-first by
    # created_at. We intentionally send no time filter either — its `created`
    # filter would cap the result set to GitHub's 1,000-result search limit and
    # silently drop rows on busy repos. Incremental sync is handled instead by
    # paginating newest-first and stopping at the cursor (see get_rows), so the
    # request stays a plain paged read regardless of incremental state.
    if endpoint == "workflow_runs":
        return {"per_page": config.page_size}

    params: dict[str, Any] = {
        "per_page": config.page_size,
        "state": "all",
        # Default to created asc — created is immutable, so new items append
        # to the end and don't shift already-fetched pages.
        "sort": "created",
        "direction": "asc",
    }

    if should_use_incremental_field and db_incremental_field_last_value:
        formatted_value = _format_incremental_value(db_incremental_field_last_value)
        incremental = incremental_field or config.default_incremental_field or "updated_at"
        sort_field_mapping = {
            "updated_at": "updated",
            "created_at": "created",
        }
        if incremental not in sort_field_mapping:
            raise ValueError(
                f"Unsupported GitHub incremental field '{incremental}'. Expected one of: {sorted(sort_field_mapping)}."
            )
        params["sort"] = sort_field_mapping[incremental]
        params["direction"] = config.sort_mode
        if endpoint in ("issues", "commits"):
            params["since"] = formatted_value

    return params


def _build_initial_url(config: GithubEndpointConfig, repository: str, params: dict[str, Any]) -> str:
    path = config.path.format(repository=repository)
    if not params:
        return f"{GITHUB_BASE_URL}{path}"
    return f"{GITHUB_BASE_URL}{path}?{urlencode(params)}"


def _resolve_sort_mode(
    config: GithubEndpointConfig,
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Literal["asc", "desc"]:
    """The order rows are actually emitted in. SourceResponse.sort_mode must
    match this, otherwise the pipeline persists the cursor watermark assuming
    the wrong direction (e.g. advancing past unread older rows).

    Most endpoints emit asc on the first sync / full refresh (stable offset
    pagination via sort=created&direction=asc) and only flip to their
    configured sort once a cutoff exists. workflow_runs is different: it ignores
    sort/direction and always returns newest-first, so it emits desc on every
    sync — including the first. workflow_jobs inherits that order: it fans out
    over workflow_runs newest-first, so its jobs land newest-first too.
    """
    if endpoint in ("workflow_runs", "workflow_jobs"):
        return config.sort_mode
    if should_use_incremental_field and db_incremental_field_last_value:
        return config.sort_mode
    return "asc"


def _get_headers(access_token: str, endpoint: str = "") -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    # Stargazers needs this Accept header to include the starred_at timestamp.
    if endpoint == "stargazers":
        headers["Accept"] = "application/vnd.github.star+json"
    return headers


def _parse_next_url(link_header: str) -> str | None:
    """Return the URL with rel="next" from GitHub's Link header, if any."""
    if not link_header:
        return None
    for part in link_header.split(","):
        part = part.strip()
        match = re.match(r'<([^>]+)>;\s*rel="next"', part)
        if match:
            return match.group(1)
    return None


def _is_empty_repository_response(response: requests.Response) -> bool:
    """GitHub returns 409 Conflict on the commits endpoint when the repository
    has no commits yet (e.g. a freshly created, empty repo), with a stable
    "Git Repository is empty." message in the body. This is a valid, benign
    state — not a credential or config problem — so callers sync zero rows
    rather than raising (which otherwise retries the activity indefinitely)."""
    if response.status_code != 409:
        return False
    try:
        body = response.json()
        message = body.get("message", "") if isinstance(body, dict) else ""
    except (ValueError, TypeError):
        message = response.text or ""
    return isinstance(message, str) and "repository is empty" in message.lower()


def _as_utc(dt: datetime) -> datetime:
    """Treat naive datetimes as UTC so tz-aware values (GitHub returns ISO 8601
    with `Z`) can be safely compared against naive cutoffs from the DB."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _now_utc() -> datetime:
    """Wall clock as UTC. Wrapped so the first-sync lookback floor is patchable in tests."""
    return datetime.now(UTC)


def _is_older_than_cutoff(value: Any, cutoff: datetime) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        try:
            parsed_value = dateutil_parser.parse(value)
        except (ValueError, TypeError):
            return False
    elif isinstance(value, datetime):
        parsed_value = value
    else:
        return False
    return _as_utc(parsed_value) <= _as_utc(cutoff)


def _should_stop_desc(
    data: list[dict[str, Any]],
    sort_mode: str,
    incremental_field: str | None,
    cutoff: Any,
) -> bool:
    """Desc + incremental can stop the moment we see the first old record."""
    if sort_mode != "desc" or not incremental_field or not cutoff or not data:
        return False
    if not isinstance(cutoff, datetime):
        return False
    return any(_is_older_than_cutoff(item.get(incremental_field), cutoff) for item in data if item)


def validate_credentials(personal_access_token: str, repository: str) -> tuple[bool, str | None]:
    """Validate GitHub API credentials by making a test request to the repository."""
    url = f"{GITHUB_BASE_URL}/repos/{repository}"
    headers = {
        "Authorization": f"Bearer {personal_access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        response = make_tracked_session().get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            return True, None

        if response.status_code == 401:
            return False, "Invalid personal access token"

        if response.status_code == 404:
            return False, f"Repository '{repository}' not found or not accessible"

        try:
            error_data = response.json()
            message = error_data.get("message", response.text)
            return False, message
        except Exception:
            pass

        return False, response.text
    except requests.exceptions.RequestException as e:
        return False, str(e)


def _flatten_commit(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten commit data by extracting nested author/committer info."""
    if "commit" in item and isinstance(item["commit"], dict):
        commit_data = item["commit"]
        item["message"] = commit_data.get("message")

        if "author" in commit_data and isinstance(commit_data["author"], dict):
            item["author_name"] = commit_data["author"].get("name")
            item["author_email"] = commit_data["author"].get("email")
            item["created_at"] = commit_data["author"].get("date")

        if "committer" in commit_data and isinstance(commit_data["committer"], dict):
            item["committer_name"] = commit_data["committer"].get("name")
            item["committer_email"] = commit_data["committer"].get("email")
            item["committed_at"] = commit_data["committer"].get("date")

    if "author" in item and isinstance(item["author"], dict):
        item["author_id"] = item["author"].get("id")
        item["author_login"] = item["author"].get("login")

    if "committer" in item and isinstance(item["committer"], dict):
        item["committer_id"] = item["committer"].get("id")
        item["committer_login"] = item["committer"].get("login")

    return item


def _flatten_stargazer(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten stargazer data when using starred_at timestamp."""
    if "user" in item and isinstance(item["user"], dict):
        user = item.pop("user")
        item["id"] = user["id"]
        item["login"] = user.get("login")
        item["avatar_url"] = user.get("avatar_url")
        item["type"] = user.get("type")
    return item


def _is_issue_not_pr(item: dict[str, Any]) -> bool:
    """Exclude pull requests from the issues endpoint.

    GitHub's Issues API returns both issues and PRs. PRs can be identified
    by the presence of the 'pull_request' key in the response.
    """
    return "pull_request" not in item or item["pull_request"] is None


def _get_item_mapper(endpoint: str) -> Callable[[dict[str, Any]], dict[str, Any]] | None:
    if endpoint == "commits":
        return _flatten_commit
    if endpoint == "stargazers":
        return _flatten_stargazer
    return None


def _get_item_filter(endpoint: str) -> Callable[[dict[str, Any]], bool] | None:
    if endpoint == "issues":
        return _is_issue_not_pr
    return None


# Upper bound on how long we'll honor GitHub's rate-limit reset before retrying,
# so a misreported reset header can't stall a worker indefinitely. The source
# iterator runs in a thread pool while the activity's liveness heartbeat fires
# from the event loop every heartbeat_timeout/30 (~4s), so a 300s wait here does
# not trip the 2-min heartbeat timeout. Mirrors common/rest_source/rest_client.py.
GITHUB_MAX_RETRY_AFTER_SECONDS = 300.0

# Plain backoff for transient blips (5xx, connection resets) where GitHub gives
# us no reset to honor.
_github_backoff_wait = wait_exponential_jitter(initial=1, max=30)

# Disable the tracked session's default adapter retries on this path. That policy
# retries 429/5xx and honors Retry-After *uncapped*, underneath _fetch_page — which
# would defeat the 300s cap below and stack a second, untested retry layer. With
# adapter retries off, _fetch_page sees every response/exception and our tenacity
# layer is the single, rate-limit-aware retry authority.
_NO_ADAPTER_RETRY = Retry(total=0)


def _github_retry_wait(state: RetryCallState) -> float:
    """Sleep until GitHub's advertised rate-limit reset when it gave us one
    (capped, plus a little jitter so the sources sharing one installation's
    budget don't all wake at the same reset instant); otherwise fall back to
    exponential backoff."""
    if state.outcome is not None and state.outcome.failed:
        exc = state.outcome.exception()
        if isinstance(exc, GitHubRateLimitError) and exc.retry_after is not None:
            return min(float(exc.retry_after), GITHUB_MAX_RETRY_AFTER_SECONDS) + random.uniform(0, 1)
    return _github_backoff_wait(state)


@retry(
    retry=retry_if_exception_type(
        (
            GithubRetryableError,
            # Our egress limiter shed this deferrable page (BATCH); back off and re-acquire next attempt.
            GitHubEgressBudgetExhausted,
            GitHubRateLimitError,
            requests.ReadTimeout,
            requests.ConnectionError,
            # GitHub can break the connection mid-body on a chunked response, which surfaces as a
            # ChunkedEncodingError (a direct RequestException subclass, not a ConnectionError). It's
            # transient — a fresh GET re-fetches the page — so retry it instead of failing the sync.
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=_github_retry_wait,
    reraise=True,
)
def _fetch_page(
    page_url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    egress_identity: GithubEgressIdentity | None = None,
) -> requests.Response:
    # One gated + recorded GET through the shared egress client. The App path bills the shared
    # per-installation budget at BATCH (deferrable bulk); the PAT path (installation_id None) skips the
    # gate and records volume only. On a BATCH denial the client raises GitHubEgressBudgetExhausted, which
    # this function's @retry backs off on; transport failures are recorded and re-raised for the same
    # retry. We keep our own tracked session and the GitHub response→exception mapping below.
    installation_id = egress_identity.installation_id if egress_identity is not None else None
    response = github_request(
        "GET",
        page_url,
        source="warehouse",
        headers=headers,
        installation_id=installation_id,
        priority=Priority.BATCH,
        timeout=60,
        session=make_tracked_session(retry=_NO_ADAPTER_RETRY),
    )

    # Transient server errors: retry with plain exponential backoff.
    if response.status_code >= 500:
        raise GithubRetryableError(f"Github API error (retryable): status={response.status_code}, url={page_url}")

    # Rate limited (secondary 429, or primary 403 with a rate-limit body): raise
    # so we retry honoring the reset/Retry-After. A genuine permission 403 carries
    # no rate-limit body and falls through to raise_for_status below, staying fatal.
    raise_if_github_rate_limited(response)

    # An empty repository (no commits yet) returns 409 on the commits
    # endpoint. Signal it so the loop can sync zero rows without raising
    # a hard error (which would otherwise retry the activity indefinitely).
    if _is_empty_repository_response(response):
        raise GithubEmptyRepositoryError()

    if not response.ok:
        logger.error(f"Github API error: status={response.status_code}, body={response.text}, url={page_url}")
        response.raise_for_status()

    return response


def _iter_pages(
    url: str,
    headers: dict[str, str],
    response_data_path: str | None,
    logger: FilteringBoundLogger,
    max_pages: int | None = None,
    page_cap_context: dict[str, Any] | None = None,
    egress_identity: GithubEgressIdentity | None = None,
) -> Iterator[tuple[list[dict[str, Any]], str]]:
    """Yield (items, page_url) for each page of a paginated GitHub list,
    unwrapping the envelope and following the Link header. Stops at ``max_pages``,
    logging a structured warning when the cap is reached. An empty or ``null``
    envelope body simply ends iteration — there is nothing to truncate."""
    page_count = 0
    while True:
        response = _fetch_page(url, headers, logger, egress_identity)
        data = response.json()
        if response_data_path and isinstance(data, dict):
            data = data.get(response_data_path) or []
        if not isinstance(data, list) or not data:
            return
        next_url = _parse_next_url(response.headers.get("Link", ""))
        yield data, url
        page_count += 1
        if not next_url:
            return
        if max_pages is not None and page_count >= max_pages:
            logger.warning(
                "Github: per-parent page cap reached; remaining pages skipped",
                max_pages=max_pages,
                **(page_cap_context or {}),
            )
            return
        url = next_url


def _iter_jobs_for_run(
    repository: str,
    run_id: Any,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    config: GithubEndpointConfig,
    egress_identity: GithubEgressIdentity | None = None,
) -> Iterator[dict[str, Any]]:
    path = config.path.format(repository=repository, run_id=run_id)
    params: dict[str, Any] = {"per_page": config.page_size, **(config.extra_params or {})}
    url = f"{GITHUB_BASE_URL}{path}?{urlencode(params)}"
    for jobs, _page_url in _iter_pages(
        url,
        headers,
        config.response_data_path,
        logger,
        max_pages=config.max_pages_per_parent,
        page_cap_context={"repository": repository, "run_id": run_id},
        egress_identity=egress_identity,
    ):
        yield from jobs


def _fan_out_get_rows(
    personal_access_token: str,
    repository: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GithubResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
    egress_identity: GithubEgressIdentity | None = None,
) -> Iterator[Any]:
    """Single-hop parent->child fan-out: walk the parent endpoint newest-first and
    emit every child row for each parent. Incremental bounding happens on the
    parent's created_at cursor (the same desc early-stop workflow_runs uses).

    The child cursor value (max job created_at) is compared against the parent's
    created_at — they coincide closely since a job is created when its run starts,
    so the watermark sits slightly above the newest run's timestamp. Re-reading a
    boundary parent is harmless (jobs upsert by id), but note the inverse: a run
    that was in_progress when first synced drops below the watermark once it
    finishes, so its terminal job conclusions and any later-added jobs are not
    re-fetched. This is the same created_at-cursor staleness workflow_runs carries;
    the workflow_run webhook (followup) is the fix, not re-scanning history.
    """
    child_config = GITHUB_ENDPOINTS[endpoint]
    assert child_config.fan_out_parent is not None  # guarded by the get_rows dispatch
    parent_config = GITHUB_ENDPOINTS[child_config.fan_out_parent]
    headers = _get_headers(personal_access_token, endpoint)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    parent_field = incremental_field or parent_config.default_incremental_field or "created_at"
    parent_cutoff = db_incremental_field_last_value if should_use_incremental_field else None

    # First incremental sync (watermark set up, but nothing synced yet): floor the
    # backfill at a recent window instead of fanning out over the repo's entire run
    # history. Scoped to the incremental first run on purpose — an explicit full
    # refresh still pulls everything, and later syncs advance from their watermark.
    if (
        should_use_incremental_field
        and db_incremental_field_last_value is None
        and child_config.initial_lookback_days is not None
    ):
        parent_cutoff = _now_utc() - timedelta(days=child_config.initial_lookback_days)
        logger.debug(f"Github: flooring {endpoint} first-sync fan-out at {parent_cutoff.isoformat()}")

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        parent_url: str = resume_config.next_url
        logger.debug(f"Github: resuming {endpoint} fan-out from parent URL: {parent_url}")
    else:
        parent_url = _build_initial_url(parent_config, repository, {"per_page": parent_config.page_size})

    for runs, page_url in _iter_pages(
        parent_url, headers, parent_config.response_data_path, logger, egress_identity=egress_identity
    ):
        stop_after_this_page = _should_stop_desc(runs, "desc", parent_field, parent_cutoff)

        for run in runs:
            # Direct access on the run's id (its primary key): a run without one is a broken
            # response that should fail loudly, not get silently dropped.
            run_id = run["id"]
            # Only fan out parents at/above the watermark; older ones were synced before.
            if parent_cutoff is not None and _is_older_than_cutoff(run.get(parent_field), parent_cutoff):
                continue
            for job in _iter_jobs_for_run(repository, run_id, headers, logger, child_config, egress_identity):
                batcher.batch(job)
                if batcher.should_yield():
                    yield batcher.get_table()
                    # Checkpoint the parent page; resume re-fans it out and dedupes by id.
                    if not stop_after_this_page:
                        resumable_source_manager.save_state(GithubResumeConfig(next_url=page_url))

        if stop_after_this_page:
            break

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def get_rows(
    personal_access_token: str,
    repository: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GithubResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
    egress_identity: GithubEgressIdentity | None = None,
) -> Iterator[Any]:
    config = GITHUB_ENDPOINTS[endpoint]
    if config.fan_out_parent is not None:
        yield from _fan_out_get_rows(
            personal_access_token=personal_access_token,
            repository=repository,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
            egress_identity=egress_identity,
        )
        return

    headers = _get_headers(personal_access_token, endpoint)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    actual_sort_mode = _resolve_sort_mode(
        config, endpoint, should_use_incremental_field, db_incremental_field_last_value
    )

    stop_field: str | None = None
    stop_cutoff: Any = None
    if actual_sort_mode == "desc" and should_use_incremental_field:
        stop_field = incremental_field or config.default_incremental_field
        stop_cutoff = db_incremental_field_last_value

    item_filter = _get_item_filter(endpoint)
    item_mapper = _get_item_mapper(endpoint)

    initial_params = _build_initial_params(
        config, endpoint, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        url: str = resume_config.next_url
        logger.debug(f"Github: resuming from URL: {url}")
    else:
        url = _build_initial_url(config, repository, initial_params)

    while True:
        try:
            response = _fetch_page(url, headers, logger, egress_identity)
        except GithubEmptyRepositoryError:
            logger.debug(f"Github: repository has no commits (empty repository), syncing zero rows: url={url}")
            break

        data = response.json()
        # Most GitHub list endpoints return a JSON array at the top level,
        # but some (e.g. /actions/runs) wrap results in {"<resource>": [...]}.
        if config.response_data_path and isinstance(data, dict):
            data = data.get(config.response_data_path, [])
        if not isinstance(data, list) or not data:
            break

        next_url = _parse_next_url(response.headers.get("Link", ""))
        stop_after_this_page = _should_stop_desc(data, actual_sort_mode, stop_field, stop_cutoff)

        # Chunk boundaries don't align with page boundaries (issues drops
        # PRs, items can also straddle the chunk_size cap), so checkpoint
        # the CURRENT page URL. On resume we re-fetch the current page and
        # rely on primary_keys merge semantics to dedupe already-yielded
        # items; this avoids silently dropping items that were batched but
        # not yet yielded when the worker restarts.
        checkpoint_url = url

        for item in data:
            if item_filter and not item_filter(item):
                continue
            if item_mapper:
                item = item_mapper(item)
            batcher.batch(item)

            if batcher.should_yield():
                py_table = batcher.get_table()
                yield py_table

                if not stop_after_this_page:
                    resumable_source_manager.save_state(GithubResumeConfig(next_url=checkpoint_url))

        if stop_after_this_page or not next_url:
            break

        url = next_url

    if batcher.should_yield(include_incomplete_chunk=True):
        py_table = batcher.get_table()
        yield py_table


def _make_webhook_dedupe_transformer(primary_key: str, version_keys: list[str]) -> Callable[[pa.Table], pa.Table]:
    """Collapse a webhook batch to one row per ``primary_key`` — the one ranking newest by
    ``version_keys`` (newest first, NULLs last). GitHub emits a single run/job as separate
    queued -> in_progress -> completed events sharing an id, and the delta merge doesn't dedupe
    within a source batch, so without this it keeps whichever event landed last in batch order and
    freezes rows pre-completion. Same problem and same fix as the Stripe webhook source."""

    def transform(table: pa.Table) -> pa.Table:
        present_version_keys = [key for key in version_keys if key in table.column_names]
        if table.num_rows == 0 or primary_key not in table.column_names or not present_version_keys:
            return table

        ids = table.column(primary_key).to_pylist()
        version_columns = [table.column(key).to_pylist() for key in present_version_keys]

        def rank(row_index: int) -> tuple[tuple[int, Any], ...]:
            # A present value beats NULL (NULLS LAST); among present values a larger one is newer
            # (ISO-8601 timestamps compare correctly as strings). The leading flag keeps NULLs from
            # ever being order-compared against a real value.
            return tuple(
                (1, column[row_index]) if column[row_index] is not None else (0, "") for column in version_columns
            )

        best_index_by_id: dict[Any, int] = {}
        for index, object_id in enumerate(ids):
            if object_id is None:
                continue
            best = best_index_by_id.get(object_id)
            # On a tie (>=, not >) the later-arriving row wins. GitHub timestamps are second-coarse,
            # so a fast in_progress -> completed transition can share an updated_at; rows arrive in
            # chronological order (files read oldest-first), so the later index is the newer event.
            if best is None or rank(index) >= rank(best):
                best_index_by_id[object_id] = index

        # Preserve input order among the survivors so the batch stays in arrival order. The indices
        # are an explicit int64 array so an empty result doesn't infer a null-typed index array.
        return table.take(pa.array(sorted(best_index_by_id.values()), type=pa.int64()))

    return transform


def github_source(
    personal_access_token: str,
    repository: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GithubResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
    webhook_source_manager: Optional[WebhookSourceManager] = None,
    egress_identity: GithubEgressIdentity | None = None,
) -> SourceResponse:
    endpoint_config = GITHUB_ENDPOINTS[endpoint]

    actual_sort_mode = _resolve_sort_mode(
        endpoint_config, endpoint, should_use_incremental_field, db_incremental_field_last_value
    )

    # Steady-state webhook ingestion replaces the poll fan-out once the initial
    # backfill is complete and a webhook function is enabled. When no manager is
    # passed (or it isn't enabled), the poll path below stays unchanged.
    #
    # An endpoint whose poll does no first-sync backfill (initial_lookback_days == 0,
    # i.e. workflow_jobs) would otherwise deadlock a fresh webhook schema: the
    # zero-row poll never creates a table, so initial_sync_complete is never set, so
    # webhook_enabled stays False forever and queued webhook files never drain. There
    # is no backfill to lose for these, so activate webhook mode from the first run
    # (skip the initial_sync_complete gate), the same way the Slack source does.
    skip_initial_sync_complete_check = endpoint_config.initial_lookback_days == 0
    webhook_enabled = (
        async_to_sync(webhook_source_manager.webhook_enabled)(skip_initial_sync_complete_check)
        if webhook_source_manager is not None
        else False
    )

    def items() -> Iterator[Any] | AsyncIterator[Any]:
        if webhook_enabled:
            assert webhook_source_manager is not None
            # The Hog template lands the nested workflow_job / workflow_run object as the
            # row, with no transform — it matches the polled REST shape. GitHub defines the
            # job and workflow-run objects once: the "list jobs for a workflow run" REST
            # response object is the same schema as the workflow_job webhook event's nested
            # workflow_job object (same for workflow_run), so the rows are interchangeable.
            #
            # Each event for an id arrives as its own row (queued -> in_progress -> completed);
            # collapse them to the latest per id here, since the delta merge doesn't dedupe a
            # source batch. Same pattern as the Stripe webhook source.
            transformer = (
                _make_webhook_dedupe_transformer(endpoint_config.primary_key, endpoint_config.version_keys)
                if endpoint_config.version_keys
                else None
            )
            return webhook_source_manager.get_items(table_transformer=transformer)

        return get_rows(
            personal_access_token=personal_access_token,
            repository=repository,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
            egress_identity=egress_identity,
        )

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=[endpoint_config.primary_key],
        sort_mode=actual_sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def _is_repo_hook_permission_error(response: requests.Response) -> bool:
    """A token without admin:repo_hook can't manage repo webhooks — GitHub returns
    403 (or 404 when the resource is hidden from the token). Treat both as the
    permission case so callers fall back to manual setup instead of retrying."""
    return response.status_code in (403, 404)


def create_repo_webhook(
    token: str, repo: str, webhook_url: str, events: list[str], secret: str
) -> WebhookCreationResult:
    """Create a repo webhook via POST /repos/{repo}/hooks.

    Returns a failed (not raised) result when the token lacks admin:repo_hook so
    the caller can surface a manual-setup caption instead of hard-failing.
    """
    headers = _get_headers(token)
    payload = {
        "name": "web",
        "active": True,
        "events": events,
        "config": {
            "url": webhook_url,
            "content_type": "json",
            "secret": secret,
        },
    }

    try:
        response = make_tracked_session().post(
            f"{GITHUB_BASE_URL}/repos/{repo}/hooks", headers=headers, json=payload, timeout=30
        )
    except requests.exceptions.RequestException as e:
        return WebhookCreationResult(success=False, error=f"Failed to create webhook automatically: {e}")

    if response.status_code in (200, 201):
        # GitHub never echoes the secret back, so we return the one we generated as
        # extra_inputs — the framework persists it onto the hog function's
        # signing_secret input, which the template uses to verify X-Hub-Signature-256.
        return WebhookCreationResult(success=True, extra_inputs={"signing_secret": secret})

    if _is_repo_hook_permission_error(response):
        return WebhookCreationResult(
            success=False,
            error=(
                f"Your GitHub token lacks {_WEBHOOK_PERMISSION_HINT} needed to create a repository webhook. "
                "Add it and reconnect, or set up the webhook manually following the steps below."
            ),
        )

    return WebhookCreationResult(
        success=False, error=f"Failed to create webhook automatically: {response.status_code} {response.text}"
    )


def _list_repo_hooks(token: str, repo: str) -> tuple[list[dict[str, Any]] | None, str | None]:
    """List repo webhooks via GET /repos/{repo}/hooks. Returns (hooks, error); error is
    ``"permission"`` when the token lacks admin:repo_hook so callers can fall back to manual setup."""
    try:
        response = make_tracked_session().get(
            f"{GITHUB_BASE_URL}/repos/{repo}/hooks", headers=_get_headers(token), params={"per_page": 100}, timeout=30
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
    """Return the hook whose config.url matches webhook_url, or None."""
    for hook in hooks:
        # `config` can be present-but-null on some hook shapes; `or {}` guards the
        # null case that a plain `.get("config", {})` default would not.
        if (hook.get("config") or {}).get("url") == webhook_url:
            return hook
    return None


def _find_repo_hook_id(token: str, repo: str, webhook_url: str) -> tuple[int | None, str | None]:
    """Return (hook_id, error). Matches on config.url == webhook_url."""
    hooks, error = _list_repo_hooks(token, repo)
    if error is not None:
        return None, error
    hook = _match_hook_by_url(hooks or [], webhook_url)
    return (hook.get("id") if hook else None), None


def delete_repo_webhook(token: str, repo: str, webhook_url: str) -> WebhookDeletionResult:
    """Find the repo webhook matching webhook_url and DELETE /repos/{repo}/hooks/{id}."""
    hook_id, error = _find_repo_hook_id(token, repo, webhook_url)
    if error == "permission":
        return WebhookDeletionResult(
            success=False,
            error=f"Your GitHub token lacks {_WEBHOOK_PERMISSION_HINT}. Please delete the webhook manually.",
        )
    if error is not None:
        return WebhookDeletionResult(success=False, error=f"Failed to delete webhook: {error}")
    if hook_id is None:
        # Nothing to delete — treat as success, same as Stripe's no-match path.
        return WebhookDeletionResult(success=True)

    headers = _get_headers(token)
    try:
        response = make_tracked_session().delete(
            f"{GITHUB_BASE_URL}/repos/{repo}/hooks/{hook_id}", headers=headers, timeout=30
        )
    except requests.exceptions.RequestException as e:
        return WebhookDeletionResult(success=False, error=f"Failed to delete webhook: {e}")

    # 404 here means the hook vanished between the list and the DELETE (concurrent
    # delete, manual removal) — the end state we wanted, so treat it as success
    # rather than the permission case _is_repo_hook_permission_error would assign.
    if response.status_code in (200, 204, 404):
        return WebhookDeletionResult(success=True)
    if _is_repo_hook_permission_error(response):
        return WebhookDeletionResult(
            success=False,
            error=f"Your GitHub token lacks {_WEBHOOK_PERMISSION_HINT}. Please delete the webhook manually.",
        )
    return WebhookDeletionResult(
        success=False, error=f"Failed to delete webhook: {response.status_code} {response.text}"
    )


def get_repo_webhook_info(token: str, repo: str, webhook_url: str) -> ExternalWebhookInfo:
    """List repo webhooks via GET /repos/{repo}/hooks and match config.url == webhook_url."""
    hooks, error = _list_repo_hooks(token, repo)
    if error == "permission":
        return ExternalWebhookInfo(
            exists=False,
            error=f"Your GitHub token lacks {_WEBHOOK_PERMISSION_HINT} needed to read repository webhooks.",
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
