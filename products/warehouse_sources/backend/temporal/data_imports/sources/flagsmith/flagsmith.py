import json
import threading
import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.flagsmith.settings import (
    FLAGSMITH_ENDPOINTS,
    FlagsmithEndpointConfig,
    ParentResource,
)

DEFAULT_BASE_URL = "https://api.flagsmith.com"

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5
MAX_RETRY_WAIT_SECONDS = 60

# Cap on the total pages walked in one sync invocation, shared across parent enumeration and
# every fan-out child listing. `next` links come from a user-supplied (self-hosted) host, so a
# hostile or misconfigured server can return a non-empty cyclic `next` forever — and in a fan-out
# multiply that across thousands of parents. A single shared budget makes the whole sync
# self-terminate instead of issuing credentialed requests until the activity is cancelled.
# Generous enough not to truncate real data.
MAX_PAGES_PER_SYNC = 10_000

# Cap on how many fan-out parents (organisation ids, project ids, or environment api_keys) a single
# sync enumerates and holds in memory before child processing begins. Even within the page budget a
# hostile host could return enough parents to balloon this list and exhaust a warehouse worker; the
# keys are short identifiers, so a count cap bounds the retained bytes too. Generous enough to cover
# any real org.
MAX_FANOUT_PARENTS = 50_000


class _PageBudget:
    """Mutable page allowance drawn down across a whole sync (all parents and child listings)."""

    def __init__(self, limit: int) -> None:
        self.remaining = limit

    def take(self) -> bool:
        """Consume one page; return False once the shared budget is exhausted."""
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True


# base_url can be a customer-controlled self-hosted host, so response bodies are streamed and
# read under a byte cap and a total-transfer deadline: an arbitrarily large (or endlessly
# dripped) 200 body must fail the sync instead of exhausting worker memory or holding a worker.
# The cap counts decoded bytes, so a gzip bomb can't slip past it.
MAX_RESPONSE_BYTES = 256 * 1024 * 1024
_READ_CHUNK_BYTES = 1024 * 1024
# The per-read socket timeout only bounds the gap between bytes, so a host that trickles one byte
# just before each read timeout could keep a worker busy until the activity's timeout. This
# absolute wall-clock deadline (enforced in `_read_bounded`) caps how long a single body read may
# take end to end, even while a read is blocked mid-chunk.
MAX_RESPONSE_SECONDS = 600
# Bytes pulled from an error body for a diagnostic message — error bodies are never needed in full.
_ERROR_SNIPPET_BYTES = 2048


class FlagsmithRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class FlagsmithResponseTooLargeError(Exception):
    pass


class FlagsmithResponseTimeoutError(Exception):
    pass


def _read_bounded(
    response: requests.Response, max_bytes: int = MAX_RESPONSE_BYTES, max_seconds: float = MAX_RESPONSE_SECONDS
) -> bytes:
    """Read a streamed response body under both a byte cap and a total-transfer deadline.

    The read runs on a worker thread bounded by ``join(timeout=max_seconds)``, so the deadline is
    enforced as absolute wall-clock time even while a read is blocked: ``iter_content`` fills a
    whole chunk before it yields, so a host that trickles bytes just under the per-read socket
    timeout could otherwise never let an in-loop deadline check run. On timeout we close the
    response to unblock the pending socket read and let the daemon thread unwind.
    """
    box: dict[str, Any] = {}

    def _reader() -> None:
        try:
            total = 0
            chunks: list[bytes] = []
            for chunk in response.iter_content(chunk_size=_READ_CHUNK_BYTES):
                total += len(chunk)
                if total > max_bytes:
                    box["error"] = FlagsmithResponseTooLargeError(
                        f"Flagsmith API response exceeded the size limit ({max_bytes} bytes)"
                    )
                    return
                chunks.append(chunk)
            box["data"] = b"".join(chunks)
        except Exception as exc:  # surfaced on the calling thread below
            box["error"] = exc

    thread = threading.Thread(target=_reader, name="flagsmith-read-bounded", daemon=True)
    thread.start()
    thread.join(timeout=max_seconds)
    if thread.is_alive():
        # Close the socket so the blocked read raises and the daemon thread can exit.
        response.close()
        raise FlagsmithResponseTimeoutError(
            f"Flagsmith API response exceeded the download time limit ({max_seconds:g}s)"
        )
    if "error" in box:
        raise box["error"]
    return box.get("data", b"")


