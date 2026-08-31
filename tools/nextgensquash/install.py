"""Copy emitted squashes into the real migration dirs and reverse that (uninstall)."""

from __future__ import annotations

import re
import sys
import argparse
import subprocess
from pathlib import Path
from typing import Any

from . import loading


def _run_install(args: argparse.Namespace) -> None:
    """Copy emitted squash files into real migration dirs, strip retired squashes'
    `replaces` (Django-canonical retirement), and delete the specific files that
    create the multi-app dep cycle (per CYCLE_DELETIONS.txt from emit).
    """
    output_dir = args.input_dir
    installed_log = output_dir / "INSTALLED.txt"
    installed: list[Path] = []
    stripped: list[Path] = []
    deleted: list[Path] = []

    apps_dirs = loading._resolve_app_migration_dirs()

    # Read cycle-break edge removals (optional).
    cycle_edges_path = output_dir / "CYCLE_EDGE_REMOVALS.txt"
    cycle_edges: list[tuple[str, str, str, str]] = []
    if cycle_edges_path.exists():
        for line in cycle_edges_path.read_text().splitlines():
            s = line.strip()
            if " -> " not in s:
                continue
            lhs, rhs = s.split(" -> ", 1)
            fa, fn = lhs.split("/", 1)
            ta, tn = rhs.split("/", 1)
            cycle_edges.append((fa, fn, ta, tn))
    # Read first-young dep-addition list (optional).
    young_adds_path = output_dir / "FIRST_YOUNG_DEP_ADDITIONS.txt"
    first_young_adds: list[tuple[str, str]] = []
    if young_adds_path.exists():
        for line in young_adds_path.read_text().splitlines():
            s = line.strip()
            if "/" in s:
                a, n = s.split("/", 1)
                first_young_adds.append((a, n))

    # Read retire manifest to know each app's leaf squash (could be finalize_fks
    # or schema_addons or just initial).
    manifest_path = output_dir / "RETIRE_MANIFEST.json"
    app_leaves: dict[str, str] = {}
    app_initials: dict[str, str] = {}
    if manifest_path.exists():
        import json as _json

        manifest = _json.loads(manifest_path.read_text())
        app_leaves = manifest.get("leaves", {}) or {}
        app_initials = manifest.get("initials", {}) or {}

    apps_processed: list[tuple[str, Path, list[Path]]] = []
    for app_dir in output_dir.iterdir() if output_dir.is_dir() else []:
        if not (app_dir / "migrations").is_dir():
            continue
        app = app_dir.name
        target_dir = apps_dirs.get(app)
        if target_dir is None:
            sys.stderr.write(f"skip {app}: no target migrations dir\n")
            continue
        squash_paths: list[Path] = []
        for src in (app_dir / "migrations").glob("*.py"):
            dest = target_dir / src.name
            dest.write_text(src.read_text())
            installed.append(dest)
            squash_paths.append(dest)
        apps_processed.append((app, target_dir, squash_paths))
        for retired in _strip_replaces_from_claimed_squashes(squash_paths, target_dir):
            stripped.append(retired)
        # Targeted cycle-break edge removals: edit `dependencies` lists in place.
        app_edges = [e for e in cycle_edges if e[0] == app]
        for edited in _strip_cycle_edges_from_migrations(app_edges, target_dir):
            if edited not in deleted:
                deleted.append(edited)
        # Add dep on the app's leaf squash to first-young so finalize_fks /
        # schema_addons run before any young migration that needs them.
        leaf_name = app_leaves.get(app)
        if leaf_name and leaf_name != app_initials.get(app):
            for a, young_name in first_young_adds:
                if a != app:
                    continue
                edited = _add_dependency_to_migration(target_dir / f"{young_name}.py", (app, leaf_name))
                if edited is not None and edited not in deleted:
                    deleted.append(edited)

    leaves = _compute_all_app_graph_leaves([app for app, _, _ in apps_processed])
    for app, target_dir, squash_paths in apps_processed:
        leaf = leaves.get(app)
        if leaf:
            (target_dir / "max_migration.txt").write_text(leaf + "\n")
            installed.append(target_dir / "max_migration.txt")
        s_count = sum(1 for d in stripped if d.parent == target_dir)
        d_count = sum(1 for d in deleted if d.parent == target_dir)
        sys.stderr.write(
            f"{app}: +{len(squash_paths)} squashes  ~{s_count} retired  -{d_count} cycle-break  max->{leaf or '(empty)'}\n"
        )

    installed_log.write_text(
        "INSTALLED:\n"
        + "\n".join(str(p) for p in installed)
        + "\nSTRIPPED:\n"
        + "\n".join(str(p) for p in stripped)
        + "\nEDITED:\n"
        + "\n".join(str(p) for p in deleted)
        + "\n"
    )
    sys.stderr.write(
        f"\ninstalled {len(installed)} files, stripped {len(stripped)} retired squashes, edited {len(deleted)} cycle-break files; log at {installed_log}\n"
    )


