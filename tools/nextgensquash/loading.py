"""Load every managed migration from disk, date it via git, and partition old vs young at the cutoff."""

from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from django.conf import settings  # noqa: E402
from django.db import migrations  # noqa: E402
from django.db.migrations.loader import MigrationLoader  # noqa: E402

from common.migration_utils import get_managed_app_names, get_managed_app_paths  # noqa: E402

# The package __init__ ran django.setup() before this module loads, so
# BASE_DIR is the canonical repo root — no second filesystem walk.
REPO_ROOT = Path(settings.BASE_DIR)

DEFAULT_CUTOFF = date(2026, 3, 1)

# RunPython is dropped from the proposed squash; the dropped instances are
# listed in the output so they can be re-inlined later if a fresh DB needs them.
DROP_OP_KINDS = frozenset({"RunPython"})

# Apps whose migrations are never folded, regardless of cutoff. Use for apps
# that rely on SeparateDatabaseAndState + RunPython to create non-Django DDL
# (partitioned tables, custom views, materialized columns) — Django's
# CreateModel can't reproduce that DDL, and folding would silently drop it.
EXCLUDED_APPS: frozenset[str] = frozenset(
    {
        # 0001_initial creates partitioned tables + a view via raw SQL. The
        # Django state knows the models exist (via SeparateDatabaseAndState),
        # but the DB-level DDL is partition-aware in a way `CreateModel` is
        # not. Cost is ~10ms so the squash gain is negligible anyway.
        "warehouse_sources_queue",
    }
)


@dataclass(frozen=True)
class MigrationRef:
    app: str
    name: str

    def __str__(self) -> str:
        return f"{self.app}.{self.name}"

    @property
    # nosemgrep: tuple-return-prefer-dataclass -- tuples serve as graph and dict keys here
    def key(self) -> tuple[str, str]:
        return (self.app, self.name)


@dataclass(frozen=True)
class OpInfo:
    """A migration operation summarized to its class name and a target identifier."""

    kind: str
    target: str | None = None
    # Raw SQL text for RunSQL ops (and RunSQL nested in SeparateDatabaseAndState).
    # The planner scans it for constraint/index names young migrations reference.
    sql: str | None = None
    # Index/constraint names this op declares in Django state (AddIndex,
    # AddConstraint, or their SeparateDatabaseAndState state_operations). A
    # state-backed name lands in the squash snapshot, so its raw SQL is never
    # forwarded to schema_addons.
    state_names: tuple[str, ...] = ()


@dataclass(frozen=False)
class Migration:
    ref: MigrationRef
    file_path: Path
    commit_date: date | None
    dependencies: list[MigrationRef]
    replaces: list[MigrationRef]
    run_before: list[MigrationRef]
    operations: list[OpInfo]


def _op_sql_text(op: Any) -> str:
    """Flatten RunSQL's sql attribute (str, list of str, or (sql, params) pairs) to one string."""
    sql = op.sql
    if isinstance(sql, str):
        return sql
    if isinstance(sql, (list, tuple)):
        parts: list[str] = []
        for s in sql:
            if isinstance(s, str):
                parts.append(s)
            elif isinstance(s, (list, tuple)) and s and isinstance(s[0], str):
                parts.append(s[0])
            else:
                parts.append(str(s))
        return " ".join(parts)
    return str(sql)


def _op_state_names(op: Any) -> tuple[str, ...]:
    thing = getattr(op, "index", None) or getattr(op, "constraint", None)
    name = getattr(thing, "name", None)
    return (name,) if isinstance(name, str) else ()


def _summarize_op(op: Any) -> OpInfo:
    kind = op.__class__.__name__
    if kind == "RunPython":
        target = getattr(op.code, "__name__", None) or repr(op.code)
        return OpInfo(kind=kind, target=target)
    if isinstance(op, migrations.RunSQL):
        return OpInfo(kind=kind, target=None, sql=_op_sql_text(op))
    if isinstance(op, migrations.SeparateDatabaseAndState):
        inner = [_op_sql_text(o) for o in op.database_operations if isinstance(o, migrations.RunSQL)]
        state_names = tuple(n for o in op.state_operations for n in _op_state_names(o))
        return OpInfo(kind=kind, sql=" ".join(inner) or None, state_names=state_names)
    target = getattr(op, "name", None) or getattr(op, "model_name", None)
    return OpInfo(kind=kind, target=target if isinstance(target, str) else None, state_names=_op_state_names(op))