def _error_snippet(response: requests.Response) -> str:
    try:
        chunk = next(response.iter_content(chunk_size=_ERROR_SNIPPET_BYTES), b"")
        return chunk[:_ERROR_SNIPPET_BYTES].decode("utf-8", errors="replace")
    except Exception:
        return ""


@dataclasses.dataclass
class FlagsmithResumeConfig:
    # Full URL of the next page to fetch ("" once a resource is exhausted).
    next_url: str = ""
    # For fan-out endpoints, the parent (organisation id, project id, or environment
    # api_key) currently being paginated ("" for top-level endpoints or before the first
    # parent starts).
    parent_key: str = ""


def normalize_base_url(base_url: str | None) -> str:
    """Normalize the (optional) instance URL and reject anything that isn't plain http(s).

    Defaults to Flagsmith SaaS; self-hosted deployments pass their own API URL.

    Rejects URLs where the host ``urlparse`` reports could diverge from the host the HTTP
    client actually dials, which would let a caller slip past the downstream SSRF allowlist
    (which validates the parsed hostname): backslashes (treated as path separators by some
    clients but not by ``urlparse``), userinfo (``user@host`` hides the real host after an
    ``@``), and query/fragment noise that has no place in a base URL.
    """
    host = (base_url or "").strip() or DEFAULT_BASE_URL
    if "://" not in host:
        host = f"https://{host}"
    # Catch raw and percent-encoded backslashes before urlparse silently keeps them.
    if "\\" in host or "%5c" in host.lower():
        raise ValueError(f"Invalid Flagsmith base URL: {base_url}")
    host = host.rstrip("/")
    parsed = urlparse(host)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"Invalid Flagsmith base URL: {base_url}")
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise ValueError(f"Invalid Flagsmith base URL: {base_url}")
    if parsed.query or parsed.fragment or parsed.params:
        raise ValueError(f"Invalid Flagsmith base URL: {base_url}")
    return host


def hostname_of(base_url: str | None) -> str:
    return urlparse(normalize_base_url(base_url)).hostname or ""


def scheme_of(base_url: str | None) -> str:
    return urlparse(normalize_base_url(base_url)).scheme


def _api_base(base: str) -> str:
    return f"{base}/api/v1"


def _headers(api_key: str) -> dict[str, str]:
    # Organisation API keys authenticate with an "Api-Key" prefix
    # (see https://docs.flagsmith.com/clients/rest#private-admin-api-endpoints).
    return {
        "Authorization": f"Api-Key {api_key}",
        "Accept": "application/json",
    }


def _initial_url(base: str, path: str, params: dict[str, Any]) -> str:
    url = f"{_api_base(base)}{path}"
    if params:
        sep = "&" if "?" in path else "?"
        url = f"{url}{sep}{urlencode(params)}"
    return url


def _pinned_next_url(base: str, next_link: Any) -> str | None:
    """Rebuild a DRF ``next`` link onto the configured base URL.

    The API returns absolute URLs derived from the request host, which a misconfigured
    self-hosted proxy (or a hostile server) could point elsewhere. Keeping only the
    path + query pins pagination to the host that credential validation approved.
    """
    if not next_link or not isinstance(next_link, str):
        return None
    parsed = urlparse(next_link)
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{base}{parsed.path}{query}"


def _extract_rows(base: str, data: Any) -> tuple[list[dict[str, Any]], str | None]:
    """Rows + next-page URL from a response body: either a DRF pagination envelope
    (``{count, next, previous, results}``) or a plain JSON array (projects, users)."""
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)], None
    if isinstance(data, dict):
        rows = [row for row in data.get("results") or [] if isinstance(row, dict)]
        return rows, _pinned_next_url(base, data.get("next"))
    return [], None


def _wait_strategy(retry_state: Any) -> float:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, FlagsmithRetryableError) and exc.retry_after is not None:
        return min(exc.retry_after, MAX_RETRY_WAIT_SECONDS)
    return min(2.0**retry_state.attempt_number, MAX_RETRY_WAIT_SECONDS)


