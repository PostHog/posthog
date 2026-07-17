import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.jenkins.settings import JENKINS_ENDPOINTS

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5
# Builds are windowed by index range (`tree=builds[...]{start,end}`). Jenkins has no cursor, so we
# advance the range ourselves; 100 keeps each request small while limiting round trips.
BUILDS_PAGE_SIZE = 100
# Guard against pathological Folder / Multibranch nesting when discovering jobs recursively.
MAX_JOB_DEPTH = 10
# MAX_JOB_DEPTH caps nesting; this caps breadth. The customer configures the host, so a hostile or
# misconfigured server could return unbounded folder fan-out at every level and hold a worker issuing
# an effectively unlimited number of authenticated requests. Stop discovery once this many jobs have
# been emitted (far above any real Jenkins instance).
MAX_TOTAL_JOBS = 100_000
# Cap the decoded response body we buffer per request. The customer configures the host, so a hostile
# or misconfigured server could otherwise return an arbitrarily large (or highly compressed) body and
# exhaust the import worker. The `tree=` selectors keep real responses tiny; this only trips on abuse.
MAX_RESPONSE_BYTES = 50 * 1024 * 1024
RESPONSE_CHUNK_BYTES = 1024 * 1024
# Hard wall-clock deadline for reading a single response body. REQUEST_TIMEOUT_SECONDS is a per-read
# socket timeout that resets whenever a byte arrives, so a server dripping data slowly could otherwise
# hold the read loop open indefinitely; this bounds the total download regardless of drip rate.
MAX_DOWNLOAD_SECONDS = 300
# Bound windowed build pagination per job. A server returning a full page for every window would
# otherwise loop forever; 1000 pages (~100k builds at BUILDS_PAGE_SIZE) is far above any real job.
MAX_BUILD_PAGES_PER_JOB = 1000

# Field selectors passed to Jenkins' `tree` param. Keeping them explicit (rather than `depth=`) means
# we only pull the columns we store and never accidentally fetch large nested build/console payloads.
JOB_TREE_FIELDS = "name,fullName,url,color,_class,buildable"
BUILD_TREE_FIELDS = (
    "number,url,result,duration,estimatedDuration,timestamp,id,fullDisplayName,displayName,building,queueId"
)


class JenkinsRetryableError(Exception):
    pass


@dataclasses.dataclass
class JenkinsResumeConfig:
    # The next job (by stable URL) to fetch builds for. A URL bookmark rather than a positional index
    # so jobs added/removed between a crash and the retry can't resume us into the wrong job. None for
    # the jobs catalog, which is a single full-refresh pass with no cursor.
    next_job_url: str | None = None


def normalize_base_url(host: str | None) -> str:
    """Normalize the self-hosted Jenkins URL and reject anything that isn't plain http(s).

    Jenkins has no vendor-hosted API, so the customer always supplies their instance URL. Rejects
    URLs where the host `urlparse` reports could diverge from the host the HTTP client actually dials
    (backslash tricks, userinfo before `@`, query/fragment), which would let a caller slip past the
    downstream SSRF allowlist that validates the parsed hostname.
    """
    raw = (host or "").strip()
    if not raw:
        raise ValueError("Jenkins URL is required")
    if "://" not in raw:
        raw = f"https://{raw}"
    if "\\" in raw or "%5c" in raw.lower():
        raise ValueError(f"Invalid Jenkins URL: {host}")
    raw = raw.rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"Invalid Jenkins URL: {host}")
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise ValueError(f"Invalid Jenkins URL: {host}")
    if parsed.query or parsed.fragment or parsed.params:
        raise ValueError(f"Invalid Jenkins URL: {host}")
    return raw


def hostname_of(host: str | None) -> str:
    return urlparse(normalize_base_url(host)).hostname or ""


def scheme_of(host: str | None) -> str:
    return urlparse(normalize_base_url(host)).scheme


def _api_json_url(object_url: str, tree: str) -> str:
    """Build an `/api/json` URL for any Jenkins object, selecting `tree` fields.

    `object_url` is an absolute Jenkins URL (the instance root or a job's own `url`, which the API
    always returns with a trailing slash). Brackets/braces in `tree` are sent literally — Jenkins
    requires them unencoded, and every value here is constructed internally, never user input.
    """
    base = object_url if object_url.endswith("/") else f"{object_url}/"
    return f"{base}api/json?tree={tree}"


