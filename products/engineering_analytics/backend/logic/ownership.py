"""Team ownership for a test, resolved from the repository's own ownership files.

Quarantine debt asks who owes the fix now, so it resolves against the repo as it stands rather than
the capture-time span stamp the flaky rollups keep (SPEC). The web container has no checkout, so the
files are fetched and cached.
"""

import random
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import field
from http import HTTPStatus
from typing import Protocol, TypeVar

from django.core.cache import cache

import requests
import structlog
from posthog_owners import OwnersResolver
from posthog_owners.matcher import normalize_path

from posthog.dataclasses import frozen
from posthog.egress.github.transport import github_request
from posthog.models.integration.github import _is_safe_github_repo_path

from products.engineering_analytics.backend.facade.contracts import UNOWNED_TEAM

logger = structlog.get_logger(__name__)

_T = TypeVar("_T")

# The raw host serves a public repo's files off a CDN, so these reads draw on no GitHub API rate
# limit, and the HEAD ref follows the default branch. A private repo answers 404 to all of it, which
# the root-file guard in RepoOwnership catches.
_RAW_HOST = "https://raw.githubusercontent.com"
_REF = "HEAD"
_EGRESS_SOURCE = "engineering_analytics_ownership"
# Egress metrics are labeled by endpoint, so a raw file path per label would be unbounded.
_EGRESS_ENDPOINT = "/{owner}/{repo}/{ref}/{path}"
_TIMEOUT_SECONDS = 5.0
_FETCH_WORKERS = 16

# Ownership files change at review speed, so a stale answer stays right, and only the request that
# finds the cache cold pays for the fetches. A batch writes every key at once, so the jitter spreads
# their expiry over later requests instead of stranding one with the whole refetch.
_CACHE_TTL_SECONDS = 6 * 60 * 60
_CACHE_TTL_JITTER_SECONDS = 60 * 60
_CACHE_PREFIX = "eng_analytics:repo_file"
# Absence needs a cache value of its own, and no file holds this one.
_ABSENT = "\x00absent"

_ROOT_OWNERS_FILE = "owners.yaml"

# Directories a suite can run from, so its tests arrive named relative to one of these.
_SUITE_ROOTS = ("nodejs/", "frontend/", "services/mcp/")


class OwnershipUnavailable(Exception):
    """The repository's ownership files could not be read, so no attribution is trustworthy."""


class RepoFiles(Protocol):
    def read(self, path: str) -> str | None: ...

    def exists(self, path: str) -> bool: ...

    def warm(self, paths: list[str]) -> None: ...


@frozen
class GitHubRepoFiles:
    """A public repository's files over HTTPS, cached. One per batch: it holds the batch's memo and
    its HTTP connections."""

    repository: str
    # The resolver reads each file again after the batch warmed it, and Redis is a network hop too.
    _memo: dict[str, str | None] = field(default_factory=dict)
    _session: requests.Session = field(default_factory=requests.Session)

    def read(self, path: str) -> str | None:
        if path not in self._memo:
            body = self._cached("text", path, lambda: self._body("GET", path))
            self._memo[path] = None if body == _ABSENT else body
        return self._memo[path]

    def exists(self, path: str) -> bool:
        return bool(self._cached("exists", path, lambda: self._body("HEAD", path) != _ABSENT))

    def warm(self, paths: list[str]) -> None:
        _fetch_all(self.read, paths)

    def _cached(self, kind: str, path: str, fetch: Callable[[], _T]) -> _T:
        key = f"{_CACHE_PREFIX}:{kind}:{self.repository}:{_REF}:{path}"
        cached = cache.get(key)
        if cached is None:
            cached = fetch()
            cache.set(key, cached, _CACHE_TTL_SECONDS + random.randint(0, _CACHE_TTL_JITTER_SECONDS))
        return cached

    def _body(self, method: str, path: str) -> str:
        """The file's text, or ``_ABSENT`` when the repository has no such file. Any status but 200
        or 404 raises rather than reading as absent, because a missing ownership file silently
        reattributes everything under it to an ancestor."""
        if not _is_safe_github_repo_path(self.repository):
            # Source config is team-writable, so a crafted value must not steer the URL.
            raise OwnershipUnavailable(f"unsafe repository path: {self.repository!r}")
        url = f"{_RAW_HOST}/{self.repository}/{_REF}/{path}"
        try:
            response = github_request(
                method,
                url,
                source=_EGRESS_SOURCE,
                endpoint=_EGRESS_ENDPOINT,
                timeout=_TIMEOUT_SECONDS,
                session=self._session,
            )
        except Exception as e:
            raise OwnershipUnavailable(f"could not read {path} from {self.repository}: {e}") from e
        if response.status_code == HTTPStatus.NOT_FOUND:
            return _ABSENT
        if response.status_code != HTTPStatus.OK:
            raise OwnershipUnavailable(f"{self.repository} answered {response.status_code} for {path}")
        return response.text


