import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from dateutil import parser as dateutil_parser
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.nuget.settings import (
    NUGET_ENDPOINTS,
    SERVICE_INDEX_URL,
)

# Yield registration/catalog rows in chunks of this size; the pipeline batches further downstream.
ROWS_PER_YIELD = 500

# Cap the per-package existence probes at source-create so a huge pasted list can't stall the request.
MAX_VALIDATED_PACKAGES = 20

# Preference order per service-index resource; the index lists several versioned variants of each.
# RegistrationsBaseUrl/3.6.0 is the gzipped SemVer 2.0.0 view, which includes every package.
_SEARCH_TYPES = ("SearchQueryService/3.5.0", "SearchQueryService")
_REGISTRATION_TYPES = ("RegistrationsBaseUrl/3.6.0", "RegistrationsBaseUrl")
_CATALOG_TYPES = ("Catalog/3.0.0",)

PACKAGE_NOT_FOUND_PREFIX = "NuGet package not found"


class NugetRetryableError(Exception):
    pass


class NugetPackageNotFoundError(Exception):
    pass


@dataclasses.dataclass
class NugetResumeConfig:
    # catalog_events: commitTimeStamp (ISO string) of the last fully processed catalog page.
    commit_cursor: str | None = None
    # packages / package_versions: package id whose rows were fully yielded last.
    last_package_id: str | None = None


def parse_package_ids(raw: str) -> list[str]:
    """Split the user's comma/newline-separated package id list, deduping case-insensitively.

    NuGet package ids are case-insensitive; the first spelling entered is kept for display.
    Raises ``ValueError`` when no ids remain so the caller can surface a precise message.
    """
    ids: list[str] = []
    seen: set[str] = set()
    for chunk in raw.replace("\n", ",").split(","):
        package_id = chunk.strip()
        if package_id and package_id.lower() not in seen:
            seen.add(package_id.lower())
            ids.append(package_id)
    if not ids:
        raise ValueError("Enter at least one NuGet package ID (comma-separated).")
    return ids


def _parse_timestamp(value: str) -> datetime:
    # NuGet timestamps carry 7 fractional digits; dateutil truncates to microseconds, which only
    # widens the re-fetch window slightly (merge dedupes the overlap).
    return dateutil_parser.isoparse(value)


def _coerce_cursor(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str):
        try:
            return _coerce_cursor(_parse_timestamp(value))
        except ValueError:
            return None
    return None


def _resolve_resource(service_index: dict[str, Any], preferred_types: tuple[str, ...]) -> str:
    for preferred in preferred_types:
        for resource in service_index.get("resources", []):
            if resource.get("@type") == preferred:
                return str(resource["@id"])
    raise ValueError(f"NuGet service index has no resource of type {preferred_types[0]}")


