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
"""

from __future__ import annotations

from dataclasses import dataclass

# Versions that resolve to a path or another workspace package rather than to a
# registry snapshot, so `snapshots:` has nothing to hold for them.
_NON_REGISTRY_PREFIXES = ("link:", "file:", "workspace:")

_DEPENDENCY_BLOCKS = ("dependencies:", "devDependencies:", "optionalDependencies:")

# The layout below is the one pnpm writes for lockfileVersion 9. Reading a
# version this parser does not know would mistake an unrecognized layout for a
# lockfile that resolves nothing, and report every dependency as broken.
_SUPPORTED_LOCKFILE_MAJOR = "9"


def _is_supported_layout(lockfile: str) -> bool:
    for line in lockfile.splitlines():
        if line.startswith("lockfileVersion:"):
            version = _unquote(line[len("lockfileVersion:") :].strip())
            return version.split(".")[0] == _SUPPORTED_LOCKFILE_MAJOR
        if line and not line[0].isspace():
            break
    return False


def _unquote(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    return text


def _key_before_colon(stripped: str) -> str | None:
    """The mapping key on a lockfile line, or None when the line is not one.

    A key may be quoted, and an unquoted key may itself contain ':' when the
    version is a tarball URL, so an unquoted key ends either at the end of the
    line or at the first ': ' that introduces a value.
    """
    if stripped.startswith(("'", '"')):
        quote = stripped[0]
        end = stripped.find(quote, 1)
        if end == -1:
            return None
        return stripped[1:end]
    if stripped.endswith(":"):
        return stripped[:-1]
    key, sep, _ = stripped.partition(": ")
    return key if sep else None


def resolved_keys(lockfile: str) -> set[str]:
    """Every version key the lockfile defines, from both resolution sections.

    A tarball dependency lands in `packages:` with no `snapshots:` entry, so
    reading one section alone reports live dependencies as missing.
    """
    keys: set[str] = set()
    in_section = False
    for line in lockfile.splitlines():
        if line and not line[0].isspace():
            in_section = line.startswith(("snapshots:", "packages:"))
            continue
        if not in_section or not line.strip():
            continue
        if len(line) - len(line.lstrip(" ")) != 2:
            continue
        key = _key_before_colon(line.strip())
        if key:
            keys.add(key)
    return keys


@dataclass(frozen=True, kw_only=True, slots=True)
class ImporterDependency:
    """One dependency an importer declares, and the version it resolved to."""

    package: str
    version: str


def importer_dependencies(lockfile: str) -> list[ImporterDependency]:
    """Every dependency the importer blocks declare."""
    dependencies: list[ImporterDependency] = []
    in_section = False
    in_block = False
    package = ""
    for line in lockfile.splitlines():
        if line and not line[0].isspace():
            in_section = line.startswith("importers:")
            continue
        if not in_section or not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if indent == 2:
            in_block = False
        elif indent == 4:
            in_block = stripped in _DEPENDENCY_BLOCKS
        elif indent == 6 and in_block:
            package = _unquote(_key_before_colon(stripped) or "")
        elif indent == 8 and in_block and stripped.startswith("version:"):
            version = _unquote(stripped[len("version:") :].strip())
            if package and version and not version.startswith(_NON_REGISTRY_PREFIXES):
                dependencies.append(ImporterDependency(package=package, version=version))
    return dependencies


def missing_resolutions(lockfile: str) -> list[str]:
    """Versions an importer resolves to that the lockfile does not define.

    Empty for any lockfile pnpm would accept, and empty for a lockfile whose
    layout this parser does not recognize, because a guess either way is worse
    than staying quiet. A non-empty result names the keys `--frozen-lockfile`
    reports, and needs no install to compute.
    """
    if not _is_supported_layout(lockfile):
        return []
    keys = resolved_keys(lockfile)
    missing = set()
    for dependency in importer_dependencies(lockfile):
        key = f"{dependency.package}@{dependency.version}"
        # An aliased dependency ("npm:@scope/other@1.2.3") carries the full spec
        # in its version, so that string is the key rather than name@version.
        if key not in keys and dependency.version not in keys:
            missing.add(key)
    return sorted(missing)
