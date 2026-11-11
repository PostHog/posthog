"""Team ownership for a test, resolved from the repository's own ownership files.

Quarantine debt asks who owes the fix now, so it resolves against the repo as it stands and not
against the capture-time span stamp the flaky rollups keep (SPEC §6).
"""

from typing import Protocol

import structlog
from owners_yaml.matcher import normalize_path

from posthog.dataclasses import frozen
from posthog.ownership.paths import UNOWNED_TEAM, own_paths, read_root
from posthog.ownership.repo_files import GitHubRepoFiles, OwnershipUnavailable, RepoFiles

logger = structlog.get_logger(__name__)

# A TypeScript suite names its tests relative to the directory it runs from.
# Keep in step with jest_root_for_suite in .github/scripts/report_test_timings.py.
_SUITE_ROOTS = ("nodejs/", "frontend/", "services/mcp/", "common/replay-shared/")


class ProbeableRepoFiles(RepoFiles, Protocol):
    """A quarantined test arrives named by its suite, so the repository has to say which of its
    candidate paths exists."""

    def exists_all(self, paths: list[str]) -> dict[str, bool]: ...


@frozen
class QuarantinedTestFile:
    """A Rust test carries only its crate. Every other test carries the path its suite reported."""

    source_path: str
    crate: str


@frozen
class PlacedTest:
    path: str
    owner_team: str


UNPLACED = PlacedTest(path="", owner_team=UNOWNED_TEAM)


@frozen
class RepoOwnershipResult:
    """Every test is unowned both when the read failed and when no team claims the paths, so only
    ``resolved`` tells the two apart."""

    tests: list[PlacedTest]
    resolved: bool


def _strip_relative_prefix(path: str) -> str:
    while path.startswith("../"):
        path = path.partition("/")[2]
    return path


def _candidate_paths(test: QuarantinedTestFile) -> list[str]:
    """Paths that could hold the test, most specific first.

    A crate's directory need not match its name: `common-kafka` lives at rust/common/kafka.
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
    # A missing root file means the reader cannot see the repository (a private or renamed repo
    # answers 404 to everything), not that nobody owns anything.
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
    """Return one placement per test, in order. A failed read returns every test unowned with
    ``resolved=False``."""
    reader = files if files is not None else GitHubRepoFiles(repository)
    try:
        return RepoOwnershipResult(tests=_place(repository, reader, tests), resolved=True)
    except OwnershipUnavailable:
        # One unreadable file makes every other answer suspect, so the whole batch fails together.
        logger.exception("repo_ownership_unavailable", repository=repository)
        return RepoOwnershipResult(tests=[UNPLACED] * len(tests), resolved=False)
