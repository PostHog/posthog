import re
import json
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.npm_registry.settings import (
    EARLIEST_DOWNLOAD_DATE,
    MAX_DOWNLOADS_WINDOW_DAYS,
    MAX_PACKAGES,
    MAX_RESPONSE_BYTES,
    MAX_ROWS_PER_BATCH,
    NPM_REGISTRY_ENDPOINTS,
    NpmRegistryEndpointConfig,
)

NPM_DOWNLOADS_BASE_URL = "https://api.npmjs.org"
NPM_REGISTRY_BASE_URL = "https://registry.npmjs.org"

DOWNLOADS_REQUEST_TIMEOUT_SECONDS = 30
# The full registry document for a popular package (every published version's manifest, inlined)
# can run several MB, so allow more time than a small downloads-range response needs.
REGISTRY_REQUEST_TIMEOUT_SECONDS = 60


@dataclasses.dataclass
class NpmRegistryResumeConfig:
    # Index into the parsed package list of the package currently in progress. Packages before
    # this index are considered fully synced for this run.
    package_index: int = 0
    # Downloads stream only: next date window's start (yyyy-mm-dd) within the in-progress package.
    window_start: Optional[str] = None


def parse_packages(raw: str | None) -> list[str]:
    """Parse the user's free-text `package_names` field into a list of npm package names.

    Accepts one package per line and/or comma-separated names (scoped names like `@scope/name`
    contain no comma or newline, so they pass through untouched). Raises `ValueError` with an
    actionable message on empty/oversized input rather than silently syncing nothing or everything.
    Names are de-duplicated (exact match — npm package names are always lowercase) while preserving
    order.
    """
    if not raw:
        raise ValueError("At least one package name is required.")

    packages: list[str] = []
    seen: set[str] = set()
    for token in re.split(r"[\n,]", raw):
        name = token.strip()
        if not name:
            continue
        if name not in seen:
            seen.add(name)
            packages.append(name)

    if not packages:
        raise ValueError("At least one package name is required.")
    if len(packages) > MAX_PACKAGES:
        raise ValueError(f"Too many packages: at most {MAX_PACKAGES} are allowed per source.")

    return packages


def _encode_package(package: str) -> str:
    # Percent-encode the whole path segment (including `@` and `/` for scoped packages like
    # `@scope/name`) so it can't break out of the URL path.
    return quote(package, safe="")


def _downloads_url(package: str, start: date, end: date) -> str:
    return f"{NPM_DOWNLOADS_BASE_URL}/downloads/range/{start.isoformat()}:{end.isoformat()}/{_encode_package(package)}"


def _registry_url(package: str) -> str:
    return f"{NPM_REGISTRY_BASE_URL}/{_encode_package(package)}"


