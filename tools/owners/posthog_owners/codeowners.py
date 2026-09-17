"""A CODEOWNERS projection of the distributed owners.yaml map.

Some tools read CODEOWNERS and nothing else. Test analytics tools such as Trunk Flaky Tests
attribute each test to an owner by matching the JUnit ``file`` attribute against a CODEOWNERS file
in the checkout, so the repo's real ownership map is invisible to them.

The projection covers test files only, because that is all a test-attribution consumer looks up, and
it never writes to ``.github/CODEOWNERS``, which carries GitHub's blocking-approval semantics and
stays hand-maintained.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from posixpath import dirname

from .census import runner_for_path
from .matcher import compile_pattern
from .resolver import OwnersResolver
from .schema import CodeownersSettings


def owner_handle(owner: str, org: str) -> str:
    """A CODEOWNERS handle for one owners.yaml owner: a team slug becomes ``@org/slug``,
    an ``@handle`` for an individual is already in CODEOWNERS form."""
    return owner if owner.startswith("@") else f"@{org}/{owner}"


def _package_relative(path: str, package_dirs: tuple[str, ...], settings: CodeownersSettings) -> str | None:
    """``path`` as the nearest enclosing Node package would spell it, else None.

    A package under ``jest_root_packages`` is excluded, because ``jest_root`` runs its tests.
    """
    excluded = settings.jest_root_packages
    for directory in package_dirs:
        if path.startswith(f"{directory}/"):
            if excluded is not None and directory.startswith(f"{excluded}/"):
                return None
            return path[len(directory) + 1 :]
    return None


def _jest_root_relative(path: str, settings: CodeownersSettings) -> str | None:
    """``path`` as a suite running from ``jest_root`` spells it, for a file ``jest_root_tests`` matches."""
    if settings.jest_root is None or settings.jest_root_tests is None:
        return None
    if not compile_pattern(settings.jest_root_tests).test(path):
        return None
    depth = len(settings.jest_root.split("/"))
    return "../" * depth + path


def spellings(path: str, package_dirs: tuple[str, ...] = (), settings: CodeownersSettings | None = None) -> list[str]:
    """Every way a test runner can spell ``path`` in a JUnit ``file`` attribute.

    jest-junit writes the attribute relative to the working directory the suite ran from, which is
    not always the package that holds the file. pytest runs from the repo root, so a Python test
    has one spelling.
    """
    settings = settings or CodeownersSettings()
    found = [path]
    if runner_for_path(path) != "jest":
        return found
    for spelling in (_package_relative(path, package_dirs, settings), _jest_root_relative(path, settings)):
        if spelling is not None:
            found.append(spelling)
    return found


@dataclass(frozen=True, kw_only=True, slots=True)
class CodeownersProjection:
    """The generated file plus what it does and does not cover."""

    lines: list[str]
    owned_file_count: int
    unowned_file_count: int
    ambiguous_spellings: list[str]

    def render(self) -> str:
        header = [
            "# Generated from the repo's owners.yaml map by `owners codeowners`. Do not edit.",
            "# Test files only, for tools that attribute a test to a team through CODEOWNERS.",
            "# GitHub reads .github/CODEOWNERS for review assignment, never this file.",
            "",
        ]
        return "\n".join([*header, *self.lines, ""])


def _rule_depth(pattern: str) -> int:
    return len(pattern.strip("/").split("/"))


def project(
    paths: Iterable[str],
    resolver: OwnersResolver,
    org: str,
    package_dirs: tuple[str, ...] = (),
    settings: CodeownersSettings | None = None,
) -> CodeownersProjection:
    """Project the ownership of every test file in ``paths`` into CODEOWNERS rules.

    A spelling that two files with different owners share is dropped rather than guessed, so an
    ambiguous path reaches the consumer unowned instead of wrongly owned.
    """
    owners_by_spelling: dict[str, tuple[str, ...]] = {}
    ambiguous: set[str] = set()
    owned_files = 0
    unowned_files = 0

    for path in paths:
        if runner_for_path(path) is None:
            continue
        owners = resolver.resolve(path).owners
        if owners:
            owned_files += 1
        else:
            unowned_files += 1
        # An unowned file keeps an empty tuple, which renders as a rule with no owner after the
        # pattern. CODEOWNERS reads that as "nobody owns this", so an ancestor rule cannot claim it.
        handles = tuple(owner_handle(owner, org) for owner in owners or ())
        for spelling in spellings(path, package_dirs, settings):
            previous = owners_by_spelling.get(spelling)
            if previous is not None and previous != handles:
                ambiguous.add(spelling)
            owners_by_spelling[spelling] = handles

    # Unowned rather than absent, for the same reason: dropping the entry would leave a directory
    # rule free to claim the very spelling that is too ambiguous to attribute.
    for spelling in ambiguous:
        owners_by_spelling[spelling] = ()

    by_directory: dict[str, dict[tuple[str, ...], list[str]]] = {}
    for spelling, handles in owners_by_spelling.items():
        by_directory.setdefault(dirname(spelling), {}).setdefault(handles, []).append(spelling)

    # CODEOWNERS is last-match-wins, so sorting deeper rules later is what makes a directory rule
    # safe: every subdirectory that resolves elsewhere emits its own rule after it.
    rules: list[tuple[str, tuple[str, ...]]] = []
    for directory, groups in by_directory.items():
        if len(groups) == 1 and directory:
            [(handles, _)] = groups.items()
            rules.append((f"/{directory}/", handles))
            continue
        for handles, group in groups.items():
            rules.extend((f"/{spelling}", handles) for spelling in group)

    rules.sort(key=lambda rule: (_rule_depth(rule[0]), rule[0]))
    return CodeownersProjection(
        lines=[" ".join([pattern, *handles]) for pattern, handles in rules],
        owned_file_count=owned_files,
        unowned_file_count=unowned_files,
        ambiguous_spellings=sorted(ambiguous),
    )


def package_dirs_from(paths: Iterable[str]) -> tuple[str, ...]:
    """Directories holding a package.json, which are the working directories a Node suite runs from,
    nearest first. The repo root is excluded because a path relative to it is already the
    repo-relative spelling."""
    directories = {dirname(path) for path in paths if path.endswith("package.json") and dirname(path)}
    return tuple(sorted(directories, key=len, reverse=True))