@frozen
class QuarantinedTestFile:
    """Where the quarantine snapshot says a test lives: a path as its suite reported it, or, for a
    Rust test, only the crate."""

    source_path: str
    crate: str


@frozen
class PlacedTest:
    path: str
    owner_team: str


UNPLACED = PlacedTest(path="", owner_team=UNOWNED_TEAM)


@frozen
class RepoOwnershipResult:
    """One placement per test. Everything is unowned whether the read failed or no team claims the
    paths, so only ``resolved`` separates a real finding from a blind board."""

    tests: list[PlacedTest]
    resolved: bool


class RepoOwnership:
    """Ownership for one repository's tests. Build one per batch: it parses each ownership file once."""

    def __init__(self, repository: str, files: RepoFiles | None = None) -> None:
        self._repository = repository
        self._files: RepoFiles = files if files is not None else GitHubRepoFiles(repository=repository)
        self._resolver = OwnersResolver(source=self._files)

    def for_tests(self, tests: list[QuarantinedTestFile]) -> RepoOwnershipResult:
        try:
            return RepoOwnershipResult(tests=self._resolve(tests), resolved=True)
        except OwnershipUnavailable:
            # One unreadable file makes every later answer suspect too, so the batch fails together
            # rather than attributing part of it.
            logger.exception("repo_ownership_unavailable", repository=self._repository)
            return RepoOwnershipResult(tests=[UNPLACED] * len(tests), resolved=False)

    def _resolve(self, tests: list[QuarantinedTestFile]) -> list[PlacedTest]:
        if self._files.read(_ROOT_OWNERS_FILE) is None:
            # Every repo this runs against declares one, so its absence proves the reader is blind
            # (a private or renamed repo answers 404 to everything), not that nobody owns anything.
            raise OwnershipUnavailable(f"{self._repository} has no root {_ROOT_OWNERS_FILE}")
        candidates = [_candidate_paths(test) for test in tests]
        present = _fetch_all(self._files.exists, [path for group in candidates for path in group])
        placed = [next((path for path in group if present[path]), None) for group in candidates]
        found = [path for path in placed if path]
        self._files.warm(self._resolver.ownership_file_paths(found))
        owners = self._resolver.map(found)
        return [
            PlacedTest(
                # A Rust crate is placed by its manifest, which is not the test's file.
                path="" if path is None or test.crate else path,
                owner_team=_team(owners[path].owners if path else None),
            )
            for test, path in zip(tests, placed, strict=True)
        ]


def _team(owners: list[str] | None) -> str:
    """An '@handle' owner is a person, and every surface downstream keys on a team slug."""
    return next((owner for owner in owners or [] if not owner.startswith("@")), UNOWNED_TEAM)


def _fetch_all(fetch: Callable[[str], _T], paths: Iterable[str]) -> dict[str, _T]:
    """Fetch every distinct path concurrently. The one place this module waits on the network."""
    todo = list(dict.fromkeys(paths))
    if not todo:
        return {}
    with ThreadPoolExecutor(max_workers=min(_FETCH_WORKERS, len(todo))) as pool:
        futures = {path: pool.submit(fetch, path) for path in todo}
        try:
            return {path: future.result() for path, future in futures.items()}
        except Exception:
            # The batch is already lost, so drop the rest instead of holding the request thread.
            pool.shutdown(cancel_futures=True)
            raise


def _candidate_paths(test: QuarantinedTestFile) -> list[str]:
    """Paths that could decide the test's ownership, most specific first. The repository decides
    which one holds the file.

    Cargo names a crate, nextest reports that name, and the directory holding it need not match:
    `common-kafka` lives at rust/common/kafka.
    """
    if test.crate:
        return [
            f"rust/{test.crate}/Cargo.toml",
            f"rust/common/{test.crate.removeprefix('common-')}/Cargo.toml",
            f"{test.crate}/Cargo.toml",
        ]
    reported = _strip_relative_prefix(normalize_path(test.source_path))
    if "/" not in reported:
        return []  # a suite name ('pytest', a jest project), not a file
    return [reported, *(f"{root}{reported}" for root in _SUITE_ROOTS)]


def _strip_relative_prefix(path: str) -> str:
    while path.startswith("../"):
        path = path.partition("/")[2]
    return path