def _add_dependency_to_migration(path: Path, dep: tuple[str, str]) -> Path | None:
    """Add `(app, name)` as the first entry inside the migration's
    `dependencies` list. Returns the path if modified, else None.
    """

    if not path.exists():
        sys.stderr.write(f"  warning: {path} not found, can't add dep {dep!r}\n")
        return None
    src = path.read_text()
    # If already declares this dep, no-op.
    if re.search(r"\(\s*['\"]" + re.escape(dep[0]) + r"['\"]\s*,\s*['\"]" + re.escape(dep[1]) + r"['\"]\s*\)", src):
        return None
    pattern = re.compile(r"(dependencies\s*=\s*\[)", re.MULTILINE)
    inserted = pattern.sub(r"\1\n        ('" + dep[0] + r"', '" + dep[1] + r"'),", src, count=1)
    if inserted == src:
        sys.stderr.write(f"  warning: could not insert dep {dep!r} into {path}\n")
        return None
    path.write_text(inserted)
    return path


def _strip_cycle_edges_from_migrations(edges: list[tuple[str, str, str, str]], target_dir: Path) -> list[Path]:
    """For each `(from_app, from_name, to_app, to_name)`, edit
    `target_dir / from_name.py` to remove the single matching entry from its
    `dependencies` list. The entry is matched as a tuple literal like
    `("to_app", "to_name")` (single or double quotes, whitespace tolerant).
    The rest of the file is left untouched.
    """

    edited: list[Path] = []
    for _fa, fname, to_app, to_name in edges:
        p = target_dir / f"{fname}.py"
        if not p.exists():
            continue
        src = p.read_text()
        # Match: `("to_app", "to_name"),` or `("to_app", "to_name")` with quotes
        # in either style. We remove the entire line if it's the dep entry.
        pattern = re.compile(
            r"^[ \t]*\(\s*['\"]"
            + re.escape(to_app)
            + r"['\"]\s*,\s*['\"]"
            + re.escape(to_name)
            + r"['\"]\s*\)\s*,?\s*\n",
            re.MULTILINE,
        )
        new_src, count = pattern.subn("", src, count=1)
        if count == 0:
            sys.stderr.write(f"  warning: could not find dep ({to_app!r}, {to_name!r}) in {p}\n")
            continue
        p.write_text(new_src)
        edited.append(p)
    return edited


