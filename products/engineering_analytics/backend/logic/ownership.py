"""Team ownership for a test, resolved from the repository's own ownership files.

Quarantine debt asks who owes the fix now, so it resolves against the repo as it stands rather than
the capture-time span stamp the flaky rollups keep (SPEC). The web container has no checkout, so the
files are fetched and cached.
"""

import random
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from time import monotonic
from typing import Any, Protocol, TypeVar

from django.core.cache import cache

import requests
import structlog
from posthog_owners import OwnershipSource, OwnersResolver
from posthog_owners.matcher import normalize_path
from requests.adapters import HTTPAdapter

from posthog.dataclasses import frozen
from posthog.egress.github.transport import github_request
from posthog.models.integration.github import _is_safe_github_repo_path

from products.engineering_analytics.backend.facade.contracts import UNOWNED_TEAM

logger = structlog.get_logger(__name__)

_T = TypeVar("_T")

# The raw host serves a public repo's files off a CDN, so these reads draw on no GitHub API rate
# limit, and the HEAD ref follows the default branch. A private repo answers 404 to all of it, which
# the root-file guard in _place catches.
_RAW_HOST = "https://raw.githubusercontent.com"
_REF = "HEAD"
_EGRESS_SOURCE = "engineering_analytics_ownership"
# Egress metrics are labeled by endpoint, so a raw file path per label would be unbounded.
_EGRESS_ENDPOINT = "/{owner}/{repo}/{ref}/{path}"
_TIMEOUT_SECONDS = 5.0
_FETCH_WORKERS = 16
# A connected repository controls these files, so an unbounded read would put its bytes in a
# worker's memory and in Redis. An ownership file is a few KB; this repo's whole set is under 25 KB.
_MAX_FILE_BYTES = 1024 * 1024
# The whole resolution, not one request. A quarantine snapshot is capped at HogQL's implicit 100
# rows, so a cold board can ask for hundreds of files; if the raw host stalls, the per-request
# timeout alone would still let one board load hold a web worker for minutes. Past this the board
# says ownership is unavailable, which beats hanging.
_RESOLVE_BUDGET_SECONDS = 20.0

# Ownership files change at review speed, so a stale answer stays right, and only the request that
# finds the cache cold pays for the fetches. A batch writes every key at once, so the jitter spreads
# their expiry over later requests instead of stranding one with the whole refetch.
_CACHE_TTL_SECONDS = 6 * 60 * 60
_CACHE_TTL_JITTER_SECONDS = 60 * 60
_CACHE_PREFIX = "eng_analytics:repo_file"
# Absence needs a cache value of its own, and no file holds this one.
_ABSENT = "\x00absent"

_ROOT_OWNERS_FILE = "owners.yaml"

# Directories a TypeScript suite can run from, so its tests arrive named relative to one of these.
# Keep in step with jest_root_for_suite in .github/scripts/report_test_timings.py, which stamps the
# same repositioning onto the CI spans.
_SUITE_ROOTS = ("nodejs/", "frontend/", "services/mcp/", "common/replay-shared/")


class OwnershipUnavailable(Exception):
    """The repository's ownership files could not be read, so no attribution is trustworthy."""


class RepoFiles(OwnershipSource, Protocol):
    """An ownership source that also answers which paths the repository holds, in batches."""

    def exists_all(self, paths: list[str]) -> dict[str, bool]: ...

    def read_all(self, paths: list[str]) -> None: ...


