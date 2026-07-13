import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.healthchecks.settings import (
    HEALTHCHECKS_ENDPOINTS,
    HealthchecksEndpointConfig,
)

DEFAULT_BASE_URL = "https://healthchecks.io"
REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRY_ATTEMPTS = 5


class HealthchecksRetryableError(Exception):
    pass


@dataclasses.dataclass
class HealthchecksResumeConfig:
    # The check we're about to fan out over. A stable check-key bookmark (not a positional
    # index) so checks added/removed between a crash and the retry can't resume into the wrong
    # check. None for the non-fan-out endpoints (checks, channels), which are single requests.
    check_key: str | None = None


def normalize_base_url(base_url: str | None) -> str:
    """Normalize the (optional) instance URL and reject anything that isn't plain http(s).

    Defaults to healthchecks.io; self-hosted deployments pass their own base URL.
    """
    host = (base_url or "").strip() or DEFAULT_BASE_URL
    if "://" not in host:
        host = f"https://{host}"
    host = host.rstrip("/")
    parsed = urlparse(host)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"Invalid Healthchecks base URL: {base_url}")
    return host


def hostname_of(base_url: str | None) -> str:
    return urlparse(normalize_base_url(base_url)).hostname or ""


def _api_base(base_url: str | None) -> str:
    return f"{normalize_base_url(base_url)}/api/v3"


def _headers(api_key: str) -> dict[str, str]:
    return {"X-Api-Key": api_key, "Accept": "application/json"}


def _to_unix_seconds(value: Any) -> int | None:
    """Convert a datetime/date/ISO-string/number incremental cursor to a UNIX timestamp for the
    flips `start` filter. Returns None when the value can't be interpreted."""
    if value is None:
        return None
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(aware.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        aware = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        return int(aware.timestamp())
    return None


def _check_key(check: dict[str, Any]) -> str | None:
    """The identifier to address a check's sub-endpoints. Full API keys expose `uuid`;
    read-only keys omit it and expose `unique_key` instead."""
    return check.get("uuid") or check.get("unique_key")


@retry(
    retry=retry_if_exception_type(
        (
            HealthchecksRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> requests.Response:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    # Healthchecks rate-limits at ~100 requests/minute (429 beyond that); 5xx are transient.
    if response.status_code == 429 or response.status_code >= 500:
        raise HealthchecksRetryableError(
            f"Healthchecks API error (retryable): status={response.status_code}, url={url}"
        )

    if not response.ok:
        logger.error(f"Healthchecks API error: status={response.status_code}, body={response.text[:500]}, url={url}")
        response.raise_for_status()

    return response


def validate_credentials(base_url: str | None, api_key: str) -> tuple[bool, str | None]:
    """Probe the checks list endpoint. Works with both full and read-only keys."""
    url = f"{_api_base(base_url)}/checks/"
    try:
        response = make_tracked_session(allow_redirects=False).get(
            url, headers=_headers(api_key), timeout=REQUEST_TIMEOUT_SECONDS
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Healthchecks API key"
    return False, f"Healthchecks returned status {response.status_code}"


def _iter_checks(
    session: requests.Session, base_url: str | None, api_key: str, logger: FilteringBoundLogger
) -> list[dict[str, Any]]:
    """Fetch every check once, up front, so the fan-out can enumerate parents."""
    response = _fetch(session, f"{_api_base(base_url)}/checks/", _headers(api_key), logger)
    body = response.json()
    checks = body.get("checks", []) if isinstance(body, dict) else []
    return [c for c in checks if isinstance(c, dict)]


def _normalize_check(check: dict[str, Any]) -> dict[str, Any]:
    """Stamp a stable `id` onto each check (uuid for full keys, unique_key for read-only keys)
    so the primary key survives regardless of which API-key type is connected."""
    return {"id": _check_key(check), **check}


def _fan_out_url(
    config: HealthchecksEndpointConfig, base_url: str | None, check_key: str, params: dict[str, Any]
) -> str:
    path = config.path.format(check_key=check_key)
    url = f"{_api_base(base_url)}{path}"
    return f"{url}?{urlencode(params)}" if params else url


def _get_fan_out_rows(
    session: requests.Session,
    base_url: str | None,
    api_key: str,
    config: HealthchecksEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HealthchecksResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    headers = _headers(api_key)
    checks = _iter_checks(session, base_url, api_key, logger)
    # A stable order so the resume bookmark resolves deterministically across runs.
    check_keys = [key for key in (_check_key(c) for c in checks) if key]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = check_keys
    if resume is not None and resume.check_key is not None and resume.check_key in check_keys:
        remaining = check_keys[check_keys.index(resume.check_key) :]
        logger.debug(f"Healthchecks: resuming {config.name} fan-out from check_key={resume.check_key}")

    params: dict[str, Any] = {}
    if config.supports_incremental and should_use_incremental_field:
        start = _to_unix_seconds(db_incremental_field_last_value)
        if start is not None:
            # `start` returns flips newer than this UNIX timestamp (server-side filter).
            params["start"] = start

    for index, check_key in enumerate(remaining):
        url = _fan_out_url(config, base_url, check_key, params)
        try:
            response = _fetch(session, url, headers, logger)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            # The pings sub-endpoint only accepts the full uuid, so read-only keys (unique_key
            # only) 404 here — skip that check rather than failing the whole sync. A check
            # deleted mid-sync also 404s; same benign skip.
            if status == 404:
                logger.warning(f"Healthchecks: {config.name} not available for check {check_key} (404), skipping")
                continue
            raise

        body = response.json()
        if config.data_key is None:
            items = body if isinstance(body, list) else []
        else:
            items = body.get(config.data_key, []) if isinstance(body, dict) else []

        rows = [{"check_id": check_key, **item} for item in items if isinstance(item, dict)]
        if rows:
            yield rows

        # Bookmark the NEXT check only after the current one is fully yielded, so a resume starts
        # at the next unprocessed check rather than re-emitting a check whose rows already landed
        # (which would duplicate rows for the full-refresh pings table). Flips finalize their
        # incremental watermark at job end (desc sort_mode), so a bounded re-pull on crash is
        # merge-deduped regardless.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(HealthchecksResumeConfig(check_key=remaining[index + 1]))


def get_rows(
    base_url: str | None,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HealthchecksResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = HEALTHCHECKS_ENDPOINTS[endpoint]
    # `base_url` is user-supplied (self-hosted), so pin redirects off: validation and the
    # outbound request must stay on the same target (SSRF defense-in-depth).
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)

    if config.fan_out_over_checks:
        yield from _get_fan_out_rows(
            session,
            base_url,
            api_key,
            config,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
        return

    # Top-level endpoints (checks, channels): a single unpaginated request.
    response = _fetch(session, f"{_api_base(base_url)}{config.path}", _headers(api_key), logger)
    body = response.json()
    items = body.get(config.data_key, []) if (config.data_key and isinstance(body, dict)) else []
    rows = [item for item in items if isinstance(item, dict)]
    if endpoint == "checks":
        rows = [_normalize_check(row) for row in rows]
    if rows:
        yield rows


def healthchecks_source(
    base_url: str | None,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HealthchecksResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = HEALTHCHECKS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            base_url=base_url,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=list(config.primary_keys),
        # Flips fan out over many checks, so rows do not arrive in a single global timestamp
        # order. desc mode defers persisting the incremental watermark until the job completes
        # (see finalize_desc_sort_incremental_value): a partial run can't advance the watermark
        # past checks it never reached. Other endpoints stream in one request, so asc is correct.
        sort_mode="desc" if config.fan_out_over_checks and config.supports_incremental else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
