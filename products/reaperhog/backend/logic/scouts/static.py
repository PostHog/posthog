import json
import shutil
import logging
import subprocess
from collections.abc import Callable
from pathlib import Path

from products.reaperhog.backend.facade.enums import NAMED_SCOPES, SCOPE_ALL, RootKind, ScoutName
from products.reaperhog.backend.logic.artefacts import Hit
from products.reaperhog.backend.logic.scouts.base import ScoutContext, ScoutIncomplete

logger = logging.getLogger(__name__)

KNIP_CONFIG = "knip.json"
KNIP_TIMEOUT_SECONDS = 900.0
KnipRunner = Callable[[Path], dict | None]


def find_knip_workspaces(root: Path, scope_path: str | None) -> list[Path]:
    base = root / scope_path if scope_path else root
    # The scope is operator-supplied and is not normalised, so "../other" would otherwise run that
    # directory's knip binary before the caller's relative_to() rejected the workspace.
    if not base.resolve().is_relative_to(root.resolve()):
        logger.warning("Skipping knip: scope %r resolves outside the checkout", scope_path)
        return []
    candidates = [base, *base.parents]
    for candidate in candidates:
        if candidate == root.parent:
            break
        if (candidate / KNIP_CONFIG).is_file():
            return [candidate]
    if scope_path:
        return []
    return sorted(path.parent for path in root.glob(f"products/*/{KNIP_CONFIG}"))


def run_knip(workspace: Path) -> dict | None:
    pnpm = shutil.which("pnpm")
    if pnpm is None or not (workspace / "node_modules").is_dir():
        logger.info("Skipping knip in %s: pnpm or node_modules missing", workspace)
        return None
    try:
        result = subprocess.run(
            [pnpm, "exec", "knip", "--reporter", "json", "--no-progress", "--no-exit-code"],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
            timeout=KNIP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        logger.warning("knip in %s did not finish within %ss", workspace, KNIP_TIMEOUT_SECONDS)
        return None
    start = result.stdout.find("{")
    if start == -1:
        logger.warning("knip in %s produced no JSON: %s", workspace, result.stderr.strip()[:200])
        return None
    try:
        return json.loads(result.stdout[start:])
    except json.JSONDecodeError:
        logger.warning("knip in %s produced unparseable JSON", workspace)
        return None


def knip_hits(report: dict, workspace_prefix: str) -> list[Hit]:
    hits: list[Hit] = []
    for file in report.get("files") or []:
        path = f"{workspace_prefix}{file}"
        hits.append(
            Hit(
                scout=ScoutName.STATIC,
                root_kind=RootKind.FILE,
                root=path,
                files=[path],
                summary="knip: no entry point imports this file",
                evidence={"tool": "knip", "issue": "unused_file"},
            )
        )
    for issue in report.get("issues") or []:
        file = issue.get("file")
        if not file:
            continue
        exports = [entry.get("name") for entry in issue.get("exports") or [] if entry.get("name")]
        types = [entry.get("name") for entry in issue.get("types") or [] if entry.get("name")]
        names = [name for name in exports + types if name]
        if not names:
            continue
        path = f"{workspace_prefix}{file}"
        hits.append(
            Hit(
                scout=ScoutName.STATIC,
                root_kind=RootKind.SYMBOL,
                root=f"{path}:{','.join(sorted(names))}",
                files=[path],
                summary=f"knip: {len(names)} unused export(s): {', '.join(sorted(names)[:8])}",
                evidence={"tool": "knip", "issue": "unused_exports", "exports": ", ".join(sorted(names))},
            )
        )
    return hits


class StaticScout:
    name = ScoutName.STATIC

    def __init__(self, runner: KnipRunner = run_knip) -> None:
        self._runner = runner

    def applies_to(self, scope: str) -> bool:
        return scope == SCOPE_ALL or scope not in NAMED_SCOPES

    def run(self, context: ScoutContext) -> list[Hit]:
        hits: list[Hit] = []
        skipped: list[str] = []
        for workspace in find_knip_workspaces(context.repo.root, context.scope_path):
            report = self._runner(workspace)
            if report is None:
                skipped.append(str(workspace))
                continue
            relative = workspace.relative_to(context.repo.root).as_posix()
            prefix = f"{relative}/" if relative and relative != "." else ""
            hits += [hit for hit in knip_hits(report, prefix) if context.in_scope(hit.files)]
        # A workspace knip never reported on has no unused files as far as this run can tell. Calling
        # the scan complete would let the vanish pass close every static cluster underneath it.
        if skipped:
            raise ScoutIncomplete(f"knip produced no report for {', '.join(skipped)}", hits)
        return hits