class GitDates:
    """Batch-resolves the first-added commit date for each given file path."""

    COMMIT_PREFIX = "__C__"

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root

    def first_added(self, files: list[Path]) -> dict[Path, date]:
        if not files:
            return {}
        rel = [str(f.relative_to(self.repo_root)) for f in files]
        result = subprocess.run(
            [
                "git",
                "-C",
                str(self.repo_root),
                "log",
                "--diff-filter=A",
                "--reverse",
                f"--format={self.COMMIT_PREFIX}%cI",
                "--name-only",
                "--",
                *rel,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return self._parse(result.stdout)

    def _parse(self, stdout: str) -> dict[Path, date]:
        out: dict[Path, date] = {}
        cur: date | None = None
        for line in stdout.splitlines():
            if line.startswith(self.COMMIT_PREFIX):
                cur = datetime.fromisoformat(line[len(self.COMMIT_PREFIX) :]).date()
                continue
            stripped = line.strip()
            if not stripped or cur is None:
                continue
            p = self.repo_root / stripped
            if p not in out:
                out[p] = cur
        return out


class MigrationTree:
    """All Django migrations loaded from disk via the MigrationLoader."""

    def __init__(self, migrations: dict[tuple[str, str], Migration]):
        self.migrations = migrations

    @staticmethod
    def _discover_files(repo_root: Path) -> list[Path]:
        files: list[Path] = []
        for root in get_managed_app_paths(repo_root).values():
            if not root.is_dir():
                continue
            files.extend(f for f in root.glob("*.py") if f.name != "__init__.py")
        return files

    @classmethod
    def load(cls, repo_root: Path) -> MigrationTree:
        files = cls._discover_files(repo_root)
        dates = GitDates(repo_root).first_added(files)
        loader = MigrationLoader(connection=None, ignore_no_migrations=True)
        managed = get_managed_app_names(repo_root)

        out: dict[tuple[str, str], Migration] = {}
        for (app, name), m in loader.graph.nodes.items():
            if app not in managed:
                continue  # skip third-party apps (auth, admin, axes, etc.)
            file_path = repo_root / Path(*m.__module__.split(".")).with_suffix(".py")
            out[(app, name)] = Migration(
                ref=MigrationRef(app=app, name=name),
                file_path=file_path,
                commit_date=dates.get(file_path),
                dependencies=[MigrationRef(a, n) for (a, n) in m.dependencies],
                replaces=[MigrationRef(a, n) for (a, n) in (m.replaces or [])],
                run_before=[MigrationRef(a, n) for (a, n) in (m.run_before or [])],
                operations=[_summarize_op(op) for op in m.operations],
            )
        return cls(out)

    # Names emitted by a previous nextgensquash phase. Always treated as old
    # regardless of `commit_date`, so a stacked phase can fold them into its
    # own `replaces=` list (cutoff alone wouldn't, since the prior squash files
    # are usually newer than any reasonable phase-N cutoff). Covers both the
    # historical un-dated names (squashed_stub/initial, finalize_fks,
    # schema_addons) and the current dated scheme (squash_stub, squash_<date>_*).
    _PRIOR_SQUASH_RE = re.compile(
        r"_squashed_(stub|initial)$"
        r"|^[0-9]+_squash_stub$"
        r"|^[0-9]+_squash_[0-9_]+_(initial|finalize_fks|schema_addons)$"
        r"|^[0-9]+_finalize_fks$"
        r"|^[0-9]+_schema_addons$"
    )

    def partition(
        self,
        cutoff: date,
        include_prior_squashes: bool = True,
        # nosemgrep: tuple-return-prefer-dataclass -- tuples serve as graph and dict keys here
    ) -> tuple[dict[tuple[str, str], Migration], dict[tuple[str, str], Migration]]:
        old: dict[tuple[str, str], Migration] = {}
        young: dict[tuple[str, str], Migration] = {}
        for k, m in self.migrations.items():
            if m.ref.app in EXCLUDED_APPS:
                young[k] = m
                continue
            is_old = bool(m.commit_date and m.commit_date < cutoff)
            if not is_old and include_prior_squashes and self._PRIOR_SQUASH_RE.search(m.ref.name):
                is_old = True
            if is_old:
                old[k] = m
            else:
                young[k] = m
        return old, young

    @staticmethod
    def group_by_app(subset: dict[tuple[str, str], Migration]) -> dict[str, list[Migration]]:
        out: dict[str, list[Migration]] = defaultdict(list)
        for m in subset.values():
            out[m.ref.app].append(m)
        for migs in out.values():
            migs.sort(key=lambda m: m.ref.name)
        return out


def _resolve_app_migration_dirs() -> dict[str, Path]:
    """Map app_label -> on-disk migrations directory."""
    from django.apps import apps as django_apps

    out: dict[str, Path] = {}
    for cfg in django_apps.get_app_configs():
        candidate = Path(cfg.path) / "migrations"
        if candidate.is_dir():
            out[cfg.label] = candidate
    return out
