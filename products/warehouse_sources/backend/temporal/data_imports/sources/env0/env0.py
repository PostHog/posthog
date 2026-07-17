import base64
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.env0.settings import (
    ENV0_ENDPOINTS,
    Env0EndpointConfig,
)

ENV0_BASE_URL = "https://api.env0.com"
# Environments/deployments list endpoints cap pages at 100 items.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# env0 rate-limits at 1,000 requests / 60s per IP+method+URI; exponential backoff on 429 suffices.
MAX_RETRIES = 5


class Env0RetryableError(Exception):
    pass


@dataclasses.dataclass
class Env0ResumeConfig:
    # Stable parent-id bookmark (organization or environment id, per the endpoint's scope; None
    # for root endpoints) — not a positional index, so parents added/removed between a crash and
    # the retry can't resume us into the wrong parent.
    parent_id: str | None = None
    # Position within the bookmarked parent's page chain: a numeric offset for limit/offset
    # endpoints, or the teams endpoint's nextPageKey. None means "start at the first page".
    offset: str | None = None


def _get_headers(api_key_id: str, api_key_secret: str) -> dict[str, str]:
    basic_token = base64.b64encode(f"{api_key_id}:{api_key_secret}".encode("ascii")).decode("ascii")
    return {
        "Authorization": f"Basic {basic_token}",
        "Accept": "application/json",
    }