@retry(
    retry=retry_if_exception_type((FlagsmithRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=_wait_strategy,
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> Any:
    # stream=True keeps the body off the wire until it's read through `_read_bounded` under a byte
    # cap and a transfer deadline — a customer-controlled host must not exhaust worker memory or
    # hold a worker with an endless body.
    with session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, stream=True) as response:
        if response.status_code == 429:
            retry_after_header = response.headers.get("Retry-After")
            try:
                retry_after = float(retry_after_header) if retry_after_header else None
            except ValueError:
                # A non-numeric value (e.g. an HTTP-date) falls back to exponential backoff.
                retry_after = None
            logger.warning(f"Flagsmith rate limited (429), retrying. retry_after={retry_after_header}, url={url}")
            raise FlagsmithRetryableError(f"Flagsmith rate limited: url={url}", retry_after=retry_after)

        if response.status_code >= 500:
            raise FlagsmithRetryableError(f"Flagsmith server error: status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(
                f"Flagsmith API error: status={response.status_code}, body={_error_snippet(response)}, url={url}"
            )
            response.raise_for_status()

        return json.loads(_read_bounded(response))


def validate_credentials(api_key: str, base_url: str | None, path: str = "/organisations/") -> int | None:
    """Probe an endpoint and return the HTTP status code (or None on transport failure)."""
    try:
        # base_url is user-supplied (self-hosted), so pin redirects off: validation and the
        # outbound request must stay on the same target (SSRF defense-in-depth). capture=False
        # keeps the probe's customer-content response body out of HTTP sample storage.
        # retry=Retry(total=0): the probe runs inline on an API worker, so it takes a single
        # attempt — a hostile base_url must not be able to hold the worker via adapter retries
        # that honour an unbounded server-controlled Retry-After.
        session = make_tracked_session(
            redact_values=(api_key,), allow_redirects=False, capture=False, retry=Retry(total=0)
        )
        # stream=True and a context manager so we read only the status line/headers and never
        # download the body: a hostile base_url could otherwise trickle an endless body and hold
        # this inline API worker open well past the read timeout (which only bounds byte gaps).
        with session.get(
            f"{_api_base(normalize_base_url(base_url))}{path}", headers=_headers(api_key), timeout=10, stream=True
        ) as response:
            return response.status_code
    except Exception:
        return None


def _iter_pages(
    session: requests.Session,
    base: str,
    start_url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    budget: _PageBudget,
) -> Iterator[list[dict[str, Any]]]:
    """Walk a listing (paginated or plain-array) without touching resume state — used to
    enumerate fan-out parents, which must be re-listed from scratch on every run."""
    url: str | None = start_url
    while url:
        if not budget.take():
            logger.warning(f"Flagsmith: sync page budget ({MAX_PAGES_PER_SYNC}) exhausted at {start_url}, truncating")
            return
        data = _fetch_page(session, url, headers, logger)
        rows, url = _extract_rows(base, data)
        if rows:
            yield rows


def _extend_capped(
    keys: list[str], listing: Iterator[list[dict[str, Any]]], field: str, logger: FilteringBoundLogger
) -> bool:
    """Append ``row[field]`` from each row of a parent listing into ``keys``, stopping once the
    retained list hits MAX_FANOUT_PARENTS so a hostile host can't balloon it and exhaust worker
    memory. Returns True if the cap was reached (the caller should stop enumerating)."""
    for rows in listing:
        for row in rows:
            keys.append(str(row[field]))
            if len(keys) >= MAX_FANOUT_PARENTS:
                logger.warning(f"Flagsmith: fan-out parent cap ({MAX_FANOUT_PARENTS}) reached, truncating enumeration")
                return True
    return False


def _fetch_parent_keys(
    session: requests.Session,
    base: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    parent: ParentResource,
    budget: _PageBudget,
) -> list[str]:
    if parent == "organisation":
        listing = _iter_pages(session, base, _initial_url(base, "/organisations/", {}), headers, logger, budget)
        org_ids: list[str] = []
        _extend_capped(org_ids, listing, "id", logger)
        return org_ids

    project_listing = _iter_pages(session, base, _initial_url(base, "/projects/", {}), headers, logger, budget)
    project_ids: list[str] = []
    _extend_capped(project_ids, project_listing, "id", logger)
    if parent == "project":
        return project_ids

    # Environments are addressed by their (non-secret, client-side) api_key and listed
    # per project; keep API order so the resume bookmark resolves deterministically.
    keys: list[str] = []
    for project_id in project_ids:
        env_listing = _iter_pages(
            session, base, _initial_url(base, f"/environments/?project={project_id}", {}), headers, logger, budget
        )
        if _extend_capped(keys, env_listing, "api_key", logger):
            break
    return keys


def _paginate_resource(
    session: requests.Session,
    base: str,
    start_url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FlagsmithResumeConfig],
    parent_key: str,
    parent_field: str | None,
    budget: _PageBudget,
) -> Iterator[list[dict[str, Any]]]:
    url: str | None = start_url
    while url:
        if not budget.take():
            logger.warning(f"Flagsmith: sync page budget ({MAX_PAGES_PER_SYNC}) exhausted at {start_url}, truncating")
            # Terminal resume state so a resume advances past this parent instead of re-entering
            # the same (possibly cyclic) chain and re-spending the budget on it.
            resumable_source_manager.save_state(FlagsmithResumeConfig(next_url="", parent_key=parent_key))
            return
        data = _fetch_page(session, url, headers, logger)
        rows, next_url = _extract_rows(base, data)

        if parent_field:
            for row in rows:
                row[parent_field] = parent_key

        if rows:
            yield rows

        # Save state AFTER yielding so a heartbeat-timeout crash re-fetches from the next
        # page rather than re-emitting the page we just yielded (merge dedupes regardless).
        resumable_source_manager.save_state(FlagsmithResumeConfig(next_url=next_url or "", parent_key=parent_key))
        url = next_url


def _get_fan_out_rows(
    session: requests.Session,
    base: str,
    config: FlagsmithEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FlagsmithResumeConfig],
    resume: FlagsmithResumeConfig | None,
    budget: _PageBudget,
) -> Iterator[list[dict[str, Any]]]:
    assert config.parent is not None
    parent_keys = _fetch_parent_keys(session, base, headers, logger, config.parent, budget)
    if not parent_keys:
        logger.warning(f"Flagsmith: no {config.parent}s found, nothing to sync for endpoint={config.name}")
        return

    start_idx = 0
    resume_url: str | None = None
    if resume is not None and resume.parent_key and resume.parent_key in parent_keys:
        idx = parent_keys.index(resume.parent_key)
        if resume.next_url:
            # Mid-parent: pick up at the saved page within that parent. Re-pin onto the current base
            # so a stale URL from a since-retargeted source can't send the current API key to the
            # previously configured host.
            start_idx = idx
            resume_url = _pinned_next_url(base, resume.next_url)
        else:
            # The saved parent finished (empty next_url marker); start at the next one.
            start_idx = idx + 1

    for i in range(start_idx, len(parent_keys)):
        parent_key = parent_keys[i]
        if i == start_idx and resume_url:
            start_url = resume_url
        else:
            start_url = _initial_url(base, config.path.format(parent=parent_key), config.params)
        yield from _paginate_resource(
            session, base, start_url, headers, logger, resumable_source_manager, parent_key, config.parent_field, budget
        )