@retry(
    retry=retry_if_exception_type(
        (NugetRetryableError, requests.ReadTimeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError)
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_json(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict:
    response = session.get(url, timeout=60)

    # nuget.org has no hard rate limit but asks for fair use; back off on throttles and transient 5xx.
    if response.status_code == 429 or response.status_code >= 500:
        raise NugetRetryableError(f"NuGet API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"NuGet API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _search_package(
    session: requests.Session, search_url: str, package_id: str, logger: FilteringBoundLogger
) -> dict | None:
    """Look up a single package by exact id. Returns None when search has no hit (unknown or unlisted)."""
    params = {"q": f"packageid:{package_id}", "prerelease": "true", "semVerLevel": "2.0.0"}
    data = _fetch_json(session, f"{search_url}?{urlencode(params)}", logger)
    docs = data.get("data", [])
    return docs[0] if docs else None


def _registration_index_url(registration_base_url: str, package_id: str) -> str:
    # Registration paths are keyed by the lowercased package id.
    return f"{registration_base_url}{quote(package_id.lower())}/index.json"


def _iter_registration_leaves(
    session: requests.Session, registration_base_url: str, package_id: str, logger: FilteringBoundLogger
) -> Iterator[dict]:
    """Yield every registration leaf for a package, following linked pages when not inlined."""
    try:
        index = _fetch_json(session, _registration_index_url(registration_base_url, package_id), logger)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            raise NugetPackageNotFoundError(
                f"{PACKAGE_NOT_FOUND_PREFIX}: no NuGet package with id '{package_id}' exists"
            ) from exc
        raise

    for page in index.get("items", []):
        # Packages with few versions inline their leaves; larger ones link out to per-page documents.
        leaves = page.get("items")
        if leaves is None:
            leaves = _fetch_json(session, page["@id"], logger).get("items", [])
        yield from leaves


def _normalize_version(version: str) -> str:
    # SemVer build metadata (`+sha`) is not part of version identity; search strips it.
    return version.split("+", 1)[0].lower()


def _version_downloads(search_doc: dict | None) -> dict[str, Any]:
    if not search_doc:
        return {}
    return {
        _normalize_version(entry["version"]): entry.get("downloads")
        for entry in search_doc.get("versions", [])
        if entry.get("version")
    }


def _package_row(search_doc: dict) -> dict:
    # `versions` is materialized as the package_versions table; the JSON-LD `@` keys aren't data.
    return {key: value for key, value in search_doc.items() if key != "versions" and not key.startswith("@")}


def _package_version_row(leaf: dict, downloads_by_version: dict[str, Any]) -> dict:
    entry = leaf.get("catalogEntry", {})
    row = {key: value for key, value in entry.items() if not key.startswith("@")}
    row["downloads"] = downloads_by_version.get(_normalize_version(row.get("version", "")))
    return row


def _catalog_event_row(item: dict) -> dict:
    return {
        "catalog_leaf_url": item["@id"],
        # "nuget:PackageDetails" (publish/edit) or "nuget:PackageDelete".
        "event_type": item["@type"],
        "commit_id": item.get("commitId"),
        "commit_timestamp": _parse_timestamp(item["commitTimeStamp"]),
        "package_id": item.get("nuget:id"),
        "package_version": item.get("nuget:version"),
    }


def _remaining_packages(
    package_ids: list[str],
    resumable_source_manager: ResumableSourceManager[NugetResumeConfig],
    logger: FilteringBoundLogger,
) -> list[str]:
    """Resolve the saved package-id bookmark to the packages still to process.

    A stable id bookmark (not a positional index) so a config edit between a crash and the retry
    can't resume into the wrong package. An unknown bookmark restarts from the first package —
    merge dedupes the re-pulled rows.
    """
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is None or resume.last_package_id is None:
        return package_ids
    lowered = [package_id.lower() for package_id in package_ids]
    if resume.last_package_id.lower() not in lowered:
        return package_ids
    remaining = package_ids[lowered.index(resume.last_package_id.lower()) + 1 :]
    logger.debug(f"NuGet: resuming after package {resume.last_package_id}")
    return remaining


def _get_package_rows(
    session: requests.Session,
    search_url: str,
    package_ids: list[str],
    resumable_source_manager: ResumableSourceManager[NugetResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict]]:
    remaining = _remaining_packages(package_ids, resumable_source_manager, logger)
    for index, package_id in enumerate(remaining):
        search_doc = _search_package(session, search_url, package_id, logger)
        if search_doc is None:
            # Unlisted packages are hidden from search; the package_versions table still covers them.
            logger.warning(f"NuGet: package {package_id} not returned by search, skipping")
        else:
            yield [_package_row(search_doc)]
        # Save AFTER yielding (and only while more packages remain) so a crash re-yields the last
        # package rather than skipping it — merge dedupes on the primary key.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(NugetResumeConfig(last_package_id=package_id))


def _get_package_version_rows(
    session: requests.Session,
    search_url: str,
    registration_base_url: str,
    package_ids: list[str],
    resumable_source_manager: ResumableSourceManager[NugetResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict]]:
    remaining = _remaining_packages(package_ids, resumable_source_manager, logger)
    for index, package_id in enumerate(remaining):
        # Per-version download counts only live in the search view, not the registration leaves.
        downloads_by_version = _version_downloads(_search_package(session, search_url, package_id, logger))

        rows: list[dict] = []
        for leaf in _iter_registration_leaves(session, registration_base_url, package_id, logger):
            rows.append(_package_version_row(leaf, downloads_by_version))
            if len(rows) >= ROWS_PER_YIELD:
                yield rows
                rows = []
        if rows:
            yield rows

        if index + 1 < len(remaining):
            resumable_source_manager.save_state(NugetResumeConfig(last_package_id=package_id))


def _get_catalog_event_rows(
    session: requests.Session,
    catalog_index_url: str,
    package_ids: list[str],
    resumable_source_manager: ResumableSourceManager[NugetResumeConfig],
    logger: FilteringBoundLogger,
    cursor: datetime | None,
) -> Iterator[list[dict]]:
    """Walk the catalog with the standard NuGet cursor protocol, filtered to the tracked packages.

    A page's commitTimeStamp is the max of its items and pages fill sequentially, so pages at or
    below the cursor hold nothing new and are skipped without fetching. The index's page list and
    each page's items are NOT time-ordered (verified against the live API), so both are sorted
    client-side — that's what makes the stream globally ascending and sort_mode="asc" truthful.
    """
    wanted = {package_id.lower() for package_id in package_ids}

    index = _fetch_json(session, catalog_index_url, logger)
    pages = sorted(index.get("items", []), key=lambda page: _parse_timestamp(page["commitTimeStamp"]))

    skipped = 0
    for page_entry in pages:
        if cursor is not None and _parse_timestamp(page_entry["commitTimeStamp"]) <= cursor:
            skipped += 1
            continue

        page = _fetch_json(session, page_entry["@id"], logger)
        items = sorted(page.get("items", []), key=lambda item: _parse_timestamp(item["commitTimeStamp"]))
        rows = [
            _catalog_event_row(item)
            for item in items
            if (cursor is None or _parse_timestamp(item["commitTimeStamp"]) > cursor)
            and (item.get("nuget:id") or "").lower() in wanted
        ]
        if rows:
            yield rows
        # Save AFTER yielding so a crash re-processes this page — merge dedupes the re-yielded rows.
        resumable_source_manager.save_state(NugetResumeConfig(commit_cursor=page_entry["commitTimeStamp"]))

    if skipped:
        logger.debug(f"NuGet: skipped {skipped} catalog pages at or below the cursor")


def _effective_catalog_cursor(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    resume: NugetResumeConfig | None,
) -> datetime | None:
    """Combine the incremental watermark and any saved resume checkpoint; the later one wins."""
    candidates: list[datetime] = []
    if should_use_incremental_field:
        coerced = _coerce_cursor(db_incremental_field_last_value)
        if coerced is not None:
            candidates.append(coerced)
    if resume is not None and resume.commit_cursor:
        candidates.append(_parse_timestamp(resume.commit_cursor))
    return max(candidates) if candidates else None


def get_rows(
    package_ids_raw: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NugetResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict]]:
    package_ids = parse_package_ids(package_ids_raw)
    # One session reused across every request so urllib3 keeps connections alive.
    session = make_tracked_session()
    service_index = _fetch_json(session, SERVICE_INDEX_URL, logger)

    if endpoint == "packages":
        yield from _get_package_rows(
            session, _resolve_resource(service_index, _SEARCH_TYPES), package_ids, resumable_source_manager, logger
        )
    elif endpoint == "package_versions":
        yield from _get_package_version_rows(
            session,
            _resolve_resource(service_index, _SEARCH_TYPES),
            _resolve_resource(service_index, _REGISTRATION_TYPES),
            package_ids,
            resumable_source_manager,
            logger,
        )
    elif endpoint == "catalog_events":
        resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
        cursor = _effective_catalog_cursor(should_use_incremental_field, db_incremental_field_last_value, resume)
        yield from _get_catalog_event_rows(
            session,
            _resolve_resource(service_index, _CATALOG_TYPES),
            package_ids,
            resumable_source_manager,
            logger,
            cursor,
        )
    else:
        raise ValueError(f"Unknown NuGet endpoint: {endpoint}")


def nuget_source(
    package_ids: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NugetResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = NUGET_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            package_ids_raw=package_ids,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_nuget_connection(package_ids_raw: str) -> tuple[bool, str | None]:
    """Probe the service index and each configured package's registration index.

    The public NuGet V3 API is anonymous, so "credentials" are just the package id list —
    validation checks the ids actually exist (a 404 on the registration index means they don't).
    Throttles and transient 5xx during the per-package probes must not block source creation.
    Raises ``ValueError`` when the id list is empty so the caller can surface a precise message.
    """
    package_ids = parse_package_ids(package_ids_raw)
    session = make_tracked_session()

    try:
        response = session.get(SERVICE_INDEX_URL, timeout=10)
        response.raise_for_status()
        registration_base_url = _resolve_resource(response.json(), _REGISTRATION_TYPES)
    except Exception:
        return False, "Could not reach the NuGet API. Please try again."

    unknown: list[str] = []
    for package_id in package_ids[:MAX_VALIDATED_PACKAGES]:
        try:
            probe = session.get(_registration_index_url(registration_base_url, package_id), timeout=10)
        except Exception:
            return False, "Could not reach the NuGet API. Please try again."
        if probe.status_code == 404:
            unknown.append(package_id)

    if unknown:
        return False, f"These package IDs were not found on NuGet: {', '.join(unknown)}"
    return True, None