def _format_date_window_value(value: Any) -> Optional[str]:
    """Format an incremental cursor as YYYY-MM-DDTHH:mm:ss.sssZ, the format env0's
    fromDate/toDate params require."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _build_date_window_params(
    config: Env0EndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, str]:
    """Build the fromDate/toDate server-side window for incremental syncs.

    env0 requires both params together, so the window runs from the watermark (minus the
    endpoint's lookback, letting rows that mutated after first fetch be re-pulled and merged)
    up to now.
    """
    if not config.supports_date_window or not should_use_incremental_field:
        return {}

    if db_incremental_field_last_value is None:
        return {}

    from_value = db_incremental_field_last_value
    if config.incremental_lookback is not None and isinstance(from_value, datetime | date):
        if isinstance(from_value, datetime):
            from_value = from_value - config.incremental_lookback
        else:
            from_value = datetime.combine(from_value, datetime.min.time(), tzinfo=UTC) - config.incremental_lookback

    from_date = _format_date_window_value(from_value)
    if from_date is None:
        return {}

    return {"fromDate": from_date, "toDate": _format_date_window_value(datetime.now(UTC)) or ""}


def _build_url(config: Env0EndpointConfig, parent_id: str | None, params: dict[str, Any]) -> str:
    path = config.path.format(parent_id=parent_id) if parent_id is not None else config.path
    clean_params = {key: value for key, value in params.items() if value is not None}
    if not clean_params:
        return f"{ENV0_BASE_URL}{path}"
    return f"{ENV0_BASE_URL}{path}?{urlencode(clean_params)}"


def _build_params(
    config: Env0EndpointConfig,
    parent_id: str | None,
    offset: str | None,
    date_window_params: dict[str, str],
) -> dict[str, Any]:
    params: dict[str, Any] = dict(config.params)
    if config.org_id_param and parent_id is not None:
        params[config.org_id_param] = parent_id
    if config.paginated:
        params["limit"] = PAGE_SIZE
        if offset is not None:
            params["offset"] = offset
    params.update(date_window_params)
    return params


def validate_credentials(api_key_id: str, api_key_secret: str) -> bool:
    """Confirm the API key pair is valid. /organizations is a cheap authenticated probe that
    works for both organization and personal API keys."""
    try:
        response = make_tracked_session().get(
            f"{ENV0_BASE_URL}/organizations",
            headers=_get_headers(api_key_id, api_key_secret),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type((Env0RetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> Any:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise Env0RetryableError(f"env0 API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # 404s during the per-environment fan-out (environment deleted mid-sync, or cost
        # monitoring not configured) are handled by the caller.
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"env0 API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _extract_items(
    data: Any, config: Env0EndpointConfig, offset: str | None
) -> tuple[list[dict[str, Any]], str | None]:
    """Pull the item list out of a response and compute the next-page offset (None = done).

    Most env0 list endpoints return a bare JSON array; paginated arrays advance a numeric
    offset until a short page. Teams returns {"teams": [...], "nextPageKey": ...} where the
    next request's offset is the returned nextPageKey.
    """
    if isinstance(data, dict):
        items = data.get(config.data_key or "items", []) or []
        next_page_key = data.get("nextPageKey")
        return items, str(next_page_key) if next_page_key else None

    items = data or []
    if config.paginated and len(items) == PAGE_SIZE:
        return items, str(int(offset or 0) + len(items))
    return items, None


def _normalize_row(item: dict[str, Any], config: Env0EndpointConfig, parent_id: str | None) -> dict[str, Any]:
    row = {key: value for key, value in item.items() if key not in config.strip_fields}
    if config.inject_parent_id_field and parent_id is not None:
        row[config.inject_parent_id_field] = parent_id
    return row


def _list_organization_ids(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger
) -> list[str]:
    data = _fetch_page(session, f"{ENV0_BASE_URL}/organizations", headers, logger)
    return [org["id"] for org in data or []]


def _list_environment_ids(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger
) -> list[str]:
    """Enumerate every environment id across all accessible organizations, paging through the
    environments list. The nested latest deployment is excluded to keep enumeration light."""
    environment_ids: list[str] = []
    for organization_id in _list_organization_ids(session, headers, logger):
        offset = 0
        while True:
            query = urlencode(
                {
                    "organizationId": organization_id,
                    "limit": PAGE_SIZE,
                    "offset": offset,
                    "excludeFields": "latestDeploymentLog",
                }
            )
            data = _fetch_page(session, f"{ENV0_BASE_URL}/environments?{query}", headers, logger)
            items = data or []
            environment_ids.extend(item["id"] for item in items)
            if len(items) < PAGE_SIZE:
                break
            offset += len(items)
    return environment_ids


def _list_parents(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger, config: Env0EndpointConfig
) -> list[str | None]:
    if config.scope == "organization":
        return list(_list_organization_ids(session, headers, logger))
    if config.scope == "environment":
        return list(_list_environment_ids(session, headers, logger))
    return [None]


def get_rows(
    api_key_id: str,
    api_key_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[Env0ResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = ENV0_ENDPOINTS[endpoint]
    headers = _get_headers(api_key_id, api_key_secret)
    # One session reused across every page and fan-out parent so urllib3 keeps the connection
    # alive instead of re-handshaking per request.
    session = make_tracked_session()

    date_window_params = _build_date_window_params(
        config, should_use_incremental_field, db_incremental_field_last_value
    )

    parents = _list_parents(session, headers, logger, config)

    # Resolve the saved parent bookmark to the slice of parents still to process. If the
    # bookmarked parent no longer exists (deleted between runs), start over from the first —
    # merge dedupes the re-pulled rows on the primary key.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = parents
    resume_offset: str | None = None
    if resume is not None and resume.parent_id in parents:
        remaining = parents[parents.index(resume.parent_id) :]
        resume_offset = resume.offset
        logger.debug(f"env0: resuming {endpoint} from parent_id={resume.parent_id}, offset={resume_offset}")

    for index, parent_id in enumerate(remaining):
        offset = resume_offset
        resume_offset = None  # only the resumed-into parent uses the saved offset

        try:
            while True:
                params = _build_params(config, parent_id, offset, date_window_params)
                url = _build_url(config, parent_id, params)
                data = _fetch_page(session, url, headers, logger)
                items, next_offset = _extract_items(data, config, offset)

                rows = [_normalize_row(item, config, parent_id) for item in items]
                if rows:
                    yield rows

                if next_offset is None:
                    break
                # Save AFTER yielding so a crash re-yields the last page rather than skipping
                # it — merge dedupes on the primary key.
                resumable_source_manager.save_state(Env0ResumeConfig(parent_id=parent_id, offset=next_offset))
                offset = next_offset
        except requests.HTTPError as exc:
            # During the per-environment fan-out, a 404 means the environment was deleted
            # mid-sync or (for costs) cost monitoring isn't configured for it. Skip it rather
            # than failing the whole sync; any other HTTP error is re-raised.
            if config.scope == "environment" and exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"env0: {endpoint} returned 404 for environment {parent_id}, skipping")
            else:
                raise

        # Advance the bookmark to the next parent so a crash between parents resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(Env0ResumeConfig(parent_id=remaining[index + 1], offset=None))


def env0_source(
    api_key_id: str,
    api_key_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[Env0ResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ENV0_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key_id=api_key_id,
            api_key_secret=api_key_secret,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # env0 doesn't document list ordering and the deployments endpoint fans out per
        # environment, so the incremental watermark must only persist at successful job end —
        # "desc" gives exactly that. Full-refresh endpoints have no watermark to protect.
        sort_mode="desc" if config.incremental_fields else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
