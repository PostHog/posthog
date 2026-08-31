"""Team ownership for a test, resolved from the repository's own ownership files.

Quarantine debt asks who owes the fix now, so it resolves against the repo as it stands rather than
the capture-time span stamp the flaky rollups keep (SPEC). The web container has no checkout, so the
files are fetched and cached.
"""

from typing import Protocol

from django.core.cache import cache

import requests
import structlog
from posthog_owners import OwnersResolver

from posthog.dataclasses import frozen
from posthog.egress.github.transport import github_request

logger = structlog.get_logger(__name__)

# The raw host serves a public repo's files off a CDN, so these reads draw on no API rate limit, and
# the HEAD ref follows the default branch.
_RAW_HOST = "https://raw.githubusercontent.com"
_REF = "HEAD"
_EGRESS_SOURCE = "engineering_analytics_ownership"
_TIMEOUT_SECONDS = 5.0

_CACHE_TTL_SECONDS = 60 * 60
_CACHE_PREFIX = "eng_analytics:repo_file"
# Absence needs a cache value of its own. No file holds this one.
_ABSENT = "\x00absent"

_HTTP_OK = 200
_HTTP_NOT_FOUND = 404

# Directories a suite can run from, so its tests arrive named relative to one of these. Tried after
# the path as reported, so placement follows what the repo holds; a root missing here leaves a test
# unplaced, never attributed to the team that happens to own the same path elsewhere.
_SUITE_ROOTS = ("nodejs/", "frontend/", "services/mcp/")


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
        """Reads the file, or raises. Anything but 200 or 404 raises rather than reading as absent:
        a missing ownership file silently reattributes everything under it to an ancestor."""
        url = f"{_RAW_HOST}/{self.repository}/{_REF}/{path}"
        try:
            response = github_request(method, url, source=_EGRESS_SOURCE, timeout=_TIMEOUT_SECONDS)
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
    """Where a test lives in the repository, and which team owns it there. Either can be unknown."""

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
            return [self._for_test(test) for test in tests]
        except OwnershipUnavailable:
            logger.exception("repo_ownership_unavailable", repository=self._repository)
            return [UNPLACED] * len(tests)

    def _for_test(self, test: QuarantinedTestFile) -> TestOwnership:
        for candidate in _candidate_paths(test):
            if not self._files.exists(candidate):
                continue
            owners = self._resolver.resolve(candidate).owners
            return TestOwnership(path=candidate, owner_team=owners[0] if owners else None)
        return UNPLACED


def _candidate_paths(test: QuarantinedTestFile) -> list[str]:
    """Repo-relative paths a test could live at, most specific first.

    Nextest names a Rust test ``crate::target`` with no file at all, so it places to the crate's
    manifest; every other runner reports a path.
    """
    if test.runner == "rust":
        crate = test.parent.split("::")[0]
        return [f"rust/{crate}/Cargo.toml"] if crate else []
    reported = _strip_relative_prefix(test.file or test.parent)
    if "/" not in reported:
        return []  # a suite name ('pytest', a jest project), not a file
    return [reported, *(f"{root}{reported}" for root in _SUITE_ROOTS)]


def _strip_relative_prefix(path: str) -> str:
    while path.startswith("./") or path.startswith("../"):
        path = path.partition("/")[2]
    return path