class GitHubRepoFiles:
    """A public repository's files over HTTPS, cached in Redis. Build one per batch: it holds the
    batch's memo and its HTTP connections."""

    def __init__(self, repository: str) -> None:
        self.repository = repository
        # Raw cache values, so ``_ABSENT`` rather than None for a file the repository does not hold.
        # The resolver reads each file again after the batch fetched it, and Redis is a network hop too.
        self._bodies: dict[str, str] = {}
        self._session = requests.Session()
        # requests pools 10 connections by default and discards the overflow, so a smaller pool than
        # the worker count makes most of the batch pay a fresh TLS handshake.
        self._session.mount(_RAW_HOST, HTTPAdapter(pool_connections=_FETCH_WORKERS, pool_maxsize=_FETCH_WORKERS))
        self._deadline = monotonic() + _RESOLVE_BUDGET_SECONDS

    def read(self, path: str) -> str | None:
        if path not in self._bodies:
            self.read_all([path])
        return None if self._bodies[path] == _ABSENT else self._bodies[path]

    def read_all(self, paths: list[str]) -> None:
        """Take every file the batch needs before it reads any, so one Redis round trip and one
        concurrent fetch cover them all."""
        self._bodies.update(self._batch("text", [p for p in paths if p not in self._bodies], self._get))

    def exists_all(self, paths: list[str]) -> dict[str, bool]:
        return self._batch("exists", paths, self._head)

    def _batch(self, kind: str, paths: Iterable[str], fetch: Callable[[str], _T]) -> dict[str, _T]:
        todo = list(dict.fromkeys(paths))
        if not todo:
            return {}
        by_key = {self._key(kind, path): path for path in todo}
        known = {by_key[key]: value for key, value in cache.get_many(list(by_key)).items()}
        fetched = _fetch_all(fetch, [path for path in todo if path not in known], self._deadline)
        if fetched:
            cache.set_many({self._key(kind, path): value for path, value in fetched.items()}, _ttl())
            known.update(fetched)
        return known

    def _key(self, kind: str, path: str) -> str:
        return f"{_CACHE_PREFIX}:{kind}:{self.repository}:{_REF}:{path}"

    def _get(self, path: str) -> str:
        """The file's text, or ``_ABSENT`` when the repository has no such file."""
        with self._response("GET", path, stream=True) as response:
            if response.status_code == HTTPStatus.NOT_FOUND:
                return _ABSENT
            return self._capped_text(response, path)

    def _head(self, path: str) -> bool:
        with self._response("HEAD", path) as response:
            return response.status_code != HTTPStatus.NOT_FOUND

    def _response(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        """Any status but 200 or 404 raises rather than reading as absent, because a missing
        ownership file silently reattributes everything under it to an ancestor."""
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
                **kwargs,
            )
        except Exception as e:
            raise OwnershipUnavailable(f"could not read {path} from {self.repository}: {e}") from e
        if response.status_code not in (HTTPStatus.OK, HTTPStatus.NOT_FOUND):
            raise OwnershipUnavailable(f"{self.repository} answered {response.status_code} for {path}")
        return response

    def _capped_text(self, response: requests.Response, path: str) -> str:
        too_large = f"{path} in {self.repository} exceeds the {_MAX_FILE_BYTES}-byte limit"
        # Content-Length can be absent or wrong, so the streamed read below is the actual ceiling.
        declared = response.headers.get("Content-Length")
        if declared is not None and declared.isdigit() and int(declared) > _MAX_FILE_BYTES:
            raise OwnershipUnavailable(too_large)
        body = bytearray()
        for chunk in response.iter_content(chunk_size=8192):
            body.extend(chunk)
            if len(body) > _MAX_FILE_BYTES:
                raise OwnershipUnavailable(too_large)
        return body.decode(response.encoding or "utf-8", errors="replace")


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


def resolve_test_ownership(
    repository: str, tests: list[QuarantinedTestFile], files: RepoFiles | None = None
) -> RepoOwnershipResult:
    """Place every test in the repository and name the team that owns it."""
    reader = files if files is not None else GitHubRepoFiles(repository)
    try:
        return RepoOwnershipResult(tests=_place(repository, reader, tests), resolved=True)
    except OwnershipUnavailable:
        # One unreadable file makes every later answer suspect too, so the batch fails together
        # rather than attributing part of it.
        logger.exception("repo_ownership_unavailable", repository=repository)
        return RepoOwnershipResult(tests=[UNPLACED] * len(tests), resolved=False)


def _place(repository: str, files: RepoFiles, tests: list[QuarantinedTestFile]) -> list[PlacedTest]:
    if files.read(_ROOT_OWNERS_FILE) is None:
        # Every repo this runs against declares one, so its absence proves the reader is blind
        # (a private or renamed repo answers 404 to everything), not that nobody owns anything.
        raise OwnershipUnavailable(f"{repository} has no root {_ROOT_OWNERS_FILE}")
    resolver = OwnersResolver(source=files)
    candidates = [_candidate_paths(test) for test in tests]
    present = files.exists_all([path for group in candidates for path in group])
    placed = [next((path for path in group if present[path]), None) for group in candidates]
    found = [path for path in placed if path]
    files.read_all(resolver.ownership_file_paths(found))
    owners = resolver.map(found)
    return [
        PlacedTest(
            # A Rust crate is placed by its manifest, which is not the test's file.
            path="" if path is None or test.crate else path,
            owner_team=_team(owners[path].owners if path else None),
        )
        for test, path in zip(tests, placed, strict=True)
    ]


def _ttl() -> int:
    return _CACHE_TTL_SECONDS + random.randint(0, _CACHE_TTL_JITTER_SECONDS)


def _team(owners: list[str] | None) -> str:
    """An '@handle' owner is a person, and every surface downstream keys on a team slug."""
    return next((owner for owner in owners or [] if not owner.startswith("@")), UNOWNED_TEAM)


def _fetch_all(fetch: Callable[[str], _T], paths: Iterable[str], deadline: float) -> dict[str, _T]:
    """Fetch every distinct path concurrently, within what is left of the batch's budget. The one
    place this module waits on the network."""
    todo = list(dict.fromkeys(paths))
    if not todo:
        return {}
    with ThreadPoolExecutor(max_workers=min(_FETCH_WORKERS, len(todo))) as pool:
        futures = {path: pool.submit(fetch, path) for path in todo}
        try:
            return {path: future.result(max(deadline - monotonic(), 0)) for path, future in futures.items()}
        except TimeoutError as e:
            pool.shutdown(cancel_futures=True)
            raise OwnershipUnavailable(f"ownership took longer than {_RESOLVE_BUDGET_SECONDS}s") from e
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
    if reported.endswith(".py"):
        return [reported]  # pytest runs from the repo root, and every suite root holds TypeScript
    return [reported, *(f"{root}{reported}" for root in _SUITE_ROOTS)]


def _strip_relative_prefix(path: str) -> str:
    while path.startswith("../"):
        path = path.partition("/")[2]
    return path
