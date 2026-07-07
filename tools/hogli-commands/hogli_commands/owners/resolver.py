"""Ownership resolution for a repo-relative path.

Walks from the repo root toward the path, collecting ``owners.yaml`` (or aliased
``product.yaml``) contributions, honoring ``inherit: false`` as a hard cut, and
merges them nearest-file-wins per field. See ``docs/internal/ownership-model-proposal.md``.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .matcher import compile_pattern, normalize_path
from .schema import UNSET, OwnersFile, _Unset, parse_owners_file, parse_product_yaml_as_owners

OWNERS_FILENAME = "owners.yaml"
PRODUCT_FILENAME = "product.yaml"


@dataclass
class Resolution:
    """The resolved ownership of a single path."""

    path: str
    owners: list[str] | None  # None for both explicit-null and no-contribution
    status: str
    slack: str | None
    oncall: str | None
    source: str | None  # repo-relative path of the file that decided owners
    unowned_by_design: bool  # explicit `owners: null` exemption

    @property
    def is_owned(self) -> bool:
        return bool(self.owners)

    @property
    def is_unowned(self) -> bool:
        """Unowned and NOT exempt — what the coverage check fails on."""
        return not self.owners and not self.unowned_by_design


@dataclass
class _Merged:
    owners: list[str] | None | _Unset = UNSET
    slack: str | bool | _Unset = UNSET
    oncall: str | _Unset = UNSET
    status: str | _Unset = UNSET
    source: str | None = None


def _git_repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip())


class OwnersResolver:
    """Resolves ownership by reading ``owners.yaml`` / ``product.yaml`` from disk.

    Works from any CWD by locating the repo root via ``git rev-parse`` (override
    with ``repo_root`` for testing). Parsed files are cached per directory.
    """

    def __init__(self, repo_root: Path | None = None) -> None:
        self.repo_root = (repo_root or _git_repo_root()).resolve()
        self._dir_cache: dict[str, OwnersFile | None] = {}

    def _load_dir_file(self, directory: str) -> OwnersFile | None:
        """Ownership file for a repo-relative directory ("" = root), or None."""
        if directory in self._dir_cache:
            return self._dir_cache[directory]

        base = self.repo_root if directory == "" else self.repo_root / directory
        result: OwnersFile | None = None

        owners_path = base / OWNERS_FILENAME
        if owners_path.is_file():
            parsed, _errors = parse_owners_file(owners_path.read_text(), path=owners_path, directory=directory)
            result = parsed

        # A product.yaml alias only applies when there is no owners.yaml (a
        # directory with both is a lint error; resolve prefers owners.yaml).
        if result is None:
            product_path = base / PRODUCT_FILENAME
            if product_path.is_file():
                result = parse_product_yaml_as_owners(product_path.read_text(), path=product_path, directory=directory)

        self._dir_cache[directory] = result
        return result

    def _ancestor_dirs(self, path: str) -> list[str]:
        """Repo-relative dirs from root ("") down to the path's parent, outermost first."""
        dirs = [""]
        parts = path.split("/")[:-1]  # drop the filename
        acc: list[str] = []
        for part in parts:
            acc.append(part)
            dirs.append("/".join(acc))
        return dirs

    def _collect_files(self, path: str) -> list[OwnersFile]:
        """Ownership files on the walk to ``path``, outermost first, after applying
        ``inherit: false`` cuts."""
        collected: list[OwnersFile] = []
        for directory in self._ancestor_dirs(path):
            f = self._load_dir_file(directory)
            if f is None:
                continue
            if not f.inherit:
                # `set noparent`: discard everything collected above this file.
                collected = []
            collected.append(f)
        return collected

    def _file_contribution(self, f: OwnersFile, path: str) -> OwnersFile | None:
        """A shallow copy of the file's fields with its own last-matching rule
        applied. Returns an OwnersFile whose top-level fields hold the effective
        contribution (rules already merged in). Returns the file itself if no rule."""
        rel = path[len(f.directory) + 1 :] if f.directory else path
        matched = None
        for rule in f.rules:  # last-match-wins within the file
            if compile_pattern(rule.match).test(rel):
                matched = rule
        if matched is None:
            return f

        contrib = OwnersFile(
            path=f.path,
            directory=f.directory,
            owners=f.owners,
            slack=f.slack,
            oncall=f.oncall,
            status=f.status,
            inherit=f.inherit,
            is_alias=f.is_alias,
        )
        if not isinstance(matched.owners, _Unset):
            contrib.owners = matched.owners
        if not isinstance(matched.slack, _Unset):
            contrib.slack = matched.slack
        if not isinstance(matched.oncall, _Unset):
            contrib.oncall = matched.oncall
        if not isinstance(matched.status, _Unset):
            contrib.status = matched.status
        return contrib

    def resolve(self, path: str) -> Resolution:
        norm = normalize_path(path)
        merged = _Merged()

        for f in self._collect_files(norm):
            contrib = self._file_contribution(f, norm)
            assert contrib is not None

            # Owners: an explicit list (non-empty) or explicit null overrides; an
            # empty list is "no contribution here" and falls through.
            if contrib.owners is None:
                merged.owners = None
                merged.source = self._rel(contrib.path)
            elif contrib.owners:
                merged.owners = list(contrib.owners)
                merged.source = self._rel(contrib.path)

            if not isinstance(contrib.slack, _Unset):
                merged.slack = contrib.slack
            if not isinstance(contrib.oncall, _Unset):
                merged.oncall = contrib.oncall
            if not isinstance(contrib.status, _Unset):
                merged.status = contrib.status

        return self._build_resolution(norm, merged)

    @staticmethod
    def _effective_slack(value: str | bool | _Unset, owners: list[str] | None) -> str | None:
        if isinstance(value, _Unset):
            # Derive `#<primary owner>` when the first owner is a team slug.
            if owners and not owners[0].startswith("@"):
                return f"#{owners[0]}"
            return None
        if isinstance(value, bool):
            # Schema only admits `slack: false`; any bool means "no channel".
            return None
        return value

    def _build_resolution(self, path: str, merged: _Merged) -> Resolution:
        unowned_by_design = merged.owners is None
        owners: list[str] | None = None if isinstance(merged.owners, _Unset) else merged.owners

        status = "active" if isinstance(merged.status, _Unset) else merged.status

        slack = self._effective_slack(merged.slack, owners)

        oncall = None if isinstance(merged.oncall, _Unset) else merged.oncall

        return Resolution(
            path=path,
            owners=owners,
            status=status,
            slack=slack,
            oncall=oncall,
            source=merged.source,
            unowned_by_design=unowned_by_design,
        )

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.repo_root).as_posix()

    def map(self, paths: list[str]) -> dict[str, Resolution]:
        return {p: self.resolve(p) for p in paths}

    def unowned(self, paths: list[str]) -> list[str]:
        """The subset of ``paths`` that resolve to unowned (and not exempt)."""
        return [p for p in paths if self.resolve(p).is_unowned]

    def tracked_files(self, prefix: str | None = None) -> list[str]:
        """Repo-relative paths from ``git ls-files``, optionally under ``prefix``."""
        args = ["git", "-C", str(self.repo_root), "ls-files", "-z"]
        if prefix:
            args.append(prefix)
        result = subprocess.run(args, capture_output=True, text=True, check=True)
        return [p for p in result.stdout.split("\0") if p]

    def ownership_files(self) -> list[Path]:
        """Absolute paths of every tracked ownership file (owners.yaml + product.yaml)."""
        files: list[Path] = []
        for rel in self.tracked_files():
            name = rel.rsplit("/", 1)[-1]
            if name in (OWNERS_FILENAME, PRODUCT_FILENAME):
                files.append(self.repo_root / rel)
        return files
