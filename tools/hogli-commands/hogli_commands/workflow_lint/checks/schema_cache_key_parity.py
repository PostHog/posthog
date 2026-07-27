"""Every copy of the migration-set schema cache key must hash identical inputs.

ci-backend.yml saves one shared Postgres schema dump per master push under
``posthog-schema-mig-<epoch>-<hash>``, where the hash is computed from the
migration file blobs plus the postgres image. ci-e2e-playwright.yml,
ci-dagster.yml, ci-mcp.yml, and the .depot shadow of ci-backend.yml each
recompute that hash from their own inline copy of the shell block to restore it.

There is no cross-check at runtime: a copy that adds an input, drops a grep
filter, or reorders the printf produces a different 40-char hash, so it stops
matching every saved entry and falls back to a full migrate. CI stays green and
the only symptom is a job that got slower, which is why this has to be linted.

Three things legitimately differ between copies and are normalized away before
comparing: the git ref the inputs are read from (merge-base on restore sides,
HEAD on the save side), the ``$GITHUB_OUTPUT`` variable name the key is written
to, and the wording of ``::notice::`` / ``::warning::`` messages. The annotation
*level* is compared, so a warning present in one copy has to be present in all.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, replace
from pathlib import Path

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Workflow, WorkflowParseError, read_workflows

_BLOCK_START = "MIG_FILES="
_GUARD = re.compile(r'^if\s+\[\s+-z\s+"\$MIG_FILES"')
_SAVER = "ci-backend.yml"

# Hand-maintained mirror of .github/workflows that carries its own copy of the
# block, so it has to be compared alongside the canonical tree.
_SHADOW_DIR = Path(".depot") / "workflows"

_REF_LS_TREE = re.compile(r"(git ls-tree -r --format='%\(objectname\) %\(path\)' )\S+")
_REF_GIT_SHOW = re.compile(r'(git show ")[^:"]*(:)')
_OUTPUT_NAME = re.compile(r'^echo "[A-Za-z_][A-Za-z0-9_]*=')
_ANNOTATION = re.compile(r"(::(?:notice|warning|error)::).*")


def _normalize_body(body: str) -> str:
    body = _REF_LS_TREE.sub(r"\1<REF>", body)
    body = _REF_GIT_SHOW.sub(r"\1<REF>\2", body)
    body = _OUTPUT_NAME.sub('echo "<OUT>=', body)
    return _ANNOTATION.sub(r"\1<MESSAGE>", body)


def _normalize(block: str) -> list[str]:
    """Strip the differences that cannot change the hash, keeping everything else."""
    return [_normalize_body(line.strip()) for line in textwrap.dedent(block).splitlines() if line.strip()]


def _closing_fi(lines: list[str], start: int) -> int | None:
    """Index of the ``fi`` closing the ``if [ -z "$MIG_FILES" ]`` guard, or None."""
    guard = None
    for i in range(start, len(lines)):
        stripped = lines[i].strip()
        if i > start and stripped.startswith(_BLOCK_START):
            break  # ran into the next copy without finding a guard
        if _GUARD.match(stripped):
            guard = i
            break
    if guard is None:
        return None
    depth = 0
    for i in range(guard, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("if ") or stripped == "if":
            depth += 1
        if stripped == "fi" or stripped.startswith("fi "):
            depth -= 1
            if depth == 0:
                return i
    return None


def _hash_blocks(run: str) -> tuple[list[str], int]:
    """Extract each ``MIG_FILES=`` … ``fi`` block from one run script.

    Returns the blocks plus a count of ``MIG_FILES=`` sites whose guard could not
    be located, which is itself worth reporting rather than skipping silently.
    """
    lines = run.splitlines()
    blocks: list[str] = []
    undelimited = 0
    for start, line in enumerate(lines):
        if not line.strip().startswith(_BLOCK_START):
            continue
        end = _closing_fi(lines, start)
        if end is None:
            undelimited += 1
            continue
        blocks.append("\n".join(lines[start : end + 1]))
    return blocks, undelimited


def _label(path: Path) -> str:
    """Filename for canonical workflows, ``<dir>/<dir>/<name>`` for shadow copies."""
    if path.parent.name == "workflows" and path.parent.parent.name == ".github":
        return path.name
    return f"{path.parent.parent.name}/{path.parent.name}/{path.name}"


@dataclass(frozen=True, slots=True)
class _Site:
    """One inline copy of the key computation, located and reduced to its comparable form."""

    path: Path
    job: str
    step: str
    normalized: tuple[str, ...]

    @property
    def label(self) -> str:
        return _label(self.path)

    def issue(self, message: str) -> Issue:
        return Issue(workflow=self.label, job=self.job, step=self.step, message=message, file=str(self.path))


def _shadow_workflows(workflows: list[Workflow]) -> tuple[list[Workflow], list[str]]:
    """Load ``.depot/workflows`` mirrors sitting next to any linted ``.github/workflows``.

    Gated on the directory layout so a fixture directory never picks up the real
    repo's shadow tree.
    """
    seen = {wf.path for wf in workflows}
    roots: list[Path] = []
    for wf in workflows:
        parent = wf.path.parent
        if parent.name != "workflows" or parent.parent.name != ".github":
            continue
        root = parent.parent.parent
        if root not in roots:
            roots.append(root)

    extra: list[Workflow] = []
    errors: list[str] = []
    for root in roots:
        shadow = root / _SHADOW_DIR
        if not shadow.is_dir():
            continue
        try:
            found = list(read_workflows(shadow))
        except WorkflowParseError as exc:
            errors.append(str(exc))
            continue
        for wf in found:
            if wf.path not in seen:
                seen.add(wf.path)
                extra.append(wf)
    return extra, errors


class SchemaCacheKeyParityCheck(WorkflowCheck):
    id = "WF008-schema-cache-key-parity"
    label = "schema cache key parity"
    description = "every migration-set schema cache key computation hashes identical inputs"

    @property
    def fix_hint(self) -> str | None:
        return (
            "Make every MIG_FILES=…fi block identical (ci-backend.yml is the save side). "
            "Only the git ref, the $GITHUB_OUTPUT variable name, and annotation wording may differ. "
            "Mirror any change into .depot/workflows/ci-backend.yml in the same commit."
        )

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        shadows, shadow_errors = _shadow_workflows(workflows)
        for message in shadow_errors:
            result.issues.append(Issue(workflow=str(_SHADOW_DIR), message=message))

        sites: list[_Site] = []
        for wf in [*workflows, *shadows]:
            found, undelimited = _sites(wf)
            sites.extend(found)
            result.issues.extend(undelimited)

        groups: dict[tuple[str, ...], list[_Site]] = {}
        for site in sites:
            groups.setdefault(site.normalized, []).append(site)
        if len(groups) <= 1:
            return result

        canonical = _canonical(groups)
        reference = ", ".join(sorted({site.label for site in groups[canonical]}))
        for key, members in groups.items():
            if key == canonical:
                continue
            difference = _first_difference(canonical, key)
            for site in members:
                result.issues.append(
                    site.issue(
                        "migration-set schema cache key computation differs from the copy in "
                        f"{reference}, so it hashes to a different key and silently stops hitting the "
                        f"shared schema cache (falling back to a full migrate); {difference}"
                    )
                )
        return result


def _sites(wf: Workflow) -> tuple[list[_Site], list[Issue]]:
    """Every key computation in one workflow, plus issues for blocks that could not be delimited."""
    sites: list[_Site] = []
    issues: list[Issue] = []
    for job in wf.jobs:
        for step in job.steps:
            if step.run is None or _BLOCK_START not in step.run:
                continue
            blocks, undelimited = _hash_blocks(step.run)
            site = _Site(path=wf.path, job=job.name, step=step.ref, normalized=())
            if undelimited:
                issues.append(
                    site.issue(
                        f'{undelimited} MIG_FILES= block(s) have no `if [ -z "$MIG_FILES" ]` guard, '
                        "so the shared schema cache key cannot be compared against the other copies"
                    )
                )
            sites.extend(replace(site, normalized=tuple(_normalize(block))) for block in blocks)
    return sites, issues


def _canonical(groups: dict[tuple[str, ...], list[_Site]]) -> tuple[str, ...]:
    """The group to treat as correct: the save side's, since it is what populates the cache."""
    saver = [key for key, members in groups.items() if any(site.path.name == _SAVER for site in members)]
    if len(saver) == 1:
        return saver[0]
    # Either the save side is out of scope (a filtered --workflows-dir) or its own copies
    # disagree, so fall back to the largest group to surface the divergence deterministically.
    return max(groups, key=lambda key: (len(groups[key]), key))


def _first_difference(canonical: tuple[str, ...], other: tuple[str, ...]) -> str:
    for idx in range(max(len(canonical), len(other))):
        expected = canonical[idx] if idx < len(canonical) else "<end of block>"
        actual = other[idx] if idx < len(other) else "<end of block>"
        if expected != actual:
            return f"first difference at block line {idx + 1}: expected {expected!r}, found {actual!r}"
    return "blocks differ only in line count"


__all__ = ["SchemaCacheKeyParityCheck"]