def _strip_replaces_from_claimed_squashes(squash_paths: list[Path], target_dir: Path) -> list[Path]:
    """For each pre-existing squash file in `target_dir` that's claimed by any
    of our new squashes, delete it. Our new squash already lists every migration
    name the old squash claimed in its own `replaces=` — Django doesn't need the
    file to exist to honour the redirect. Leaving the file in place was causing
    `manage.py sqlmigrate posthog 0001` ambiguity in CI (two 0001_*.py files).

    Recognising a squash: load it as a module and check `Migration.replaces`.
    Skip files we just wrote ourselves.
    """
    import importlib.util

    def load_module(p: Path) -> Any | None:
        try:
            spec = importlib.util.spec_from_file_location(f"_ngs_chk_{p.stem}_{id(p)}", p)
            if spec is None or spec.loader is None:
                return None
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
        except Exception:
            return None

    our_claims: set[str] = set()
    for sp in squash_paths:
        mod = load_module(sp)
        if mod is None:
            continue
        for _, name in getattr(mod.Migration, "replaces", []) or []:
            our_claims.add(name)

    new_stems = {p.stem for p in squash_paths}
    deleted: list[Path] = []
    for p in target_dir.glob("*.py"):
        if p.stem == "__init__" or p.stem in new_stems:
            continue
        if p.stem not in our_claims:
            continue
        # A retired squash file is one whose name matches a known prior-phase
        # squash pattern (any nextgensquash output, including the old un-dated
        # `_squashed_*`/`finalize_fks`/`schema_addons` names AND the current
        # `squash_<date>_*` names). Regular non-squash migrations stay in
        # place — Django folds them via our squash's replaces= list. We delete
        # the squash files themselves so they don't create `sqlmigrate` prefix
        # ambiguity or graph collisions with our newly emitted squash files.
        if not loading.MigrationTree._PRIOR_SQUASH_RE.search(p.stem):
            continue
        mod = load_module(p)
        if mod is None:
            continue
        p.unlink()
        deleted.append(p)
    return deleted


def _run_uninstall(args: argparse.Namespace) -> None:
    """Reverse `install`: delete what we wrote, restore what we stripped (via git)."""
    installed_log = args.input_dir / "INSTALLED.txt"
    if not installed_log.exists():
        sys.stderr.write(f"no INSTALLED.txt at {installed_log}\n")
        return

    sections: dict[str, list[Path]] = {"INSTALLED": [], "STRIPPED": [], "EDITED": []}
    cur = None
    for line in installed_log.read_text().splitlines():
        s = line.strip()
        if s in ("INSTALLED:", "STRIPPED:", "EDITED:"):
            cur = s.rstrip(":")
            continue
        if not s or cur is None:
            continue
        sections[cur].append(Path(s))

    removed = 0
    txt_files: list[Path] = []
    for p in sections["INSTALLED"]:
        if p.name == "max_migration.txt":
            txt_files.append(p)
            continue
        if p.exists():
            p.unlink()
            removed += 1
    files_to_restore = (
        [str(p) for p in txt_files] + [str(p) for p in sections["STRIPPED"]] + [str(p) for p in sections["EDITED"]]
    )
    if files_to_restore:
        subprocess.run(["git", "restore", "--", *files_to_restore], check=False)
    sys.stderr.write(
        f"removed {removed} squash files; restored {len(txt_files)} max_migration.txt + "
        f"{len(sections['STRIPPED'])} stripped + {len(sections['EDITED'])} edge-edited files via git\n"
    )


def _compute_all_app_graph_leaves(apps: list[str]) -> dict[str, str]:
    """Single subprocess that loads Django once and returns each app's graph leaf.

    Using a subprocess so we get a *fresh* MigrationLoader — the in-process one
    has already cached the pre-install state and won't see the new squash files.
    """
    if not apps:
        return {}
    apps_repr = repr(list(apps))
    code = (
        "import os, sys, json\n"
        f"sys.path.insert(0, {str(loading.REPO_ROOT)!r})\n"
        "os.environ.setdefault('DJANGO_SETTINGS_MODULE','posthog.settings')\n"
        "import django; django.setup()\n"
        "from django.db.migrations.loader import MigrationLoader\n"
        "loader = MigrationLoader(connection=None, ignore_no_migrations=True)\n"
        f"apps = {apps_repr}\n"
        "out = {}\n"
        "for app in apps:\n"
        "    leaves = sorted(n for _, n in loader.graph.leaf_nodes(app))\n"
        "    if leaves: out[app] = leaves[-1]\n"
        "print('__JSON__' + json.dumps(out))\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if line.startswith("__JSON__"):
            import json

            return json.loads(line[len("__JSON__") :])
    sys.stderr.write(f"leaf-resolver stderr:\n{result.stderr}\n")
    return {}
