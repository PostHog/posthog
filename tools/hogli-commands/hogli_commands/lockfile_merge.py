"""Detects a pnpm lockfile that git merged cleanly into an inconsistent state.

`pnpm-lock.yaml` is one file holding two coupled halves: `importers:` names the
version each workspace package resolved to, and `packages:`/`snapshots:` hold an
entry per resolved version. A branch that bumps a dependency edits both halves.
When master bumps the same dependency, git merges the two edits without a
conflict, because they land in different regions of a 46k-line file. The merged
lockfile can then name a version in `importers:` that no longer has an entry, and
pnpm refuses it with ERR_PNPM_LOCKFILE_MISSING_DEPENDENCY.

Nothing catches that before the merge happens. The branch's own lockfile is
valid, master's is valid, and only their merge is not, so the failure first
appears in the merge queue where the Docker build runs `--frozen-lockfile`.

This reads the lockfile rather than running `pnpm install --frozen-lockfile`
because the merged lockfile exists only as a git tree. Running pnpm against it
would mean materializing that tree and every `package.json` in it to disk first,
then a possible registry round-trip, on a path that runs before every push. The
answer is already in the file: an importer version with no matching resolution
key is exactly what `--frozen-lockfile` rejects.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

# The paths the `lockfile` preflight check already watches, so the two cannot
# disagree about where this repo keeps lockfiles. It has six, not one.
LOCKFILE_GLOBS = ("pnpm-lock.yaml", "*/pnpm-lock.yaml")

# Versions that resolve to a path or another workspace package rather than to a
# registry snapshot, so the resolution sections have nothing to hold for them.
_NON_REGISTRY_PREFIXES = ("link:", "file:", "workspace:")

_DEPENDENCY_BLOCKS = ("dependencies:", "devDependencies:", "optionalDependencies:")

# The layout below is the one pnpm writes for lockfileVersion 9. Reading a
# version this parser does not know would mistake an unrecognized layout for a
# lockfile that resolves nothing, and report every dependency as broken.
_SUPPORTED_LOCKFILE_MAJOR = "9"


@dataclass(frozen=True, kw_only=True, slots=True)
class _ImporterDependency:
    """One dependency an importer declares, and the version it resolved to."""

    package: str
    version: str


def _unquote(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    return text


def _key_before_colon(stripped: str) -> str | None:
    """The mapping key on a lockfile line, unquoted, or None for a non-key line.

    An unquoted key can itself contain ':' when the version is a tarball URL, so
    it ends either at the end of the line or at the first ': ' before a value.
    """
    if stripped.startswith(("'", '"')):
        quote = stripped[0]
        end = stripped.find(quote, 1)
        return None if end == -1 else stripped[1:end]
    if stripped.endswith(":"):
        return stripped[:-1]
    key, sep, _ = stripped.partition(": ")
    return key if sep else None


def _is_supported_layout(lockfile: str) -> bool:
    """Whether this parser knows the layout, read from the leading version key."""
    # pnpm writes lockfileVersion first, so only the head is worth splitting: the
    # whole file is 46k lines and this needs one of them.
    for line in lockfile.split("\n", 8)[:8]:
        if line.startswith("lockfileVersion:"):
            version = _unquote(line[len("lockfileVersion:") :].strip())
            return version.split(".")[0] == _SUPPORTED_LOCKFILE_MAJOR
        if line and not line[0].isspace():
            break
    return False


def _section_lines(lines: list[str], *sections: str) -> Iterator[tuple[int, str]]:
    """Indent and content of each non-blank line inside the named top-level sections."""
    in_section = False
    for line in lines:
        if line and not line[0].isspace():
            in_section = line.startswith(sections)
        elif in_section and line.strip():
            yield len(line) - len(line.lstrip(" ")), line.strip()


def _resolved_keys(lines: list[str]) -> set[str]:
    """Every version key the lockfile defines, from both resolution sections.

    A tarball dependency lands in `packages:` with no `snapshots:` entry, so
    reading one section alone reports live dependencies as missing.
    """
    return {
        key
        for indent, stripped in _section_lines(lines, "snapshots:", "packages:")
        if indent == 2 and (key := _key_before_colon(stripped))
    }


def _importer_dependencies(lines: list[str]) -> Iterator[_ImporterDependency]:
    """Every dependency the importer blocks declare."""
    in_block = False
    package = ""
    for indent, stripped in _section_lines(lines, "importers:"):
        if indent == 2:
            in_block = False
        elif indent == 4:
            in_block = stripped in _DEPENDENCY_BLOCKS
        elif indent == 6 and in_block:
            package = _key_before_colon(stripped) or ""
        elif indent == 8 and in_block and stripped.startswith("version:"):
            version = _unquote(stripped[len("version:") :].strip())
            if package and version and not version.startswith(_NON_REGISTRY_PREFIXES):
                yield _ImporterDependency(package=package, version=version)


def missing_resolutions(lockfile: str) -> list[str]:
    """Versions an importer resolves to that the lockfile does not define.

    Empty for any lockfile pnpm would accept, and empty for a lockfile whose
    layout this parser does not recognize, because a guess either way is worse
    than staying quiet. A non-empty result names the keys `--frozen-lockfile`
    reports, and needs no install to compute.
    """
    if not _is_supported_layout(lockfile):
        return []
    lines = lockfile.splitlines()
    keys = _resolved_keys(lines)
    missing = set()
    for dependency in _importer_dependencies(lines):
        key = f"{dependency.package}@{dependency.version}"
        # An aliased dependency ("npm:@scope/other@1.2.3") carries the full spec
        # in its version, so that string is the key rather than name@version.
        if key not in keys and dependency.version not in keys:
            missing.add(key)
    return sorted(missing)