def _headers() -> dict[str, str]:
    return {"Accept": "application/json"}


def _is_job_container(job: dict[str, Any]) -> bool:
    """Whether a job actually holds nested jobs (Folder, Organization Folder, Multibranch Pipeline).

    Jenkins ships several nesting plugins with different `_class` values, so match on the stable
    suffixes rather than exact class names.
    """
    cls = job.get("_class") or ""
    return cls.endswith("Folder") or "MultiBranch" in cls or "OrganizationFolder" in cls


@retry(
    retry=retry_if_exception_type(
        (
            JenkinsRetryableError,
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
    session: requests.Session,
    url: str,
    auth: tuple[str, str],
    logger: FilteringBoundLogger,
) -> requests.Response:
    # Stream so the status/headers arrive before the body, letting us cap the decoded size (see
    # _read_body_capped) rather than letting `requests` buffer an unbounded response up front.
    response = session.get(url, auth=auth, headers=_headers(), timeout=REQUEST_TIMEOUT_SECONDS, stream=True)

    # No documented rate limits (bounded by the customer's own server), but honor 429 if a reverse
    # proxy imposes one, and retry transient 5xx.
    if response.status_code == 429 or response.status_code >= 500:
        response.close()
        raise JenkinsRetryableError(f"Jenkins API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        response.close()
        logger.error(f"Jenkins API error: status={response.status_code}, url={url}")
        response.raise_for_status()

    _read_body_capped(response, url)
    return response


def _read_body_capped(response: requests.Response, url: str) -> None:
    """Buffer the streamed body up to MAX_RESPONSE_BYTES, then cache it so `.json()` still works.

    A response over the cap raises (non-retryable — it won't shrink on retry) instead of being read
    into memory in full.
    """
    deadline = time.monotonic() + MAX_DOWNLOAD_SECONDS
    buffer = bytearray()
    for chunk in response.iter_content(chunk_size=RESPONSE_CHUNK_BYTES):
        if not chunk:
            continue
        buffer += chunk
        if len(buffer) > MAX_RESPONSE_BYTES:
            response.close()
            raise ValueError(f"Jenkins response exceeded the {MAX_RESPONSE_BYTES}-byte limit: url={url}")
        if time.monotonic() > deadline:
            response.close()
            raise ValueError(f"Jenkins response exceeded the {MAX_DOWNLOAD_SECONDS}s download deadline: url={url}")
    # Cache the decoded body so downstream `.json()` reads from memory rather than re-reading the
    # (now consumed) stream.
    response._content = bytes(buffer)


def validate_credentials(
    host: str | None, username: str, api_token: str, schema_name: str | None = None
) -> tuple[bool, str | None]:
    """Probe the instance root `/api/json` to confirm the username + API token are genuine.

    A read-only GET needs no CSRF crumb. Both streams need the same Overall/Read permission, so the
    root probe covers per-schema checks too.
    """
    try:
        url = _api_json_url(normalize_base_url(host), "nodeName")
    except ValueError as e:
        return False, str(e)

    session = make_tracked_session(redact_values=(api_token,), allow_redirects=False)
    try:
        # Stream and only read the status line: the probe never needs the body, so a hostile host
        # can't make us buffer a large response just to validate credentials.
        response = session.get(
            url, auth=(username, api_token), headers=_headers(), timeout=REQUEST_TIMEOUT_SECONDS, stream=True
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    status_code = response.status_code
    response.close()

    if status_code == 200:
        return True, None
    if status_code == 401:
        return False, "Invalid Jenkins username or API token"
    if status_code == 403:
        return False, "The Jenkins user lacks Overall/Read permission"
    return False, f"Jenkins returned status {status_code}"


def _to_epoch_ms(value: Any) -> int | None:
    """Convert a datetime/date/ISO-string incremental cursor to epoch milliseconds.

    Jenkins build timestamps are epoch ms, so the watermark is compared in the same unit. Returns
    None when the value can't be interpreted (treated as "no watermark", i.e. full history)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(aware.timestamp() * 1000)
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        aware = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        return int(aware.timestamp() * 1000)
    return None


def _pin_job_url(base_url: str, url: Any) -> str | None:
    """Re-anchor a response-supplied job URL onto the configured origin, trusting only its path.

    Discovered job URLs are fetched later with the stored Basic credentials, so they must never
    steer a request off the validated instance: a compromised response could otherwise hand back an
    attacker URL (receiving the token in cleartext) or an internal address the configured-host SSRF
    check never examined. Rebuilding from the configured scheme + netloc plus the response path also
    drops any userinfo/query/fragment, and keeps discovery working when Jenkins' self-configured
    root URL differs from the URL the user connected with (a common reverse-proxy setup).
    """
    if not isinstance(url, str) or "\\" in url or "%5c" in url.lower():
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if not parsed.path.startswith("/"):
        return None
    base = urlparse(base_url)
    return f"{base.scheme}://{base.netloc}{parsed.path}"


def _discover_jobs(
    session: requests.Session,
    base_url: str,
    auth: tuple[str, str],
    logger: FilteringBoundLogger,
) -> Iterator[dict[str, Any]]:
    """Yield every job in the instance, recursing into Folders / Multibranch Pipelines.

    Each yielded row carries the raw Jenkins job fields plus a `depth`. Container jobs (folders) are
    yielded too — they're part of the catalog — but recursion also descends into them.
    """
    # (object_url, depth) frontier. Start at the instance root.
    frontier: list[tuple[str, int]] = [(base_url, 0)]
    seen_urls: set[str] = set()
    discovered = 0

    while frontier:
        object_url, depth = frontier.pop()
        response = _fetch(session, _api_json_url(object_url, f"jobs[{JOB_TREE_FIELDS}]"), auth, logger)
        body = response.json()
        jobs = body.get("jobs", []) if isinstance(body, dict) else []

        for job in jobs:
            if not isinstance(job, dict):
                continue
            # The pinned URL is the globally unique, stable identifier; skip anything without one
            # and guard against a plugin that links a folder back into its own subtree.
            job_url = _pin_job_url(base_url, job.get("url"))
            if not job_url or job_url in seen_urls:
                continue
            seen_urls.add(job_url)
            yield {**job, "id": job_url, "url": job_url}

            discovered += 1
            if discovered >= MAX_TOTAL_JOBS:
                logger.warning(f"Jenkins: reached the {MAX_TOTAL_JOBS}-job discovery limit; stopping traversal")
                return

            if _is_job_container(job) and depth + 1 < MAX_JOB_DEPTH:
                frontier.append((job_url, depth + 1))
            elif _is_job_container(job):
                logger.warning(f"Jenkins: max job nesting depth reached, not descending into {job_url}")


def _iter_buildable_job_urls(
    session: requests.Session,
    base_url: str,
    auth: tuple[str, str],
    logger: FilteringBoundLogger,
) -> list[str]:
    """The stable-ordered list of job URLs to fetch builds for (leaf, buildable jobs only)."""
    urls = [
        job["url"] for job in _discover_jobs(session, base_url, auth, logger) if job.get("buildable") and job.get("url")
    ]
    # Deterministic order so the resume bookmark resolves the same way across runs.
    return sorted(urls)


def _normalize_build(build: dict[str, Any], job_url: str) -> dict[str, Any]:
    """Stamp the parent job URL and a stable `created_at` datetime onto a build row.

    `created_at` is derived from the epoch-ms `timestamp` so both the partition key and the
    incremental cursor are proper datetimes.
    """
    timestamp_ms = build.get("timestamp")
    created_at = None
    if isinstance(timestamp_ms, (int, float)):
        created_at = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).isoformat()
    return {"job_url": job_url, "created_at": created_at, **build}


def _iter_job_builds(
    session: requests.Session,
    job_url: str,
    auth: tuple[str, str],
    logger: FilteringBoundLogger,
    watermark_ms: int | None,
) -> Iterator[dict[str, Any]]:
    """Yield a job's builds newest-first, windowing by index range and stopping at the watermark.

    Jenkins returns builds strictly newest-first and has no server-side time filter, so on an
    incremental sync we walk index ranges from the newest build and stop as soon as we reach a build
    at or before `watermark_ms` — everything older is already synced. The boundary build (equal
    timestamp) is re-emitted and deduped by merge on the primary key.
    """
    start = 0
    for _page in range(MAX_BUILD_PAGES_PER_JOB):
        tree = f"builds[{BUILD_TREE_FIELDS}]{{{start},{start + BUILDS_PAGE_SIZE}}}"
        response = _fetch(session, _api_json_url(job_url, tree), auth, logger)
        body = response.json()
        builds = body.get("builds", []) if isinstance(body, dict) else []
        if not builds:
            return

        for build in builds:
            if not isinstance(build, dict):
                continue
            build_ts = build.get("timestamp")
            if watermark_ms is not None and isinstance(build_ts, (int, float)) and build_ts < watermark_ms:
                # Reached already-synced builds; the rest of this (and every later) page is older.
                return
            yield _normalize_build(build, job_url)

        # A short page means we've reached the oldest build for this job.
        if len(builds) < BUILDS_PAGE_SIZE:
            return
        start += BUILDS_PAGE_SIZE

    # Ran the page cap without reaching a short page — a real job never has this many builds, so a
    # server returning full pages forever is hostile/misconfigured. Stop rather than loop unbounded.
    logger.warning(f"Jenkins: reached the {MAX_BUILD_PAGES_PER_JOB}-page build cap for {job_url}; stopping pagination")


def _get_jobs_rows(
    session: requests.Session,
    base_url: str,
    auth: tuple[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
) -> Iterator[Any]:
    for job in _discover_jobs(session, base_url, auth, logger):
        batcher.batch(job)
        if batcher.should_yield():
            yield batcher.get_table()


def _get_build_rows(
    session: requests.Session,
    base_url: str,
    auth: tuple[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[JenkinsResumeConfig],
    watermark_ms: int | None,
) -> Iterator[Any]:
    job_urls = _iter_buildable_job_urls(session, base_url, auth, logger)

    # Resolve the saved bookmark to the slice of jobs still to process. If the bookmarked job no
    # longer exists (deleted between runs), start over — merge dedupes the re-pulled rows.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = job_urls
    if resume is not None and resume.next_job_url is not None and resume.next_job_url in job_urls:
        remaining = job_urls[job_urls.index(resume.next_job_url) :]
        logger.debug(f"Jenkins: resuming builds fan-out from {resume.next_job_url}")

    for index, job_url in enumerate(remaining):
        for build in _iter_job_builds(session, job_url, auth, logger, watermark_ms):
            batcher.batch(build)
            if batcher.should_yield():
                yield batcher.get_table()

        # Bookmark the NEXT job only after the current one is fully yielded, so a crash resumes at an
        # unprocessed job rather than re-emitting one whose rows already landed. The incremental
        # watermark finalizes at job end (desc sort_mode), so a bounded re-pull on crash is safe.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(JenkinsResumeConfig(next_job_url=remaining[index + 1]))


def get_rows(
    host: str | None,
    username: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JenkinsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    config = JENKINS_ENDPOINTS[endpoint]
    base_url = normalize_base_url(host)
    auth = (username, api_token)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # User-supplied host: never follow redirects (SSRF boundary) and redact the token from telemetry.
    session = make_tracked_session(redact_values=(api_token,), allow_redirects=False)

    if config.fans_out_over_jobs:
        watermark_ms = _to_epoch_ms(db_incremental_field_last_value) if should_use_incremental_field else None
        yield from _get_build_rows(session, base_url, auth, logger, batcher, resumable_source_manager, watermark_ms)
    else:
        yield from _get_jobs_rows(session, base_url, auth, logger, batcher)

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def jenkins_source(
    host: str | None,
    username: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JenkinsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = JENKINS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            host=host,
            username=username,
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Builds arrive newest-first and finalize the incremental watermark at job end (see
        # _get_build_rows); the jobs catalog is a full-refresh pass.
        sort_mode=endpoint_config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