def get_rows(
    api_key: str,
    base_url: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FlagsmithResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = FLAGSMITH_ENDPOINTS[endpoint]
    base = normalize_base_url(base_url)
    headers = _headers(api_key)
    # capture=False: Flagsmith bodies carry customer-authored content the name-based scrubbers
    # can't recognise — feature values, segment rules, audit records, and member PII (names/emails).
    # retry=Retry(total=0): _fetch_page owns the retry budget via tenacity with a bounded wait
    # (_wait_strategy caps at MAX_RETRY_WAIT_SECONDS); leaving the adapter's DEFAULT_RETRY on would
    # let a hostile base_url stall a sync worker with an unbounded, server-controlled Retry-After.
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False, capture=False, retry=Retry(total=0))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    # One budget for the whole invocation so a fan-out can't multiply the per-listing cap across
    # parents into unbounded credentialed requests.
    budget = _PageBudget(MAX_PAGES_PER_SYNC)

    if config.parent is not None:
        yield from _get_fan_out_rows(session, base, config, headers, logger, resumable_source_manager, resume, budget)
        return

    if resume is not None and resume.next_url:
        logger.debug(f"Flagsmith: resuming endpoint={endpoint} from saved page")
        # Re-pin onto the current base: a stale resume URL from a since-retargeted source must not
        # send the current API key to the previously configured host.
        start_url = _pinned_next_url(base, resume.next_url) or _initial_url(base, config.path, config.params)
    else:
        start_url = _initial_url(base, config.path, config.params)

    yield from _paginate_resource(
        session,
        base,
        start_url,
        headers,
        logger,
        resumable_source_manager,
        parent_key="",
        parent_field=None,
        budget=budget,
    )


def flagsmith_source(
    api_key: str,
    base_url: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FlagsmithResumeConfig],
) -> SourceResponse:
    config = FLAGSMITH_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            base_url=base_url,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=list(config.primary_keys),
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