def _read_capped(response: requests.Response, url: str) -> bytes:
    """Read a streamed response body into memory, aborting once it exceeds `MAX_RESPONSE_BYTES`.

    The document is user-selected, so we never buffer an unbounded body: we read in chunks and raise
    as soon as the running total crosses the cap, before the full body (and its parsed form) can
    exhaust the worker's memory.
    """
    total = 0
    chunks: list[bytes] = []
    for chunk in response.iter_content(chunk_size=1 << 20):
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise ValueError(
                f"npm registry response exceeded the {MAX_RESPONSE_BYTES}-byte limit (url={url}); "
                "refusing to buffer it to protect worker memory."
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _fetch_json(
    session: requests.Session, url: str, logger: FilteringBoundLogger, timeout: int
) -> dict[str, Any] | None:
    """Fetch a single JSON document. Returns `None` for a 404 (package not found) so a typo'd or
    unpublished package is skipped rather than failing the whole sync — other configured packages
    are unaffected. `make_tracked_session()` already retries transient 429/5xx transport errors.

    Streams the body and caps how much we buffer (see `_read_capped`) so a user-selected package
    can't return an unbounded document that exhausts worker memory."""
    with session.get(url, timeout=timeout, stream=True) as response:
        if response.status_code == 404:
            logger.warning(f"npm registry: package not found, skipping: url={url}")
            return None

        if not response.ok:
            logger.error(f"npm registry API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        body = _read_capped(response, url)

    return json.loads(body)


def _to_date(value: Any) -> date | None:
    """Coerce a datetime/date/ISO-string incremental value to a `date`."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError as e:
        raise ValueError(f"Could not derive a yyyy-mm-dd date from incremental value {value!r}") from e


def _first_download_window_start(
    resume_window_start: str | None,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> date:
    if resume_window_start:
        return date.fromisoformat(resume_window_start)
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        last = _to_date(db_incremental_field_last_value)
        if last is not None:
            return last + timedelta(days=1)
    return date.fromisoformat(EARLIEST_DOWNLOAD_DATE)


def _iter_downloads(
    session: requests.Session,
    package: str,
    package_index: int,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[NpmRegistryResumeConfig],
    window_start: date,
) -> Iterator[list[dict[str, Any]]]:
    """Walk one package's daily download history in fixed-size date windows.

    The API silently truncates a too-long range to its tail instead of erroring (see
    `MAX_DOWNLOADS_WINDOW_DAYS`), so every request stays within the safe cap.
    """
    today = datetime.now(UTC).date()

    while window_start <= today:
        window_end = min(window_start + timedelta(days=MAX_DOWNLOADS_WINDOW_DAYS - 1), today)
        document = _fetch_json(
            session, _downloads_url(package, window_start, window_end), logger, DOWNLOADS_REQUEST_TIMEOUT_SECONDS
        )
        if document is None:
            # Package doesn't exist (or was unpublished) — stop trying further windows for it.
            return

        rows = [
            {"package": package, "day": entry["day"], "downloads": entry.get("downloads", 0)}
            for entry in document.get("downloads") or []
            if isinstance(entry, dict) and entry.get("day")
        ]
        if rows:
            yield rows

        if window_end >= today:
            break

        window_start = window_end + timedelta(days=1)
        # Save AFTER yielding the window so a crash re-fetches it rather than skipping it; merge
        # dedupes the re-pulled days on the [package, day] primary key.
        manager.save_state(NpmRegistryResumeConfig(package_index=package_index, window_start=window_start.isoformat()))


def _first_license(licenses: Any) -> str | None:
    """Old package manifests (pre ~2015) used a `licenses: [{"type": ...}]` array instead of the
    modern single `license` string field."""
    if not isinstance(licenses, list) or not licenses:
        return None
    first = licenses[0]
    return first.get("type") if isinstance(first, dict) else None


def _iter_versions(
    session: requests.Session, package: str, logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    """One row per published version of a package, from its full registry document.

    Uses the full (non-abbreviated) document because only it carries the per-version `time[]`
    publish timestamps — the abbreviated `install-v1+json` form omits them.
    """
    document = _fetch_json(session, _registry_url(package), logger, REGISTRY_REQUEST_TIMEOUT_SECONDS)
    if document is None:
        return

    dist_tags = document.get("dist-tags") or {}
    latest_version = dist_tags.get("latest")
    publish_times = document.get("time") or {}
    versions = document.get("versions") or {}

    chunk: list[dict[str, Any]] = []
    for version, manifest in versions.items():
        if not isinstance(manifest, dict):
            continue
        dist = manifest.get("dist") or {}
        chunk.append(
            {
                "package": package,
                "version": version,
                "published_at": publish_times.get(version),
                "is_latest": version == latest_version,
                "deprecated": manifest.get("deprecated"),
                "license": manifest.get("license") or _first_license(manifest.get("licenses")),
                "description": manifest.get("description"),
                "tarball": dist.get("tarball"),
                "shasum": dist.get("shasum"),
                "integrity": dist.get("integrity"),
                "node_engine": (manifest.get("engines") or {}).get("node"),
            }
        )
        if len(chunk) >= MAX_ROWS_PER_BATCH:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def get_rows(
    endpoint: str,
    packages: list[str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NpmRegistryResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    session = make_tracked_session()
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_index = resume.package_index if resume else 0

    for index, package in enumerate(packages):
        if index < start_index:
            continue

        if endpoint == "Downloads":
            resume_window_start = resume.window_start if resume and index == start_index else None
            window_start = _first_download_window_start(
                resume_window_start, should_use_incremental_field, db_incremental_field_last_value
            )
            yield from _iter_downloads(session, package, index, logger, resumable_source_manager, window_start)
        else:
            yield from _iter_versions(session, package, logger)

        # Advance past this package before moving on, so a crash between packages resumes at the
        # next one rather than re-walking one we already finished.
        resumable_source_manager.save_state(NpmRegistryResumeConfig(package_index=index + 1, window_start=None))


def validate_packages(packages_raw: str | None) -> tuple[bool, str | None]:
    """Confirm the config is usable by probing the first configured package.

    npm's read APIs are unauthenticated, so there's no key to check — instead we confirm at least
    one package is configured and that it resolves (200) against the small downloads-point endpoint.
    """
    try:
        packages = parse_packages(packages_raw)
    except ValueError as exc:
        return False, str(exc)

    package = packages[0]
    url = f"{NPM_DOWNLOADS_BASE_URL}/downloads/point/last-day/{_encode_package(package)}"
    try:
        response = make_tracked_session().get(url, timeout=DOWNLOADS_REQUEST_TIMEOUT_SECONDS)
    except Exception:
        return False, "Could not reach the npm registry API. Please try again."

    if response.status_code == 200:
        return True, None
    if response.status_code == 404:
        return False, f"Package '{package}' was not found on the npm registry. Check the spelling and try again."

    return False, f"npm registry API returned an unexpected status code: {response.status_code}"


def npm_registry_source(
    endpoint: str,
    package_names: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NpmRegistryResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config: NpmRegistryEndpointConfig = NPM_REGISTRY_ENDPOINTS[endpoint]
    packages = parse_packages(package_names)

    partition_kwargs: dict[str, Any] = {}
    if config.partition_key is not None:
        partition_kwargs = {
            "partition_count": 1,
            "partition_size": 1,
            "partition_mode": "datetime",
            "partition_format": "month",
            "partition_keys": [config.partition_key],
        }

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            endpoint=endpoint,
            packages=packages,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # Downloads are walked oldest-window-first per package; Versions are emitted in whatever
        # order the registry document lists them (not time-ordered, but Versions isn't incremental).
        sort_mode="asc",
        **partition_kwargs,
    )
