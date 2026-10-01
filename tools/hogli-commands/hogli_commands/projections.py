"""Checked-in projections of Python modules into files other languages read.

A projection carries data that no API endpoint serves, such as the task model catalog,
from the Python module that owns it to TypeScript or JSON the web app, the desktop app or
the MCP server imports. When the frontend needs the values an API accepts or returns, a
typed serializer field and the generated ``*EnumApi`` do that job instead.

Every projection is an entry in ``PROJECTIONS``. Do not add a script for a new one:
write a renderer module next to the data, register it here, and run
``hogli build:projections``. ``posthog/test/repo_invariants/test_generated_files_are_registered.py``
fails on a ``*.generated.*`` file that no entry and no known pipeline produces.

A renderer is a Python file with a ``render()`` function that returns the full text of
each output, keyed by its repo-relative path. It never writes files and never parses
arguments; this module does both, so ``--check`` and the write path cannot disagree.
"""

from __future__ import annotations

import sys
import runpy
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import click
from hogli.manifest import REPO_ROOT

REGISTRY = "tools/hogli-commands/hogli_commands/projections.py"


@dataclass(frozen=True)
class Projection:
    name: str
    # Repo-relative path of the renderer module. It is loaded by path, so a renderer
    # inside `posthog/` or `products/` does not import that package's `__init__`.
    renderer: str
    # Repo-relative globs whose change needs a regeneration. The renderer always counts.
    inputs: tuple[str, ...]
    # Repo-relative paths of every file the renderer returns.
    outputs: tuple[str, ...]

    @property
    def triggers(self) -> tuple[str, ...]:
        return (self.renderer, *self.inputs)


PROJECTIONS: tuple[Projection, ...] = (
    Projection(
        name="taxonomy",
        renderer="posthog/taxonomy/projection.py",
        inputs=("posthog/taxonomy/*",),
        outputs=(
            "frontend/src/taxonomy/core-filter-definitions-by-group.json",
            "services/mcp/src/lib/trace-property-allowlist.generated.ts",
        ),
    ),
    Projection(
        name="object-tags",
        renderer="posthog/object_tags/projection.py",
        inputs=("posthog/object_tags/*",),
        outputs=(
            "products/desktop/packages/core/src/inbox/objectKinds.generated.ts",
            "packages/agent/packages/agent-contracts/src/objectTagKinds.generated.ts",
            "frontend/src/lib/components/AgentObjectTags/objectKinds.generated.ts",
        ),
    ),
    Projection(
        name="task-model-catalog",
        renderer="products/tasks/scripts/model_catalog_projection.py",
        inputs=("products/tasks/backend/model_catalog.py",),
        outputs=(
            "products/tasks/frontend/modelCatalog.generated.ts",
            "packages/agent/packages/agent-contracts/src/model-catalog.generated.ts",
        ),
    ),
    Projection(
        name="mcp-oauth-scopes",
        renderer="posthog/scopes_projection.py",
        inputs=("posthog/scopes.py",),
        outputs=("services/mcp/src/lib/oauth-scopes.generated.ts",),
    ),
)


def all_triggers() -> tuple[str, ...]:
    # The registry counts too: a changed entry can change what a projection writes.
    return (REGISTRY, *(trigger for projection in PROJECTIONS for trigger in projection.triggers))


def all_outputs() -> tuple[str, ...]:
    return tuple(output for projection in PROJECTIONS for output in projection.outputs)


class ProjectionRunner:
    def __init__(self, repo_root: Path, projections: Iterable[Projection]) -> None:
        self.repo_root = repo_root
        self.projections = tuple(projections)

    def render(self, projection: Projection) -> dict[str, str]:
        # Ahead of site-packages, so a renderer that imports `posthog` reads this
        # checkout and not an installed copy of the same name.
        if str(self.repo_root) not in sys.path:
            sys.path.insert(0, str(self.repo_root))
        render: Callable[[], dict[str, str]] = runpy.run_path(str(self.repo_root / projection.renderer))["render"]
        rendered = render()
        if set(rendered) != set(projection.outputs):
            raise click.ClickException(
                f"{projection.renderer} rendered {sorted(rendered)}, but the registry declares "
                f"{sorted(projection.outputs)} for '{projection.name}'. Keep the two in step."
            )
        return rendered

    def stale(self, projection: Projection) -> list[str]:
        # Bytes, not text, so no newline translation can hide or invent a difference.
        return [path for path, contents in self.render(projection).items() if self._read(path) != contents.encode()]

    def write(self, projection: Projection) -> list[str]:
        written: list[str] = []
        for path, contents in self.render(projection).items():
            target = self.repo_root / path
            if self._read(path) == contents.encode():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            # Nothing reformats these bytes. A renderer emits the shape its workspace
            # formatter keeps, or the output sits in that formatter's ignore list, so the
            # drift check cannot flap.
            target.write_bytes(contents.encode())
            written.append(path)
        return written

    def _read(self, path: str) -> bytes | None:
        # None, not b"", so a missing file never matches an empty rendered output.
        target = self.repo_root / path
        return target.read_bytes() if target.exists() else None


def _select(only: tuple[str, ...]) -> tuple[Projection, ...]:
    names = {projection.name for projection in PROJECTIONS}
    unknown = sorted(set(only) - names)
    if unknown:
        raise click.BadParameter(f"unknown projection(s) {unknown}; known: {sorted(names)}", param_hint="--only")
    return tuple(projection for projection in PROJECTIONS if not only or projection.name in only)


@click.command(name="build:projections")
@click.option("--check", is_flag=True, help="Exit 1 if a checked-in output is out of date, without writing anything.")
@click.option("--only", multiple=True, metavar="NAME", help="Run only this projection. Repeat for several.")
def cmd_build_projections(check: bool, only: tuple[str, ...]) -> None:
    """Regenerate the checked-in projections of Python modules (no dev stack needed)."""
    runner = ProjectionRunner(REPO_ROOT, _select(only))
    if check:
        stale = [(projection, path) for projection in runner.projections for path in runner.stale(projection)]
        if not stale:
            return
        # stdout, because ci:preflight reports `result.stdout or result.stderr`.
        for projection, path in stale:
            click.echo(f"{path} is out of date with {', '.join(projection.inputs)}.")
        click.echo("Run `hogli build:projections` and commit the result.")
        raise SystemExit(1)
    for projection in runner.projections:
        written = runner.write(projection)
        click.echo(f"{projection.name}: {'wrote ' + ', '.join(written) if written else 'already up to date'}")
