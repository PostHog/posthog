"""Team ownership for a test, resolved from the repository's own ownership files.

Quarantine debt asks who owes the fix now, so it resolves against the repo as it stands rather than
the capture-time span stamp the flaky rollups keep (SPEC). The web container has no checkout, so the
files are fetched and cached.
"""

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

from django.core.cache import cache

import requests
import structlog
from posthog_owners import OwnersResolver

from posthog.dataclasses import frozen
from posthog.egress.github.transport import github_request
from posthog.models.integration.github import _is_safe_github_repo_path

logger = structlog.get_logger(__name__)

# The raw host serves a public repo's files off a CDN, so these reads draw on no API rate limit, and
# the HEAD ref follows the default branch. A private repo answers 404 to all of it: see the root-file
# guard in RepoOwnership.
_RAW_HOST = "https://raw.githubusercontent.com"
_REF = "HEAD"
_EGRESS_SOURCE = "engineering_analytics_ownership"
# Constant: the egress metrics are labeled by endpoint, and a raw file path per label is unbounded.
_EGRESS_ENDPOINT = "/{owner}/{repo}/{ref}/{path}"
_TIMEOUT_SECONDS = 5.0
_WARM_WORKERS = 16

# Ownership files change at review speed, so a stale answer stays right; the window is long because
# only the request that finds the cache cold pays for the fetches.
_CACHE_TTL_SECONDS = 6 * 60 * 60
_CACHE_PREFIX = "eng_analytics:repo_file"
# Absence needs a cache value of its own. No file holds this one.
_ABSENT = "\x00absent"

_HTTP_OK = 200
_HTTP_NOT_FOUND = 404

_ROOT_OWNERS_FILE = "owners.yaml"

# Directories a suite can run from, so its tests arrive named relative to one of these. Tried after
# the path as reported, and the repository decides which one holds the file.
_SUITE_ROOTS = ("nodejs/", "frontend/", "services/mcp/")
# Cargo names a crate, nextest reports that name, and the directory holding it need not match:
# `common-kafka` lives at rust/common/kafka.
_CRATE_ROOTS = ("rust/{crate}/", "rust/common/{crate_tail}/", "{crate}/")


class OwnershipUnavailable(Exception):
    """The repository's ownership files could not be read, so no attribution is trustworthy."""


class RepoFiles(Protocol):
    """Read access to one repository: a file's contents, and whether a path is there at all."""

    def read(self, path: str) -> str | None: ...

    def exists(self, path: str) -> bool: ...


@frozen
class GitHubRepoFiles:
    """A public repository's files over HTTPS, cached."""

    repository: str

    def read(self, path: str) -> str | None:
        key = self._cache_key("text", path)
        cached = cache.get(key)
        if cached is not None:
            return None if cached == _ABSENT else str(cached)
        response = self._request("GET", path)
        text = None if response.status_code == _HTTP_NOT_FOUND else response.text
        cache.set(key, _ABSENT if text is None else text, _CACHE_TTL_SECONDS)
        return text

    def exists(self, path: str) -> bool:
        key = self._cache_key("exists", path)
        cached = cache.get(key)
        if cached is None:
            cached = self._request("HEAD", path).status_code != _HTTP_NOT_FOUND
            cache.set(key, cached, _CACHE_TTL_SECONDS)
        return bool(cached)

    def _cache_key(self, kind: str, path: str) -> str:
        return f"{_CACHE_PREFIX}:{kind}:{self.repository}:{_REF}:{path}"

    def _request(self, method: str, path: str) -> requests.Response:
        """The file, or raises. Anything but 200 or 404 raises rather than reading as absent: a
        missing ownership file silently reattributes everything under it to an ancestor."""
        if not _is_safe_github_repo_path(self.repository):
            raise OwnershipUnavailable(f"unsafe repository path: {self.repository!r}")
        url = f"{_RAW_HOST}/{self.repository}/{_REF}/{path}"
        try:
            response = github_request(
                method, url, source=_EGRESS_SOURCE, endpoint=_EGRESS_ENDPOINT, timeout=_TIMEOUT_SECONDS
            )
        except Exception as e:
            raise OwnershipUnavailable(f"could not read {path} from {self.repository}: {e}") from e
        if response.status_code not in (_HTTP_OK, _HTTP_NOT_FOUND):
            raise OwnershipUnavailable(f"{self.repository} answered {response.status_code} for {path}")
        return response


