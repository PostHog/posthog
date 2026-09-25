"""Team ownership for a test, resolved from the repository's own ownership files.

Quarantine debt asks who owes the fix now, so it resolves against the repo as it stands rather than
the capture-time span stamp the flaky rollups keep (SPEC). The web container has no checkout, so the
files are fetched and cached.
"""

from typing import Protocol

import structlog
from owners_yaml.matcher import normalize_path

from posthog.dataclasses import frozen
from posthog.ownership.paths import UNOWNED_TEAM, own_paths, read_root
from posthog.ownership.repo_files import GitHubRepoFiles, OwnershipUnavailable, RepoFiles

logger = structlog.get_logger(__name__)

# Directories a TypeScript suite can run from, so its tests arrive named relative to one of these.
# Keep in step with jest_root_for_suite in .github/scripts/report_test_timings.py, which stamps the
# same repositioning onto the CI spans.
_SUITE_ROOTS = ("nodejs/", "frontend/", "services/mcp/", "common/replay-shared/")


class ProbeableRepoFiles(RepoFiles, Protocol):
    """A reader that also answers which paths the repository holds, in batches.

    Placing a test needs this and resolving a path does not: a quarantined test arrives named by its
    suite, so the repository has to say which of its candidate paths exists.
    """

    def exists_all(self, paths: list[str]) -> dict[str, bool]: ...


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


def _strip_relative_prefix(path: str) -> str:
    while path.startswith("../"):
        path = path.partition("/")[2]
    return path


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


def _place(repository: str, files: ProbeableRepoFiles, tests: list[QuarantinedTestFile]) -> list[PlacedTest]:
    # Every repo this runs against declares one, so its absence proves the reader is blind
    # (a private or renamed repo answers 404 to everything), not that nobody owns anything.
    root = read_root(repository, files)
    candidates = [_candidate_paths(test) for test in tests]
    present = files.exists_all([path for group in candidates for path in group])
    placed = [next((path for path in group if present[path]), None) for group in candidates]
    owned = own_paths(files, root, [path for path in placed if path])
    return [
        PlacedTest(
            # A Rust crate is placed by its manifest, which is not the test's file.
            path="" if path is None or test.crate else path,
            owner_team=owned.team_by_path[path] if path else UNOWNED_TEAM,
        )
        for test, path in zip(tests, placed, strict=True)
    ]


def resolve_test_ownership(
    repository: str, tests: list[QuarantinedTestFile], files: ProbeableRepoFiles | None = None
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
