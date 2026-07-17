import re
import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.settings import (
    BABELFORCE_ENDPOINTS,
    BabelforceEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

DEFAULT_ENVIRONMENT = "services"
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5

# The environment is the babelforce subdomain the customer's account lives on (usually
# "services", or a custom subdomain for dedicated environments). It becomes part of the
# request host, so it must be a plain DNS label — anything else could retarget credentials.
_ENVIRONMENT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]*$")


class BabelforceRetryableError(Exception):
    pass


@dataclasses.dataclass
class BabelforceResumeConfig:
    next_page: int
    params: dict[str, Any]


def is_environment_valid(environment: str) -> bool:
    return bool(_ENVIRONMENT_RE.match(environment.strip()))


def _base_url(environment: str) -> str:
    environment = environment.strip()
    if not is_environment_valid(environment):
        raise ValueError(f"Invalid babelforce environment: {environment!r}")
    return f"https://{environment.lower()}.babelforce.com/api/v2"


def _get_headers(access_id: str, access_token: str) -> dict[str, str]:
    return {
        "X-Auth-Access-Id": access_id,
        "X-Auth-Access-Token": access_token,
        "Accept": "application/json",
    }


def _to_epoch(value: Any) -> Optional[int]:
    """Coerce an incremental cursor value to unix seconds for the `dateCreated.start` filter.

    babelforce returns ISO-8601 date-time strings (e.g. "2020-04-16T22:21:38.000Z"), so the
    persisted watermark is a datetime/string; ints are accepted defensively.
    """
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
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                return int(value)
            except ValueError:
                return None
        dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
        return int(dt.timestamp())
    return None


def _build_url(environment: str, path: str, params: dict[str, Any]) -> str:
    clean_params = {key: value for key, value in params.items() if value is not None}
    base = f"{_base_url(environment)}{path}"
    if not clean_params:
        return base
    return f"{base}?{urlencode(clean_params)}"


def _build_params(
    config: BabelforceEndpointConfig, from_timestamp: Optional[int], to_timestamp: Optional[int]
) -> dict[str, Any]:
    params: dict[str, Any] = {"max": PAGE_SIZE}
    if config.supports_date_created_filter:
        # Documented on the call reporting endpoint as unix-second filters. The upper bound is
        # frozen at sync start so page contents stay stable while new calls arrive mid-sync;
        # newer rows are picked up by the next run's window.
        if from_timestamp is not None:
            params["dateCreated.start"] = from_timestamp
        if to_timestamp is not None:
            params["dateCreated.end"] = to_timestamp
    return params


def validate_credentials(environment: str, access_id: str, access_token: str) -> bool:
    """Confirm the access ID/token pair is valid with a one-row agents listing."""
    try:
        response = make_tracked_session().get(
            _build_url(environment, "/agents", {"max": 1}),
            headers=_get_headers(access_id, access_token),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    environment: str,
    access_id: str,
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BabelforceResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = BABELFORCE_ENDPOINTS[endpoint]
    headers = _get_headers(access_id, access_token)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        params = resume_config.params
        page: Optional[int] = resume_config.next_page
        logger.debug(f"Babelforce: resuming {endpoint} from page {page}")
    else:
        from_timestamp = _to_epoch(db_incremental_field_last_value) if should_use_incremental_field else None
        to_timestamp = int(time.time()) if config.supports_date_created_filter else None
        params = _build_params(config, from_timestamp, to_timestamp)
        # Omit `page` on the first request: the API's first-page index isn't documented, so we
        # let the server pick it and advance from `pagination.current` in the response.
        page = None

    @retry(
        retry=retry_if_exception_type((BabelforceRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = make_tracked_session().get(page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        # Rate limits aren't documented publicly; back off on 429s and transient 5xx.
        if response.status_code == 429 or response.status_code >= 500:
            raise BabelforceRetryableError(
                f"Babelforce API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"Babelforce API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    previous_current: Optional[int] = None

    while True:
        request_params = dict(params)
        if page is not None:
            request_params["page"] = page
        url = _build_url(environment, config.path, request_params)

        data = fetch_page(url)

        pagination = data.get("pagination") or {}
        current = pagination.get("current")
        pages = pagination.get("pages")

        # If the API ignored our `page` param and served the same page again, stop before
        # re-yielding it rather than looping forever.
        if previous_current is not None and isinstance(current, int) and current <= previous_current:
            logger.debug(f"Babelforce: page did not advance for {endpoint} (current={current}); stopping")
            break

        items = data.get("items") or []
        if items:
            yield items

        if not items or not isinstance(current, int):
            break
        if isinstance(pages, int) and current >= pages:
            break

        previous_current = current
        page = current + 1
        resumable_source_manager.save_state(BabelforceResumeConfig(next_page=page, params=params))


def babelforce_source(
    environment: str,
    access_id: str,
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BabelforceResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = BABELFORCE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            environment=environment,
            access_id=access_id,
            access_token=access_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        # The reporting API doesn't document a sort order or expose a sort param, so we can't
        # assume ascending arrival. "desc" makes the pipeline finalize the incremental watermark
        # only after a fully successful sync, which is correct for any actual ordering; the
        # server-side dateCreated window bounds what each run re-reads.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
