import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.doppler.settings import (
    DEFAULT_PER_PAGE,
    DOPPLER_ENDPOINTS,
    DopplerEndpointConfig,
)

DOPPLER_BASE_URL = "https://api.doppler.com/v3"


class DopplerRetryableError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class DopplerResumeConfig:
    # Next 1-indexed page to fetch.
    next_page: int = 1
    # Fan-out bookmark: slug of the project currently being processed. A stable slug (not a
    # positional index) so projects created or deleted between a crash and the retry can't resume
    # into the wrong project. None for workplace-level endpoints.
    project: str | None = None
    # Second-level fan-out bookmark: name of the config currently being processed. Only set for
    # config-scoped endpoints.
    config: str | None = None


def _headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_token}", "Accept": "application/json"}


def _build_url(path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{DOPPLER_BASE_URL}{path}"
    return f"{DOPPLER_BASE_URL}{path}?{urlencode(params)}"


def _parse_doppler_datetime(value: Any) -> datetime | None:
    """Parse Doppler's ISO 8601 `Z`-suffixed timestamps into an aware datetime."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _coerce_watermark(value: Any) -> datetime | None:
    """Normalize the stored incremental watermark into an aware datetime for row comparisons."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str):
        return _parse_doppler_datetime(value)
    return None


@retry(
    # Doppler enforces plan-tiered per-minute read limits and returns 429 with a retry-after
    # header when exceeded; transient 5xx are retryable too.
    retry=retry_if_exception_type((DopplerRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    response = session.get(url, headers=headers, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise DopplerRetryableError(f"Doppler API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Doppler API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _redact_secret_values(item: dict[str, Any]) -> dict[str, Any]:
    """Strip the secret values out of a config log's `diff`, keeping the secret names.

    Doppler reports each changed secret as `{"name", "added", "removed"}`, where `added` and
    `removed` are the plaintext values. The names are what a change history is read for, so they
    stay; the values would put live credentials in the warehouse. An undocumented shape is
    dropped rather than passed through, since anything in this field may be a secret.
    """
    diff = item.get("diff")
    if diff is None:
        return item
    if not isinstance(diff, list):
        return {**item, "diff": None}
    return {
        **item,
        "diff": [
            {
                "name": change.get("name"),
                "added": change.get("added") is not None,
                "removed": change.get("removed") is not None,
            }
            for change in diff
            if isinstance(change, dict)
        ],
    }


@dataclasses.dataclass(frozen=True)
class _FanOutParent:
    """A project — and for config-scoped endpoints, a config within it — to issue one request-set for."""

    project: str
    config: str | None = None

    @property
    def params(self) -> dict[str, str]:
        if self.config is None:
            return {"project": self.project}
        return {"project": self.project, "config": self.config}


def _iter_project_slugs(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[str]:
    page = 1
    while True:
        url = _build_url("/projects", {"page": page, "per_page": DEFAULT_PER_PAGE})
        projects = _fetch_page(session, url, headers, logger).get("projects") or []
        for project in projects:
            slug = project.get("slug") or project.get("id")
            if slug:
                yield slug

        if len(projects) < DEFAULT_PER_PAGE:
            break
        page += 1


def _iter_config_names(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger, project_slug: str
) -> Iterator[str]:
    page = 1
    while True:
        url = _build_url("/configs", {"project": project_slug, "page": page, "per_page": DEFAULT_PER_PAGE})
        configs = _fetch_page(session, url, headers, logger).get("configs") or []
        for item in configs:
            name = item.get("name")
            if name:
                yield name

        if len(configs) < DEFAULT_PER_PAGE:
            break
        page += 1


def _iter_fan_out_parents(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    endpoint_config: DopplerEndpointConfig,
) -> Iterator[_FanOutParent]:
    for project_slug in _iter_project_slugs(session, headers, logger):
        if not endpoint_config.fan_out_over_configs:
            yield _FanOutParent(project=project_slug)
            continue
        for config_name in _iter_config_names(session, headers, logger, project_slug):
            yield _FanOutParent(project=project_slug, config=config_name)


def _resume_at(parent: _FanOutParent, next_page: int) -> DopplerResumeConfig:
    return DopplerResumeConfig(next_page=next_page, project=parent.project, config=parent.config)


def _get_fan_out_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DopplerResumeConfig],
    endpoint_config: DopplerEndpointConfig,
    resume: DopplerResumeConfig | None,
) -> Iterator[Any]:
    """Fan out over every project, and for config-scoped endpoints every config within it.

    Most of Doppler's project-scoped responses echo `project` back on each row, so the composite
    primary keys need no parent injection; `inject_project` covers the ones that don't.
    """
    parents = list(_iter_fan_out_parents(session, headers, logger, endpoint_config))

    # Resolve the saved bookmark to the slice of parents still to process. If the bookmarked
    # parent no longer exists (deleted between runs), start over from the first one — merge
    # dedupes the re-pulled rows on the primary key.
    remaining = parents
    resume_page = 1
    if resume is not None and resume.project is not None:
        bookmark = _FanOutParent(project=resume.project, config=resume.config)
        if bookmark in parents:
            remaining = parents[parents.index(bookmark) :]
            resume_page = resume.next_page or 1
            logger.debug(f"Doppler: resuming {endpoint_config.name} from {bookmark}, page={resume_page}")

    for index, parent in enumerate(remaining):
        page = resume_page
        resume_page = 1  # only the resumed-into parent starts mid-way; the rest start at page 1

        while True:
            params: dict[str, Any] = dict(parent.params)
            if endpoint_config.paginated:
                params["page"] = page
                if endpoint_config.per_page is not None:
                    params["per_page"] = endpoint_config.per_page

            data = _fetch_page(session, _build_url(endpoint_config.path, params), headers, logger)
            items = data.get(endpoint_config.data_key) or []
            if endpoint_config.inject_project:
                items = [{**item, "project": parent.project} for item in items]
            if endpoint_config.carries_secret_values:
                items = [_redact_secret_values(item) for item in items]
            if items:
                yield items

            has_more = (
                endpoint_config.paginated
                and endpoint_config.per_page is not None
                and len(items) >= endpoint_config.per_page
            )
            if not has_more:
                break
            # Save AFTER yielding so a crash re-yields the last page rather than skipping it —
            # merge dedupes on the primary key.
            resumable_source_manager.save_state(_resume_at(parent, page + 1))
            page += 1

        # Advance the bookmark to the next parent so a crash between parents resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(_resume_at(remaining[index + 1], 1))


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DopplerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    config = DOPPLER_ENDPOINTS[endpoint]
    headers = _headers(api_token)
    # One session reused across every page (and, for fan-out, every project) so urllib3 keeps the
    # connection alive instead of re-handshaking per request.
    session = make_tracked_session(capture=not config.carries_secret_values)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.fan_out_over_projects or config.fan_out_over_configs:
        yield from _get_fan_out_rows(session, headers, logger, resumable_source_manager, config, resume)
        return

    watermark = (
        _coerce_watermark(db_incremental_field_last_value)
        if should_use_incremental_field and config.incremental_fields
        else None
    )

    page = resume.next_page if resume is not None and resume.next_page else 1
    if page > 1:
        logger.debug(f"Doppler: resuming {endpoint} from page {page}")

    while True:
        params: dict[str, Any] = {}
        if config.paginated:
            params["page"] = page
            if config.per_page is not None:
                params["per_page"] = config.per_page

        data = _fetch_page(session, _build_url(config.path, params), headers, logger)
        items = data.get(config.data_key) or []
        if not items:
            break

        if watermark is not None:
            # The activity log has no server-side time filter, but it's append-only and returned
            # newest-first, so incremental syncs page from the top and stop at the watermark.
            # Rows with a missing/unparseable created_at are kept — merge dedupes on the primary key.
            fresh = [item for item in items if _is_after_watermark(item, config, watermark)]
            if fresh:
                yield fresh
            if len(fresh) < len(items):
                # Once a row at or before the watermark appears, every remaining page is older.
                break
        else:
            yield items

        has_more = config.paginated and (len(items) >= config.per_page if config.per_page is not None else True)
        if not has_more:
            break
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it — merge
        # dedupes on the primary key. New rows arriving mid-sync only push older rows to later
        # pages (newest-first), so resuming at a saved page can re-read rows but never skip them.
        resumable_source_manager.save_state(DopplerResumeConfig(next_page=page + 1))
        page += 1


def _is_after_watermark(item: dict[str, Any], config: DopplerEndpointConfig, watermark: datetime) -> bool:
    incremental_field = config.incremental_fields[0]["field"]
    created_at = _parse_doppler_datetime(item.get(incremental_field))
    if created_at is None:
        return True
    return created_at > watermark


def doppler_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DopplerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = DOPPLER_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # Activity logs arrive newest-first; desc mode makes the pipeline persist the incremental
        # watermark at successful job end rather than per batch.
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_token: str) -> tuple[bool, int | None]:
    """Probe Doppler's `/v3/me` token-info endpoint, which accepts every Doppler token type.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error.
    """
    try:
        response = make_tracked_session().get(f"{DOPPLER_BASE_URL}/me", headers=_headers(api_token), timeout=10)
    except Exception:
        return False, None
    return response.status_code == 200, response.status_code