@frozen
class QuarantinedTestFile:
    """What Trunk reports about where a test lives: its runner, and the two fields that can name a path."""

    runner: str
    file: str
    parent: str


@frozen
class TestOwnership:
    """The test's file in the repository, and the team that owns it. Either can be unknown."""

    path: str | None
    owner_team: str | None


UNPLACED = TestOwnership(path=None, owner_team=None)


class RepoOwnership:
    """Ownership for one repository's tests. Build one per batch: it parses each ownership file once."""

    def __init__(self, repository: str, files: RepoFiles | None = None) -> None:
        self._repository = repository
        self._files: RepoFiles = files if files is not None else GitHubRepoFiles(repository=repository)
        self._resolver = OwnersResolver(source=self._files)

    def for_tests(self, tests: list[QuarantinedTestFile]) -> list[TestOwnership]:
        """Each test's file and owning team, in the order given.

        A failed read leaves the whole batch unowned: one unreadable file makes every later answer
        suspect too, and a part-attributed board reads as a healthy one.
        """
        try:
            return self._resolve(tests)
        except OwnershipUnavailable:
            logger.exception("repo_ownership_unavailable", repository=self._repository)
            return [UNPLACED] * len(tests)

    def _resolve(self, tests: list[QuarantinedTestFile]) -> list[TestOwnership]:
        if self._files.read(_ROOT_OWNERS_FILE) is None:
            # Every repo this runs against declares one, so its absence proves the reader is blind
            # (a private or renamed repo answers 404 to everything), not that nobody owns anything.
            raise OwnershipUnavailable(f"{self._repository} has no root {_ROOT_OWNERS_FILE}")
        candidates = [_candidate_paths(test) for test in tests]
        _warm(self._files.exists, [path for group in candidates for path in group])
        placed = [next((path for path in group if self._files.exists(path)), None) for group in candidates]
        _warm(self._files.read, [f for path in placed if path for f in self._resolver.ownership_file_paths(path)])
        return [self._own(test, path) for test, path in zip(tests, placed)]

    def _own(self, test: QuarantinedTestFile, path: str | None) -> TestOwnership:
        if path is None:
            return UNPLACED
        owners = self._resolver.resolve(path).owners or []
        # An '@handle' owner is a person, and every surface downstream keys on a team slug.
        team = next((owner for owner in owners if not owner.startswith("@")), None)
        # A Rust crate is placed by its manifest, which is not the test's file.
        return TestOwnership(path=None if test.runner == "rust" else path, owner_team=team)


def _warm(fetch: Callable[[str], object], paths: Iterable[str]) -> None:
    """Fill the cache concurrently, so the resolution that follows reads it rather than the network."""
    todo = list(dict.fromkeys(paths))
    if not todo:
        return
    with ThreadPoolExecutor(max_workers=min(_WARM_WORKERS, len(todo))) as pool:
        for _ in pool.map(fetch, todo):
            pass


def _candidate_paths(test: QuarantinedTestFile) -> list[str]:
    """Paths that could decide the test's ownership, most specific first.

    Nextest names a Rust test ``crate::target`` with no file at all, so it places by the crate's
    manifest; every other runner reports a path.
    """
    if test.runner == "rust":
        crate = test.parent.split("::")[0]
        if not crate:
            return []
        tail = crate.removeprefix("common-")
        return [f"{root.format(crate=crate, crate_tail=tail)}Cargo.toml" for root in _CRATE_ROOTS]
    reported = _strip_relative_prefix(test.file or test.parent)
    if "/" not in reported:
        return []  # a suite name ('pytest', a jest project), not a file
    return [reported, *(f"{root}{reported}" for root in _SUITE_ROOTS)]


def _strip_relative_prefix(path: str) -> str:
    while path.startswith("./") or path.startswith("../"):
        path = path.partition("/")[2]
    return path
