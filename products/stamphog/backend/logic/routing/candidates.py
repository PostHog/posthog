"""The owners a pull request can request for review, from its changed files and owners.yaml.

Every owner of a changed file is a candidate, whatever the size of its part. Owners of a sensitive
path and owners of additions are pinned: the cut step never removes them (SPEC sections 3.6, 3.7).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import field
from pathlib import PurePosixPath

from owners_yaml import Resolution, path_matches_pattern

from posthog.dataclasses import frozen

from products.stamphog.backend.facade.enums import OwnerKind, PinReason

# Files whose changes are generated or mechanical. They never pull in an owner: a team gains nothing
# from reviewing a regenerated client or a lockfile bump. Keep in sync with `CONFIG.excludedPatterns`
# in .github/scripts/assign-reviewers.js while both assigners run.
EXCLUDED_PATTERNS: tuple[str, ...] = (
    "frontend/src/generated/**",
    "products/*/frontend/generated/**",
    "services/mcp/src/**/generated/**",
    # Backend CI regenerates it from the schema and replaces any hand edit, so it must not pull in desktop owners.
    "products/desktop/packages/api-client/src/generated.ts",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "uv.lock",
    "**/*.lock",
    "**/*.snap",
    "**/*.ambr",
    # Regenerated wholesale by `pnpm update-ai-costs` from the OpenRouter API.
    "nodejs/src/ingestion/pipelines/ai/costs/providers/canonical-providers.ts",
    "nodejs/src/ingestion/pipelines/ai/costs/providers/llm-costs.json",
)

# An edit to an ownership file changes future routing, so it reaches a reviewer even inside a generated tree.
_OWNERSHIP_FILE_NAMES = frozenset({"owners.yaml", "product.yaml"})
_SKIPPED_STATUSES = frozenset({"generated", "vendored"})
# GitHub reports a moved file as `renamed`, and a move into a new directory adds that directory as
# much as a new file does.
ADDED_FILE_STATUSES = frozenset({"added", "renamed", "copied"})


@frozen
class Pin:
    reason: PinReason
    path: str


@frozen
class ChangedFile:
    """One entry of GitHub's `pulls/{n}/files` list."""

    path: str
    previous_path: str | None
    status: str
    additions: int
    deletions: int
    patch: str | None

    @classmethod
    def from_github(cls, entry: Mapping[str, object]) -> ChangedFile:
        path = entry.get("filename")
        if not isinstance(path, str) or not path:
            raise ValueError("a GitHub file entry has no filename")
        previous_path = entry.get("previous_filename")
        status = entry.get("status")
        additions = entry.get("additions")
        deletions = entry.get("deletions")
        patch = entry.get("patch")
        return cls(
            path=path,
            previous_path=previous_path if isinstance(previous_path, str) and previous_path else None,
            status=status if isinstance(status, str) else "",
            # Binary files and pure renames report null counts.
            additions=additions if isinstance(additions, int) else 0,
            deletions=deletions if isinstance(deletions, int) else 0,
            patch=patch if isinstance(patch, str) else None,
        )

    @property
    def lines(self) -> int:
        return self.additions + self.deletions

    @property
    def touched_paths(self) -> tuple[str, ...]:
        # A rename changes the old path too, so a move out of a sensitive directory still counts as a
        # change there. A copy leaves its source as it was.
        if self.status == "renamed" and self.previous_path:
            return (self.path, self.previous_path)
        return (self.path,)


@frozen
class OwnerCandidate:
    """One owner as owners.yaml spells it (`team-devex` or `@alice`), with its part of the pull request."""

    owner: str
    kind: OwnerKind
    files: tuple[ChangedFile, ...]
    pins: frozenset[Pin]
    # Changed path -> the ownership file whose `owners` list names this owner for it. A path the owner
    # reached only through an additions declaration has no entry, because additions collect from every
    # file on the walk and no single file decides them.
    owners_sources: Mapping[str, str] = field(default_factory=dict)

    @property
    def lines(self) -> int:
        return sum(file.lines for file in self.files)

    @property
    def is_pinned(self) -> bool:
        return bool(self.pins)


