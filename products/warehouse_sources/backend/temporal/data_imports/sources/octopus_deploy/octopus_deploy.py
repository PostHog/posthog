import re
import json
import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.octopus_deploy.settings import (
    OCTOPUS_DEPLOY_ENDPOINTS,
    OctopusDeployEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
MAX_RETRY_AFTER_SECONDS = 60
SPACES_PAGE_SIZE = 100

# The host is customer-controlled, so a malicious or misconfigured server could stream an
# unbounded body and exhaust a shared worker (requests buffers the whole body into memory by
# default, and the read timeout only guards idle gaps, not a steady large transfer). Cap what we
# read into memory — far larger than any real listing page, anything past it is refused.
MAX_RESPONSE_BYTES = 256 * 1024 * 1024
RESPONSE_CHUNK_BYTES = 256 * 1024
# Wall-clock budget for downloading one page's body. requests' timeout only bounds each individual
# socket read, so a host that dribbles the body slowly could hold the connection (and a shared
# worker) open far longer than any read timeout while staying under MAX_RESPONSE_BYTES. This caps
# total transfer time — 256 MiB in 300s is a ~0.85 MiB/s floor, far below any real API response and
# far above a slow-drip stall.
MAX_DOWNLOAD_SECONDS = 300

HOST_NOT_ALLOWED_ERROR = "Octopus Deploy host is not allowed"
RESPONSE_TOO_LARGE_ERROR = "Octopus Deploy response body was too large"
RESPONSE_TOO_SLOW_ERROR = "Octopus Deploy response download was too slow"


class OctopusDeployRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class OctopusDeployHostNotAllowedError(Exception):
    pass


class OctopusDeployResponseTooLargeError(Exception):
    pass


class OctopusDeployResponseTooSlowError(Exception):
    pass


def _read_capped_body(response: requests.Response) -> bytes:
    """Stream the body into memory, aborting past MAX_RESPONSE_BYTES or MAX_DOWNLOAD_SECONDS.

    The host is customer-controlled, so a body must never be buffered unbounded (size cap) nor be
    allowed to hold the connection open indefinitely by dribbling under the per-read timeout (time
    cap). Both are non-retryable: re-fetching the same page yields the same oversized/slow body.
    """
    chunks: list[bytes] = []
    total = 0
    deadline = time.monotonic() + MAX_DOWNLOAD_SECONDS
    try:
        for chunk in response.iter_content(chunk_size=RESPONSE_CHUNK_BYTES):
            if time.monotonic() > deadline:
                raise OctopusDeployResponseTooSlowError(
                    f"{RESPONSE_TOO_SLOW_ERROR}: exceeded {MAX_DOWNLOAD_SECONDS}s download budget"
                )
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise OctopusDeployResponseTooLargeError(
                    f"{RESPONSE_TOO_LARGE_ERROR}: exceeded {MAX_RESPONSE_BYTES} bytes"
                )
            chunks.append(chunk)
    finally:
        response.close()
    return b"".join(chunks)


@dataclasses.dataclass
class OctopusDeployResumeConfig:
    # Offset (`skip`) of the next unfetched page within the current listing.
    skip: int = 0
    # The space currently being processed. A stable space-ID bookmark (not a positional index)
    # so spaces added/removed between a crash and the retry can't resume us into the wrong
    # space. None for instance-level endpoints (spaces).
    space_id: str | None = None


def normalize_host(host: str) -> str:
    """Turn whatever the user typed into a bare Octopus server host.

    Accepts values like ``my-org.octopus.app``, ``https://my-org.octopus.app/``, or
    ``https://octopus.example.com/app#/Spaces-1`` and returns the bare hostname.
    """
    host = host.strip()
    host = re.sub(r"^https?://", "", host, flags=re.IGNORECASE)
    host = host.split("/")[0]
    return host.strip().rstrip("/")


def _base_url(host: str) -> str:
    return f"https://{normalize_host(host)}"


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "X-Octopus-ApiKey": api_key,
        "Accept": "application/json",
    }


