"""Canonical Django retirement: rewrite deps to squash leaves, empty replaces, delete replaced files."""

from __future__ import annotations

import re
import sys
import argparse
from pathlib import Path

from . import loading


def _rewrite_deps_in_file(
    path: Path,
    owning_app: str,
    replaced_to_app: dict[str, str],
    initials: dict[str, str],
    leaves: dict[str, str],
) -> bool:
    """Walk `path`'s `Migration.dependencies = [...]` literal and rewrite any
    tuple `(dep_app, dep_name)` whose `dep_app/dep_name` is in `replaced_to_app`.

    Same-app references → `(dep_app, leaves[dep_app])` (post-finalize leaf, so
    young migrations layer above finalize_fks). Cross-app references →
    `(dep_app, initials[dep_app])` (pre-finalize, avoids re-creating the cycle
    that finalize_fks itself depends on). Duplicates collapsed.

    Returns True if the file was modified.
    """
    import ast

    src = path.read_text()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False

    deps_assign = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Migration":
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "dependencies" for t in stmt.targets
                ):
                    deps_assign = stmt
                    break
    if deps_assign is None or not isinstance(deps_assign.value, ast.List):
        return False

    new_tuples: list[tuple[str, str] | str] = []
    seen: set[tuple[str, str]] = set()
    changed = False
    for elt in deps_assign.value.elts:
        if (
            isinstance(elt, ast.Tuple)
            and len(elt.elts) == 2
            and all(isinstance(c, ast.Constant) and isinstance(c.value, str) for c in elt.elts)
        ):
            dep_app, dep_name = elt.elts[0].value, elt.elts[1].value
            key = f"{dep_app}/{dep_name}"
            if key in replaced_to_app:
                target_app = replaced_to_app[key]
                new_name = leaves[target_app] if target_app == owning_app else initials[target_app]
                new_pair = (target_app, new_name)
                if new_pair != (dep_app, dep_name):
                    changed = True
                pair = new_pair
            else:
                pair = (dep_app, dep_name)
            if pair not in seen:
                seen.add(pair)
                new_tuples.append(pair)
        else:
            # Preserve unusual entries (sentinel strings, fn calls, etc.) verbatim
            new_tuples.append(ast.get_source_segment(src, elt) or "")

    if not changed:
        return False

    indent = " " * 8
    lines = ["    dependencies = ["]
    for t in new_tuples:
        if isinstance(t, tuple):
            lines.append(f'{indent}("{t[0]}", "{t[1]}"),')
        elif t:
            lines.append(f"{indent}{t},")
    lines.append("    ]")
    new_block = "\n".join(lines)

    src_lines = src.splitlines()
    start = deps_assign.lineno - 1
    end = deps_assign.end_lineno - 1
    new_src = "\n".join(src_lines[:start] + new_block.splitlines() + src_lines[end + 1 :])
    if not new_src.endswith("\n"):
        new_src += "\n"
    path.write_text(new_src)
    return True


def _empty_replaces_in_squash(path: Path) -> bool:
    """Replace the `replaces = [...]` literal with `replaces = []` in a squash file."""
    src = path.read_text()
    new = re.sub(r"replaces\s*=\s*\[[^\]]*\]", "replaces = []", src, count=1, flags=re.S)
    if new == src:
        return False
    path.write_text(new)
    return True


def _run_retire(args: argparse.Namespace) -> None:
    """Canonical Django retirement of the squashes already installed via `install`.

    Reads RETIRE_MANIFEST.json from the original emit dir, rewrites every
    `dependencies=[…]` entry that names a now-folded migration to point at the
    correct squash leaf (post-finalize for same-app, pre-finalize for cross-app),
    empties `replaces=[]` on the squashes, and deletes the replaced files on
    disk. Use this only once the squash has been applied in every environment
    that depends on this repo — per Django's docs.
    """
    import json as _json

    output_dir = args.input_dir
    manifest_path = output_dir / "RETIRE_MANIFEST.json"
    if not manifest_path.exists():
        sys.stderr.write(f"no RETIRE_MANIFEST.json at {manifest_path}; run `emit` first\n")
        sys.exit(2)
    manifest = _json.loads(manifest_path.read_text())
    replaced_to_app: dict[str, str] = manifest["replaced"]
    initials: dict[str, str] = manifest["initials"]
    leaves: dict[str, str] = manifest["leaves"]

    apps_dirs = loading._resolve_app_migration_dirs()

    # 1. Rewrite dependencies across every on-disk migration file in managed apps.
    rewritten: list[Path] = []
    for app, mig_dir in apps_dirs.items():
        if not mig_dir.is_dir():
            continue
        for f in mig_dir.glob("*.py"):
            if f.name == "__init__.py":
                continue
            if _rewrite_deps_in_file(f, app, replaced_to_app, initials, leaves):
                rewritten.append(f)
    sys.stderr.write(f"rewrote dependencies= in {len(rewritten)} files\n")

    # 2. Empty replaces=[] on every squash file.
    emptied: list[Path] = []
    for app in sorted(initials):
        mig_dir = apps_dirs.get(app)
        if mig_dir is None:
            continue
        squash = mig_dir / f"{initials[app]}.py"
        if squash.exists() and _empty_replaces_in_squash(squash):
            emptied.append(squash)
    sys.stderr.write(f"emptied replaces= in {len(emptied)} squash files\n")

    # 3. Delete the replaced files on disk.
    deleted: list[Path] = []
    for replaced_key in replaced_to_app:
        replaced_app, replaced_name = replaced_key.split("/", 1)
        mig_dir = apps_dirs.get(replaced_app)
        if mig_dir is None:
            continue
        f = mig_dir / f"{replaced_name}.py"
        if f.exists():
            f.unlink()
            deleted.append(f)
    sys.stderr.write(f"deleted {len(deleted)} replaced files\n")

    log_path = output_dir / "RETIRED.txt"
    log_path.write_text(
        "REWRITTEN:\n"
        + "\n".join(str(p) for p in rewritten)
        + "\nEMPTIED:\n"
        + "\n".join(str(p) for p in emptied)
        + "\nDELETED:\n"
        + "\n".join(str(p) for p in deleted)
        + "\n"
    )
    sys.stderr.write(f"retire log at {log_path}\n")
    sys.stderr.write("\nNext: run `python manage.py migrate --check` against a fresh DB to validate.\n")
