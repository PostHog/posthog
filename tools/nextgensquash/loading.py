"""Load every managed migration from disk, date it via git, and partition old vs young at the cutoff."""

from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from django.db.migrations.loader import MigrationLoader  # noqa: E402

from common.migration_utils import get_managed_app_names  # noqa: E402


def _find_repo_root() -> Path:
    return next(p for p in Path(__file__).resolve().parents if (p / "manage.py").exists())


REPO_ROOT = _find_repo_root()

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
    def key(self) -> tuple[str, str]:
        return (self.app, self.name)


@dataclass(frozen=True)
class OpInfo:
    """A migration operation summarized to its class name and a target identifier."""

    kind: str
    target: str | None = None


@dataclass
class Migration:
    ref: MigrationRef
    file_path: Path
    commit_date: date | None
    dependencies: list[MigrationRef]
    replaces: list[MigrationRef]
    operations: list[OpInfo]


def _summarize_op(op: Any) -> OpInfo:
    kind = op.__class__.__name__
    if kind == "RunPython":
        target = getattr(op.code, "__name__", None) or repr(op.code)
        return OpInfo(kind=kind, target=target)
    if kind == "RunSQL":
        return OpInfo(kind=kind, target=None)
    target = getattr(op, "name", None) or getattr(op, "model_name", None)
    return OpInfo(kind=kind, target=target if isinstance(target, str) else None)


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
        roots = [
            repo_root / "posthog" / "migrations",
            repo_root / "posthog" / "rbac" / "migrations",
            repo_root / "ee" / "migrations",
        ]
        products = repo_root / "products"
        if products.is_dir():
            for p in products.iterdir():
                d = p / "backend" / "migrations"
                if d.is_dir():
                    roots.append(d)
        files: list[Path] = []
        for root in roots:
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
        self, cutoff: date, include_prior_squashes: bool = True
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
