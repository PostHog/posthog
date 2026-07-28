import re
import dataclasses
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.packagist.settings import (
    PACKAGIST_ENDPOINTS,
    PackagistEndpointConfig,
)

PACKAGIST_BASE_URL = "https://packagist.org"

REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRY_ATTEMPTS = 5

# Each configured package costs one request per enabled stream on every sync, so cap the expanded
# package list to bound worker time and outbound fan-out.
MAX_PACKAGES = 500

# The security advisories endpoint accepts many `packages[]` per request, so advisories are
# fetched in batches instead of one request per package.
ADVISORIES_BATCH_SIZE = 100

# Packagist asks API consumers to send a descriptive User-Agent with a contact address.
_HEADERS = {
    "User-Agent": "PostHog Data Warehouse (https://posthog.com; mailto:support@posthog.com)",
    "Accept": "application/json",
}

# Rows for a single package are yielded in bounded chunks so a package with a long download
# history never forces one oversized in-memory Arrow conversion downstream.
MAX_ROWS_PER_BATCH = 5000

# Composer package names are lowercase `vendor/package`; keep validation lenient but reject
# tokens that could break out of the URL path. Alnum runs and separators alternate without
# ambiguity (each group starts with a separator) so malformed input can't trigger the
# exponential backtracking Composer's own upstream pattern is prone to.
_PACKAGE_NAME_RE = re.compile(r"^[a-z0-9]+([_.-][a-z0-9]+)*/[a-z0-9]+((_|\.|-{1,2})[a-z0-9]+)*$")
_VENDOR_NAME_RE = re.compile(r"^[a-z0-9]+([_.-][a-z0-9]+)*$")


class PackagistRetryableError(Exception):
    pass


@dataclasses.dataclass
class PackagistResumeConfig:
    # Index into the expanded package list (advisories: into its batch walk) of the next
    # package still to fetch.
    next_package_index: int = 0


def parse_packages(raw: str | None) -> list[str]:
    """Parse the user's free-text ``packages`` field into a list of tokens.

    Accepts one entry per line and/or comma-separated. Each entry is either a full
    ``vendor/package`` name or a bare ``vendor`` (expanded to all of the vendor's packages at
    sync time). Composer names are lowercase, so tokens are lowercased before validation.
    Raises ``ValueError`` with an actionable message on empty or malformed input.
    """
    if not raw:
        raise ValueError("At least one package or vendor name is required.")

    tokens: list[str] = []
    seen: set[str] = set()
    for token in re.split(r"[\n,]", raw):
        name = token.strip().lower()
        if not name:
            continue
        if "/" in name:
            if not _PACKAGE_NAME_RE.match(name):
                raise ValueError(f"'{name}' is not a valid Composer package name (expected vendor/package).")
        elif not _VENDOR_NAME_RE.match(name):
            raise ValueError(f"'{name}' is not a valid Packagist vendor or package name.")
        if name not in seen:
            seen.add(name)
            tokens.append(name)

        if len(tokens) > MAX_PACKAGES:
            raise ValueError(f"Too many entries: at most {MAX_PACKAGES} are allowed per source.")

    if not tokens:
        raise ValueError("At least one package or vendor name is required.")

    return tokens


def _package_url(package: str) -> str:
    vendor, name = package.split("/", 1)
    return f"{PACKAGIST_BASE_URL}/packages/{quote(vendor, safe='')}/{quote(name, safe='')}.json"


def _stats_url(package: str) -> str:
    vendor, name = package.split("/", 1)
    return f"{PACKAGIST_BASE_URL}/packages/{quote(vendor, safe='')}/{quote(name, safe='')}/stats/all.json"


def _vendor_list_url(vendor: str) -> str:
    return f"{PACKAGIST_BASE_URL}/packages/list.json?{urlencode({'vendor': vendor})}"


def _advisories_url(packages: list[str]) -> str:
    return f"{PACKAGIST_BASE_URL}/api/security-advisories/?{urlencode([('packages[]', p) for p in packages])}"