def is_excluded(path: str) -> bool:
    if PurePosixPath(path).name in _OWNERSHIP_FILE_NAMES:
        return False
    for pattern in EXCLUDED_PATTERNS:
        try:
            if path_matches_pattern(pattern, path):
                return True
        except ValueError:
            # A malformed pattern matches nothing rather than stopping the whole routing run.
            continue
    return False


def paths_to_resolve(files: Iterable[ChangedFile]) -> list[str]:
    """Every path whose ownership the candidates need, in first-seen order and without duplicates."""
    paths: dict[str, None] = {}
    for file in files:
        for path in file.touched_paths:
            if not is_excluded(path):
                paths[path] = None
    return list(paths)


def _is_generated_or_vendored(path: str, resolution: Resolution) -> bool:
    if PurePosixPath(path).name in _OWNERSHIP_FILE_NAMES:
        return False
    return resolution.status in _SKIPPED_STATUSES


def _owner_kind(owner: str) -> OwnerKind:
    return OwnerKind.PERSON if owner.startswith("@") else OwnerKind.TEAM


class _CandidateCollector:
    def __init__(self) -> None:
        self._files: dict[str, dict[str, ChangedFile]] = {}
        self._pins: dict[str, set[Pin]] = {}
        self._sources: dict[str, dict[str, str]] = {}

    def add(self, owner: str, file: ChangedFile, *, pin: Pin | None = None, source: str | None = None) -> None:
        if not owner:
            return
        self._files.setdefault(owner, {})[file.path] = file
        pins = self._pins.setdefault(owner, set())
        if pin is not None:
            pins.add(pin)
        sources = self._sources.setdefault(owner, {})
        # The first file that names the owner wins. The plain ownership of the path is collected first.
        if source and file.path not in sources:
            sources[file.path] = source

    def candidates(self) -> list[OwnerCandidate]:
        return [
            OwnerCandidate(
                owner=owner,
                kind=_owner_kind(owner),
                files=tuple(files.values()),
                pins=frozenset(self._pins[owner]),
                owners_sources=self._sources[owner],
            )
            for owner, files in self._files.items()
        ]


def _collect_owned(collector: _CandidateCollector, file: ChangedFile, resolution: Resolution | None) -> None:
    if resolution is None or is_excluded(file.path) or _is_generated_or_vendored(file.path, resolution):
        return
    for owner in resolution.owners or []:
        collector.add(owner, file, source=resolution.source)


def _collect_additions(collector: _CandidateCollector, file: ChangedFile, resolution: Resolution | None) -> None:
    # The resolver reads the base tree, so `added` is set for any path the base lacks. The status
    # check matters on a pull request behind its base: a file it edits that the base deleted since
    # is missing from the tree too, and it adds nothing.
    if resolution is None or resolution.added is None or file.status not in ADDED_FILE_STATUSES:
        return
    if is_excluded(file.path) or _is_generated_or_vendored(file.path, resolution):
        return
    pin = Pin(reason=PinReason.NEW_PATH, path=resolution.added.path)
    for owner in resolution.added.additions:
        collector.add(owner, file, pin=pin)


def _collect_sensitive(
    collector: _CandidateCollector, file: ChangedFile, resolutions: Mapping[str, Resolution]
) -> None:
    # Generated status does not skip a sensitive path: a tool writes a ratchet baseline, but one
    # added line in it is a new exemption.
    for path in file.touched_paths:
        resolution = resolutions.get(path)
        if resolution is None or not resolution.sensitive or is_excluded(path):
            continue
        pin = Pin(reason=PinReason.SENSITIVE, path=path)
        for owner in resolution.owners or []:
            collector.add(owner, file, pin=pin, source=resolution.source)


def find_candidates(files: Sequence[ChangedFile], resolutions: Mapping[str, Resolution]) -> tuple[OwnerCandidate, ...]:
    """The candidates, largest part first. Owners with equal lines keep the owners.yaml order.

    `resolutions` maps each path from `paths_to_resolve` to its resolution against the base tree.
    """
    collector = _CandidateCollector()
    for file in files:
        resolution = resolutions.get(file.path)
        _collect_owned(collector, file, resolution)
        _collect_additions(collector, file, resolution)
        _collect_sensitive(collector, file, resolutions)
    return tuple(sorted(collector.candidates(), key=lambda candidate: -candidate.lines))