def _format_incremental_value(value: Any) -> str:
    if isinstance(value, datetime):
        utc_dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_dt.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _build_params(
    config: OctopusDeployEndpointConfig,
    skip: int,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {"skip": skip, "take": config.page_size}

    if config.incremental_param and should_use_incremental_field and db_incremental_field_last_value:
        params[config.incremental_param] = _format_incremental_value(db_incremental_field_last_value)

    return params


def _endpoint_url(host: str, config: OctopusDeployEndpointConfig, space_id: str | None) -> str:
    if config.space_scoped:
        return f"{_base_url(host)}/api/{space_id}{config.path}"
    return f"{_base_url(host)}{config.path}"


def _parse_retry_after(response: requests.Response) -> float | None:
    """Octopus sends ``Retry-After`` in whole seconds on 429. Ignore HTTP-date forms."""
    raw = response.headers.get("Retry-After")
    if raw and raw.strip().isdigit():
        return min(float(raw.strip()), MAX_RETRY_AFTER_SECONDS)
    return None


def _retry_wait(retry_state: RetryCallState) -> float:
    """Honor a server-provided Retry-After when present, else exponential backoff."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, OctopusDeployRetryableError) and exc.retry_after is not None:
        return exc.retry_after
    return wait_exponential_jitter(initial=1, max=30)(retry_state)


@retry(
    retry=retry_if_exception_type((OctopusDeployRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=_retry_wait,
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    # Don't follow redirects: the customer-controlled host could 3xx to an internal address,
    # bypassing the host validation done before the request (SSRF).
    # stream=True so the body isn't buffered until we cap it — see _read_capped_body.
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False, stream=True)

    if response.status_code == 429 or response.status_code >= 500:
        response.close()
        retry_after = _parse_retry_after(response) if response.status_code == 429 else None
        raise OctopusDeployRetryableError(
            f"Octopus Deploy API error (retryable): status={response.status_code}, url={url}",
            retry_after=retry_after,
        )

    # A 3xx isn't an error status (`response.ok` is True), so reject it explicitly rather than
    # silently parsing the redirect body as data.
    if response.is_redirect or response.is_permanent_redirect:
        response.close()
        raise OctopusDeployHostNotAllowedError(
            f"Octopus Deploy API returned an unexpected redirect (status={response.status_code}); refusing to follow it"
        )

    body = _read_capped_body(response)

    if not response.ok:
        logger.error(
            f"Octopus Deploy API error: status={response.status_code}, body={body.decode(errors='replace')}, url={url}"
        )
        response.raise_for_status()

    return json.loads(body or b"null")


def _get_space_ids(
    session: requests.Session, host: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> list[str]:
    """Enumerate every space the API key can see, sorted by id for a deterministic fan-out order."""
    space_ids: list[str] = []
    skip = 0
    while True:
        url = f"{_base_url(host)}/api/spaces?{urlencode({'skip': skip, 'take': SPACES_PAGE_SIZE})}"
        data = _fetch_page(session, url, headers, logger)
        items = data.get("Items") or []
        if not items:
            break
        space_ids.extend(item["Id"] for item in items)
        if "Page.Next" not in (data.get("Links") or {}):
            break
        skip += len(items)
    return sorted(space_ids)


def _paginate(
    session: requests.Session,
    url: str,
    config: OctopusDeployEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    space_id: str | None,
    initial_skip: int,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    resumable_source_manager: ResumableSourceManager[OctopusDeployResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Walk one listing with skip/take offset pagination, yielding a batch per page.

    Octopus returns newest-first, so rows created mid-sync push already-seen rows to higher
    offsets — worst case we re-fetch a row (merge dedupes on the primary key), never skip one.
    """
    skip = initial_skip
    while True:
        params = _build_params(config, skip, should_use_incremental_field, db_incremental_field_last_value)
        data = _fetch_page(session, f"{url}?{urlencode(params)}", headers, logger)

        items = data.get("Items") or []
        if not items:
            break

        if config.space_scoped and space_id is not None:
            for item in items:
                item.setdefault("SpaceId", space_id)

        has_next = "Page.Next" in (data.get("Links") or {})
        skip += len(items)

        yield items

        if not has_next:
            break

        # Save AFTER yielding so a crash re-yields the last page rather than skipping it — merge
        # dedupes on the primary key.
        resumable_source_manager.save_state(OctopusDeployResumeConfig(skip=skip, space_id=space_id))


def get_rows(
    host: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OctopusDeployResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = OCTOPUS_DEPLOY_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)

    # Re-check at run time (not just at source-create) in case the host was edited or now
    # resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _is_host_safe(normalize_host(host), team_id)
    if not host_ok:
        raise OctopusDeployHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

    # One session reused across every page (and space) so urllib3 keeps the connection alive
    # instead of re-handshaking per request. `redact_values` masks the API key from logged
    # URLs and captured HTTP samples (the X-Octopus-ApiKey header isn't in the sampler's
    # generic denylist).
    session = make_tracked_session(redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if not config.space_scoped:
        initial_skip = resume.skip if resume is not None else 0
        url = _endpoint_url(host, config, None)
        yield from _paginate(
            session,
            url,
            config,
            headers,
            logger,
            space_id=None,
            initial_skip=initial_skip,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            resumable_source_manager=resumable_source_manager,
        )
        return

    space_ids = _get_space_ids(session, host, headers, logger)

    # Resolve the saved space-ID bookmark to the slice of spaces still to process. If the
    # bookmarked space no longer exists (deleted between runs), start over from the first space —
    # merge dedupes the re-pulled rows on the primary key.
    remaining = space_ids
    resume_skip = 0
    if resume is not None and resume.space_id is not None and resume.space_id in space_ids:
        remaining = space_ids[space_ids.index(resume.space_id) :]
        resume_skip = resume.skip
        logger.debug(f"Octopus Deploy: resuming {endpoint} from space_id={resume.space_id}, skip={resume_skip}")

    for index, space_id in enumerate(remaining):
        url = _endpoint_url(host, config, space_id)
        yield from _paginate(
            session,
            url,
            config,
            headers,
            logger,
            space_id=space_id,
            initial_skip=resume_skip,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            resumable_source_manager=resumable_source_manager,
        )
        resume_skip = 0  # only the resumed-into space starts at the saved offset

        # Advance the bookmark to the next space so a crash between spaces resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(OctopusDeployResumeConfig(skip=0, space_id=remaining[index + 1]))


def validate_credentials(
    host: str, api_key: str, schema_name: Optional[str] = None, team_id: Optional[int] = None
) -> tuple[bool, str | None]:
    """Probe the spaces listing to confirm the API key is genuine.

    At source-create (``schema_name is None``) a 403 is accepted: the key is valid but may be
    scoped to specific spaces/permissions. A scoped probe (``schema_name`` set) treats 403 as a
    hard failure.
    """
    try:
        normalized = normalize_host(host)
    except Exception:
        return False, "Invalid Octopus Deploy host"

    if not normalized or not re.match(r"^[A-Za-z0-9.\-]+$", normalized):
        return False, "Invalid Octopus Deploy host"

    # The host is fully customer-controlled (cloud `*.octopus.app` or self-hosted), so block
    # hosts that resolve to private/internal addresses (SSRF). Only enforced on cloud.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(normalized, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    url = f"https://{normalized}/api/spaces?take=1"
    try:
        # Don't follow redirects: the validated host could 3xx to an internal address, defeating
        # the host check above (SSRF). stream=True so a customer-controlled host can't force us to
        # buffer an unbounded probe body — see _read_capped_body.
        response = make_tracked_session(redact_values=(api_key,)).get(
            url, headers=_get_headers(api_key), timeout=10, allow_redirects=False, stream=True
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    try:
        if response.is_redirect or response.is_permanent_redirect:
            return False, HOST_NOT_ALLOWED_ERROR

        if response.status_code == 200:
            return True, None

        if response.status_code == 401:
            return False, "Invalid Octopus Deploy API key"

        if response.status_code == 403:
            if schema_name is None:
                # Valid key, missing permission for this probe — let source creation through.
                return True, None
            return False, "Your Octopus Deploy API key lacks the required permissions for this endpoint"

        try:
            body = _read_capped_body(response)
        except (OctopusDeployResponseTooLargeError, OctopusDeployResponseTooSlowError) as e:
            return False, str(e)

        text = body.decode(errors="replace")
        try:
            parsed = json.loads(body or b"null")
        except ValueError:
            return False, text
        if isinstance(parsed, dict):
            return False, parsed.get("ErrorMessage", text)
        return False, text
    finally:
        response.close()


def octopus_deploy_source(
    host: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OctopusDeployResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = OCTOPUS_DEPLOY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            host=host,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            team_id=team_id,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        # Octopus document ids look instance-unique, but that isn't documented — and space-scoped
        # listings fan out over every space, so the space id goes in the key to be safe.
        primary_keys=["SpaceId", "Id"] if endpoint_config.space_scoped else ["Id"],
        # Octopus listings return newest-first with no ascending option (verified against a live
        # server), and space fan-out means a partial run's max says nothing about spaces it never
        # reached — so the incremental watermark must only persist at successful job end.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
