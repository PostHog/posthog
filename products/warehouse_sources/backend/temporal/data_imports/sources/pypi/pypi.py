import re
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import quote

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.pypi.settings import (
    PYPI_ENDPOINTS,
    PyPIEndpointConfig,
)

PYPI_BASE_URL = "https://pypi.org"

REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRY_ATTEMPTS = 5

# Each configured package costs one request per enabled stream on every sync, so cap the config to
# bound worker time and outbound fan-out — a malformed/abusive config can't tie up the pipeline.
MAX_PACKAGES = 500

# The PyPI JSON API sends `Accept: application/json`; the header keeps parity with the Stats API,
# which returns HTML without it.
_HEADERS = {"Accept": "application/json"}

# Rows for a single package are yielded in bounded chunks so a package with a huge release history
# never forces one oversized in-memory Arrow conversion downstream. The pipeline batches on top of
# this, so the exact value only caps the per-yield list size.
MAX_ROWS_PER_BATCH = 5000


class PyPIRetryableError(Exception):
    pass


def _normalize_name(name: str) -> str:
    """Normalize a project name per PEP 503 so aliases collapse to one key.

    PyPI treats ``Requests``, ``requests``, ``zope.interface`` and ``zope-interface`` as the same
    project, so we de-duplicate on this form. Otherwise two aliases both resolve to the same
    canonical name and emit rows with a colliding primary key.
    """
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_packages(raw: str | None) -> list[str]:
    """Parse the user's free-text ``packages`` field into a list of package names.

    Accepts one package per line and/or comma-separated names. Raises ``ValueError`` with an
    actionable message on empty input so the user fixes the config rather than getting a silently
    empty sync. Names are de-duplicated (on their PEP 503 normalized form) while preserving order.
    """
    if not raw:
        raise ValueError("At least one package name is required.")

    packages: list[str] = []
    seen: set[str] = set()
    for token in re.split(r"[\n,]", raw):
        name = token.strip()
        if not name:
            continue
        normalized = _normalize_name(name)
        if normalized not in seen:
            seen.add(normalized)
            packages.append(name)

        if len(packages) > MAX_PACKAGES:
            raise ValueError(f"Too many packages: at most {MAX_PACKAGES} are allowed per source.")

    if not packages:
        raise ValueError("At least one package name is required.")

    return packages


def _project_url(package: str) -> str:
    # PyPI resolves and normalizes the project name itself; percent-encode the path segment so an
    # odd character can't break out of the path.
    return f"{PYPI_BASE_URL}/pypi/{quote(package, safe='')}/json"


@retry(
    retry=retry_if_exception_type((PyPIRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_project(session: requests.Session, package: str, logger: FilteringBoundLogger) -> dict[str, Any] | None:
    """Fetch a single project's JSON document.

    Returns ``None`` for a 404 (package not found) so a typo'd or deleted package is skipped rather
    than failing the whole sync. Transient 429/5xx raise a retryable error; other client errors
    raise ``requests.HTTPError``.
    """
    url = _project_url(package)
    response = session.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 404:
        logger.warning(f"PyPI: package {package!r} not found, skipping")
        return None

    if response.status_code == 429 or response.status_code >= 500:
        raise PyPIRetryableError(f"PyPI API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"PyPI API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _canonical_name(package: str, document: dict[str, Any]) -> str:
    """Prefer PyPI's canonical project name over the user's spelling.

    PyPI normalizes names (PEP 503), so ``Requests`` and ``requests`` resolve to the same project.
    Keying rows on the canonical name keeps the primary key stable regardless of how the user typed
    the package in the config.
    """
    info = document.get("info") or {}
    return info.get("name") or package


def _project_rows(package: str, document: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """One row per project: the `info` block plus the document's top-level serial."""
    info = dict(document.get("info") or {})
    info["last_serial"] = document.get("last_serial")
    # `name` is the primary key; fall back to the requested package if the API omits it.
    info.setdefault("name", package)
    yield info


def _release_rows(package: str, document: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """One row per distribution file across every version of the project.

    Each row is stamped with the canonical `package` and its `version` (the release key), neither of
    which lives on the raw file object, so the `[package, version, filename]` primary key is complete.
    Yields lazily so a huge release history is never materialized as one big list.
    """
    canonical = _canonical_name(package, document)
    releases = document.get("releases") or {}
    for version, files in releases.items():
        if not isinstance(files, list):
            continue
        for file_obj in files:
            if not isinstance(file_obj, dict):
                continue
            # `filename` completes the `[package, version, filename]` primary key; a file object
            # missing it would merge with a null key component, so skip it rather than emit a row
            # that can't upsert cleanly.
            if not file_obj.get("filename"):
                continue
            row = dict(file_obj)
            row["package"] = canonical
            row["version"] = version
            yield row


def _vulnerability_rows(package: str, document: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """One row per known vulnerability, stamped with the canonical `package`."""
    canonical = _canonical_name(package, document)
    for vuln in document.get("vulnerabilities") or []:
        if not isinstance(vuln, dict):
            continue
        row = dict(vuln)
        row["package"] = canonical
        yield row


_ROW_BUILDERS: dict[str, Callable[[str, dict[str, Any]], Iterator[dict[str, Any]]]] = {
    "projects": _project_rows,
    "releases": _release_rows,
    "vulnerabilities": _vulnerability_rows,
}


def validate_credentials(packages_raw: str | None) -> tuple[bool, str | None]:
    """Confirm the config is usable by probing the first configured package.

    PyPI's read APIs are unauthenticated, so there is no key to check; instead we confirm at least
    one package is configured and that it resolves (200). A 404 means the package name is wrong.
    """
    try:
        packages = parse_packages(packages_raw)
    except ValueError as exc:
        return False, str(exc)

    package = packages[0]
    try:
        response = make_tracked_session().get(_project_url(package), headers=_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception:
        return False, "Could not reach the PyPI API. Please try again."

    if response.status_code == 200:
        return True, None
    if response.status_code == 404:
        return False, f"Package '{package}' was not found on PyPI. Check the spelling and try again."

    return False, f"PyPI API returned an unexpected status code: {response.status_code}"


def get_rows(
    endpoint: str,
    packages: list[str],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    build_rows = _ROW_BUILDERS[endpoint]
    # One session reused across every package so urllib3 keeps the connection alive.
    session = make_tracked_session()

    for package in packages:
        document = _fetch_project(session, package, logger)
        if document is None:
            continue
        # Stream the builder into bounded chunks: a package with a very large release history is
        # never materialized as one oversized list, and each yield caps the downstream Arrow
        # conversion. The pipeline batches on top of this.
        chunk: list[dict[str, Any]] = []
        for row in build_rows(package, document):
            chunk.append(row)
            if len(chunk) >= MAX_ROWS_PER_BATCH:
                yield chunk
                chunk = []
        if chunk:
            yield chunk


def pypi_source(
    endpoint: str,
    packages_raw: str | None,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config: PyPIEndpointConfig = PYPI_ENDPOINTS[endpoint]
    packages = parse_packages(packages_raw)

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
        items=lambda: get_rows(endpoint=endpoint, packages=packages, logger=logger),
        primary_keys=config.primary_keys,
        # No server-side ordering to rely on; rows are grouped per package as fetched.
        sort_mode="asc",
        **partition_kwargs,
    )