@retry(
    retry=retry_if_exception_type((PackagistRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_json(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict[str, Any] | None:
    """Fetch a JSON document, returning ``None`` on 404 so a typo'd or removed package is
    skipped rather than failing the whole sync. Transient 429/5xx raise a retryable error."""
    response = session.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 404:
        logger.warning(f"Packagist: {url} returned 404, skipping")
        return None

    if response.status_code == 429 or response.status_code >= 500:
        raise PackagistRetryableError(f"Packagist API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Packagist API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def expand_vendors(session: requests.Session, tokens: list[str], logger: FilteringBoundLogger) -> list[str]:
    """Resolve bare vendor tokens into that vendor's full package list.

    ``vendor/package`` tokens pass through unchanged. Order is preserved and duplicates are
    dropped, so the resume index stays stable across attempts (Packagist returns vendor package
    lists in sorted order). The expanded list is capped at ``MAX_PACKAGES`` with a log line
    naming what was dropped — never silently.
    """
    packages: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> bool:
        if name in seen:
            return True
        if len(packages) >= MAX_PACKAGES:
            return False
        seen.add(name)
        packages.append(name)
        return True

    for token in tokens:
        if "/" in token:
            if not _add(token):
                logger.warning(f"Packagist: package list capped at {MAX_PACKAGES}; dropping {token!r} and the rest")
                break
            continue

        listing = _fetch_json(session, _vendor_list_url(token), logger)
        vendor_packages = (listing or {}).get("packageNames") or []
        if not vendor_packages:
            logger.warning(f"Packagist: vendor {token!r} has no packages, skipping")
            continue
        for name in vendor_packages:
            if not _add(name):
                logger.warning(
                    f"Packagist: package list capped at {MAX_PACKAGES} while expanding vendor {token!r}; "
                    "dropping the rest"
                )
                break

    return packages


def _package_rows(document: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """One row per package: the `package` object minus its (potentially huge) versions dict."""
    package = dict(document.get("package") or {})
    if not package.get("name"):
        return
    package.pop("versions", None)
    yield package


def _version_rows(package: str, document: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """One row per version, stamped with `package` so the `[package, version]` key is complete."""
    package_obj = document.get("package") or {}
    canonical = package_obj.get("name") or package
    versions = package_obj.get("versions") or {}
    for version, version_obj in versions.items():
        if not isinstance(version_obj, dict):
            continue
        row = dict(version_obj)
        row["package"] = canonical
        row.setdefault("version", version)
        yield row


def _download_rows(package: str, document: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """One row per day from the stats endpoint's parallel `labels`/`values` arrays."""
    labels = document.get("labels") or []
    values_by_package = document.get("values") or {}
    values = values_by_package.get(package)
    if values is None and len(values_by_package) == 1:
        values = next(iter(values_by_package.values()))
    if not isinstance(values, list):
        return
    for day, downloads in zip(labels, values):
        yield {"package": package, "date": day, "downloads": downloads}


def _advisory_rows(document: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for advisories in (document.get("advisories") or {}).values():
        if not isinstance(advisories, list):
            continue
        for advisory in advisories:
            if isinstance(advisory, dict) and advisory.get("advisoryId"):
                yield advisory


def _format_from_date(value: Any) -> str | None:
    """Coerce the incremental watermark into the `YYYY-MM-DD` string the stats endpoint takes."""
    if isinstance(value, datetime | date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}", value):
        return value[:10]
    return None


def validate_credentials(packages_raw: str | None) -> tuple[bool, str | None]:
    """Confirm the config is usable by probing the first configured entry.

    Packagist's read APIs are unauthenticated, so there is no key to check; instead we confirm
    the first package resolves (or the first vendor lists at least one package).
    """
    try:
        tokens = parse_packages(packages_raw)
    except ValueError as exc:
        return False, str(exc)

    token = tokens[0]
    session = make_tracked_session()
    is_package = "/" in token
    url = _package_url(token) if is_package else _vendor_list_url(token)
    try:
        response = session.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception:
        return False, "Could not reach the Packagist API. Please try again."

    if response.status_code == 404:
        return False, f"Package '{token}' was not found on Packagist. Check the spelling and try again."
    if response.status_code != 200:
        return False, f"Packagist API returned an unexpected status code: {response.status_code}"

    if not is_package and not (response.json().get("packageNames") or []):
        return False, f"No packages were found for vendor '{token}' on Packagist."
    return True, None


def _chunked(rows: Iterator[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
    chunk: list[dict[str, Any]] = []
    for row in rows:
        chunk.append(row)
        if len(chunk) >= MAX_ROWS_PER_BATCH:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def get_rows(
    endpoint: str,
    tokens: list[str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PackagistResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    # One session reused across every request so urllib3 keeps the connection alive.
    session = make_tracked_session()
    packages = expand_vendors(session, tokens, logger)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_index = resume.next_package_index if resume is not None else 0
    if start_index:
        logger.debug(f"Packagist: resuming {endpoint} from package index {start_index}")

    if endpoint == "security_advisories":
        for index in range(start_index, len(packages), ADVISORIES_BATCH_SIZE):
            batch = packages[index : index + ADVISORIES_BATCH_SIZE]
            document = _fetch_json(session, _advisories_url(batch), logger)
            if document is not None:
                yield from _chunked(_advisory_rows(document))
            # Save AFTER yielding so a crash re-yields the last batch rather than skipping it —
            # merge dedupes on the primary key.
            resumable_source_manager.save_state(PackagistResumeConfig(next_package_index=index + len(batch)))
        return

    from_date: str | None = None
    if endpoint == "downloads" and should_use_incremental_field:
        from_date = _format_from_date(db_incremental_field_last_value)

    for index in range(start_index, len(packages)):
        package = packages[index]

        if endpoint == "downloads":
            params = {"average": "daily"}
            if from_date is not None:
                params["from"] = from_date
            document = _fetch_json(session, f"{_stats_url(package)}?{urlencode(params)}", logger)
            rows = _download_rows(package, document) if document is not None else iter(())
        else:
            document = _fetch_json(session, _package_url(package), logger)
            if document is None:
                rows = iter(())
            elif endpoint == "packages":
                rows = _package_rows(document)
            else:
                rows = _version_rows(package, document)

        yield from _chunked(rows)
        resumable_source_manager.save_state(PackagistResumeConfig(next_package_index=index + 1))


def packagist_source(
    endpoint: str,
    packages_raw: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PackagistResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config: PackagistEndpointConfig = PACKAGIST_ENDPOINTS[endpoint]
    tokens = parse_packages(packages_raw)

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
            tokens=tokens,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # Download stats arrive in ascending date order (curl-verified); the metadata streams
        # have no server-side ordering to rely on and are grouped per package as fetched.
        sort_mode="asc",
        **partition_kwargs,
    )
