#!/usr/bin/env python
"""nextgensquash — propose a from-scratch squash of pre-cutoff Django migrations.

Loads every migration on disk, classifies each as old (first committed before
the cutoff) or young, then emits a YAML description of the migration tree that
would result if every old migration were collapsed into one new squash per app.

Cross-app dependencies between old migrations become dependencies between new
squashes; cycles in the proposed graph are flagged (they need deferred-FK
splits to resolve). RunPython operations are dropped — their source migrations
are listed in the output so they can be re-inlined later if a fresh DB needs
the data state they produced.

This is a v1 sketch. It does not emit actual squash files — only the YAML
description of the tree that would result.
"""

from __future__ import annotations

import os
import re
import sys
import argparse
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml
import networkx as nx

REPO_ROOT = Path(__file__).resolve().parent.parent

# Django bootstrap — must run before any django.* import. Tool entrypoint, not a
# library, so keeping the setup at module scope (with E402 noqa) is cleaner than
# burying lazy imports inside functions.
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import django  # noqa: E402

django.setup()

from django.db import migrations as dj_migrations  # noqa: E402
from django.db.migrations.loader import MigrationLoader  # noqa: E402
from django.db.migrations.state import ProjectState  # noqa: E402
from django.db.migrations.writer import MigrationWriter  # noqa: E402

from common.migration_utils import get_managed_app_names  # noqa: E402

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


@dataclass
class DroppedRunPython:
    from_migration: MigrationRef
    callable_name: str


@dataclass
class ProposedSquash:
    app: str
    name: str
    replaces: list[MigrationRef]
    dependencies: list[MigrationRef]
    op_counts: dict[str, int]
    dropped_runpythons: list[DroppedRunPython]


class Squasher:
    """Plans a new migration tree given an old/young partition."""

    def __init__(self, tree: MigrationTree, cutoff: date, include_prior_squashes: bool = True):
        self.tree = tree
        self.cutoff = cutoff
        # Dated name matches `Emitter.INITIAL_NAME` — same value, different
        # entry point (plan/preview vs actual file emission).
        self.SQUASH_NAME = f"0001_squash_{cutoff.isoformat().replace('-', '_')}_initial"
        self.include_prior_squashes = include_prior_squashes
        self.old, self.young = tree.partition(cutoff, include_prior_squashes=include_prior_squashes)
        self.old_keys = set(self.old.keys())
        self.migration_graph = self._build_migration_graph()
        self.app_graph = self._build_app_graph()
        self.squashes = self._plan_squashes()

    def _build_migration_graph(self) -> nx.DiGraph:
        """Migration-level DAG over the old set. Edges point from dependent to dependency."""
        g: nx.DiGraph = nx.DiGraph()
        for m in self.old.values():
            g.add_node(m.ref.key, app=m.ref.app)
            for dep in m.dependencies:
                if dep.key in self.old_keys:
                    g.add_edge(m.ref.key, dep.key)
        return g

    def _build_app_graph(self) -> nx.DiGraph:
        """App-level condensation of the migration graph. Cycles here = cycles between apps."""
        g: nx.DiGraph = nx.DiGraph()
        for m in self.old.values():
            g.add_node(m.ref.app)
            for dep in m.dependencies:
                if dep.app != m.ref.app and dep.key in self.old_keys:
                    g.add_edge(m.ref.app, dep.app)
        return g

    def _plan_one(self, app: str, migs: list[Migration]) -> ProposedSquash:
        deps_apps: set[str] = set()
        op_counts: dict[str, int] = defaultdict(int)
        dropped: list[DroppedRunPython] = []
        replaces: list[MigrationRef] = []

        for m in migs:
            replaces.append(m.ref)
            # Transitively claim any old squash's already-folded members so the
            # new squash represents the full historical name set.
            replaces.extend(m.replaces)
            for dep in m.dependencies:
                if dep.app != app and dep.key in self.old_keys:
                    deps_apps.add(dep.app)
            for op in m.operations:
                op_counts[op.kind] += 1
                if op.kind in DROP_OP_KINDS:
                    dropped.append(
                        DroppedRunPython(
                            from_migration=m.ref,
                            callable_name=op.target or "<unknown>",
                        )
                    )

        return ProposedSquash(
            app=app,
            name=self.SQUASH_NAME,
            replaces=replaces,
            dependencies=[MigrationRef(a, self.SQUASH_NAME) for a in sorted(deps_apps)],
            op_counts=dict(op_counts),
            dropped_runpythons=dropped,
        )

    def _plan_squashes(self) -> list[ProposedSquash]:
        return [self._plan_one(app, migs) for app, migs in sorted(MigrationTree.group_by_app(self.old).items())]

    def cross_app_edges(self) -> list[tuple[MigrationRef, MigrationRef]]:
        """Every (from_old, to_old) cross-app edge in the old set."""
        out: list[tuple[MigrationRef, MigrationRef]] = []
        for (frm_app, frm_name), (to_app, to_name) in self.migration_graph.edges:
            if frm_app != to_app:
                out.append((MigrationRef(frm_app, frm_name), MigrationRef(to_app, to_name)))
        out.sort(key=lambda pair: (pair[0].app, pair[0].name))
        return out

    def app_cycles(self) -> list[list[str]]:
        """SCCs with > 1 app, or single-app SCCs that contain a self-loop."""
        sccs: list[list[str]] = []
        for component in nx.strongly_connected_components(self.app_graph):
            comp = sorted(component)
            if len(comp) > 1 or self.app_graph.has_edge(comp[0], comp[0]):
                sccs.append(comp)
        return sccs

    def edges_inside_cycle(self, scc: list[str]) -> list[tuple[MigrationRef, MigrationRef]]:
        members = set(scc)
        return [(frm, to) for frm, to in self.cross_app_edges() if frm.app in members and to.app in members]

    @staticmethod
    def suggest_cut(edges: list[tuple[MigrationRef, MigrationRef]]) -> dict[str, Any]:
        """Pick the smallest direction-counted set of edges to defer to break the cycle.

        Real squashing would compute the minimum edge feedback set on the underlying FK
        graph, but for a v1 sketch the per-direction tally is the right shape: each cross-
        app edge corresponds to one or more cross-app FKs that the deferring squash would
        push into a follow-up "finalize FKs" migration.
        """
        per_direction: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        for frm, to in edges:
            per_direction[(frm.app, to.app)].append({"from": str(frm), "to": str(to)})
        if not per_direction:
            return {}
        smallest = min(per_direction, key=lambda k: len(per_direction[k]))
        return {
            "defer_direction": {"from_app": smallest[0], "to_app": smallest[1]},
            "edges_to_defer": per_direction[smallest],
            "edge_counts_by_direction": {f"{f}->{t}": len(v) for (f, t), v in sorted(per_direction.items())},
        }

    def app_topological_order(self) -> list[str]:
        """Apply order (parents first) over the app graph with cycles condensed."""
        # Edges in app_graph point dependent→dependency. Reverse to get apply order
        # (dependency→dependent) before condensation + topo sort.
        condensed = nx.condensation(self.app_graph.reverse())
        scc_order = list(nx.topological_sort(condensed))
        out: list[str] = []
        for scc_idx in scc_order:
            out.extend(sorted(condensed.nodes[scc_idx]["members"]))
        return out

    def young_referencing_old_modules(self) -> list[dict[str, Any]]:
        """Young migrations whose source imports a dotted path into a soon-squashed module."""
        old_module_prefixes = sorted(
            {f"{m.ref.app}.migrations.{m.ref.name}" for m in self.old.values()},
            key=len,
            reverse=True,
        )
        findings: list[dict[str, Any]] = []
        for m in self.young.values():
            try:
                src = m.file_path.read_text()
            except OSError:
                continue
            for prefix in old_module_prefixes:
                if prefix in src:
                    findings.append({"young": str(m.ref), "references": prefix})
                    break
        return findings


class TreeRenderer:
    """Builds the nested dict that becomes the YAML output."""

    def __init__(self, squasher: Squasher):
        self.squasher = squasher

    @staticmethod
    def _render_cycle(squasher: Squasher, scc: list[str]) -> dict[str, Any]:
        edges = squasher.edges_inside_cycle(scc)
        return {
            "apps": scc,
            "edge_count": len(edges),
            "edges": [{"from": str(frm), "to": str(to)} for frm, to in edges],
            "suggested_cut": Squasher.suggest_cut(edges),
        }

    @staticmethod
    def _render_squash(sq: ProposedSquash) -> dict[str, Any]:
        return {
            "name": sq.name,
            "dependencies": [str(d) for d in sq.dependencies],
            "operation_counts": dict(sorted(sq.op_counts.items())),
            "replaces_count": len(sq.replaces),
            "dropped_runpython_count": len(sq.dropped_runpythons),
            "replaces": [r.name for r in sq.replaces],
            "dropped_runpythons": [
                {"from": str(d.from_migration), "callable": d.callable_name} for d in sq.dropped_runpythons
            ],
        }

    def render(self) -> dict[str, Any]:
        s = self.squasher
        cycles = s.app_cycles()
        young_refs = s.young_referencing_old_modules()
        cross_app_edges = s.cross_app_edges()
        topo_order = s.app_topological_order()

        squashes_by_app = {sq.app: sq for sq in s.squashes}
        old_by_app = MigrationTree.group_by_app(s.old)
        young_by_app = MigrationTree.group_by_app(s.young)
        all_apps = sorted(set(old_by_app) | set(young_by_app))

        apps_out: dict[str, Any] = {}
        total_dropped = 0
        for app in all_apps:
            sq = squashes_by_app.get(app)
            apps_out[app] = {
                "counts": {
                    "old": len(old_by_app.get(app, [])),
                    "young": len(young_by_app.get(app, [])),
                },
                "proposed_squash": self._render_squash(sq) if sq else None,
            }
            if sq:
                total_dropped += len(sq.dropped_runpythons)

        return {
            "cutoff": s.cutoff.isoformat(),
            "summary": {
                "total_migrations": len(s.tree.migrations),
                "old_count": len(s.old),
                "young_count": len(s.young),
                "new_squashes": len(s.squashes),
                "cross_app_edges": len(cross_app_edges),
                "cycles_detected": len(cycles),
                "dropped_runpythons": total_dropped,
                "young_referencing_old_modules": len(young_refs),
            },
            "apps": apps_out,
            "app_topological_order": topo_order,
            "cycles": [self._render_cycle(s, cyc) for cyc in cycles],
            "cross_app_edges": [{"from": str(frm), "to": str(to)} for frm, to in cross_app_edges],
            "young_referencing_old_modules": young_refs,
        }


class Snapshotter:
    """Builds the ProjectState representing all old migrations applied."""

    def __init__(self, squasher: Squasher):
        self.squasher = squasher

    def latest_old_per_app(self) -> dict[str, str]:
        """For each app with old migrations, the alphabetically-last (= numerically last) name."""
        out: dict[str, str] = {}
        for m in self.squasher.old.values():
            cur = out.get(m.ref.app)
            if cur is None or m.ref.name > cur:
                out[m.ref.app] = m.ref.name
        return out

    def final_state(self) -> ProjectState:
        """ProjectState after applying all old migrations from all apps."""
        loader = MigrationLoader(connection=None, ignore_no_migrations=True)
        targets = list(self.latest_old_per_app().items())
        state = loader.project_state(targets, at_end=True)
        # `loader.project_state` produces ModelStates whose `options` may lack the
        # 'indexes'/'constraints' keys that downstream Django code expects.
        # Normalize here so CreateModel(...) and MigrationWriter both behave.
        for ms in state.models.values():
            ms.options.setdefault("indexes", [])
            ms.options.setdefault("constraints", [])
        return state


@dataclass
class SquashFile:
    app: str
    name: str
    operations: list[Any]
    dependencies: list[tuple[str, str]]
    replaces: list[tuple[str, str]]
    atomic: bool = True


@dataclass(frozen=True)
class FKField:
    """A concrete cross-app foreign-key field in the final state."""

    from_app: str
    from_model: str  # lowercase
    field_name: str
    to_app: str
    to_model: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.from_app, self.from_model, self.field_name)


class CycleBreaker:
    """Final-state FK cycle analysis at the field level.

    Walks every model in `state`, collects each cross-app FK field, picks a
    topological order over the apps that minimizes deferred edges, and exposes
    the resulting "defer this field" set.
    """

    def __init__(self, state: ProjectState):
        self.state = state
        self.all_fks: list[FKField] = self._collect_cross_app_fks(state)
        self._app_graph = self._build_app_graph(self.all_fks)
        self.cycle_apps: set[str] = self._compute_cycle_apps(self._app_graph)
        self.apply_order: list[str] = self._compute_apply_order(self._app_graph, self.all_fks)
        self.deferred: set[FKField] = self._compute_deferred(self.all_fks, self.apply_order)
        # Intra-app FK cycles (e.g. team ↔ user ↔ organization in posthog). Same
        # treatment as cross-app: pick an ordering, defer back-edge fields,
        # AddField them later in finalize_fks.
        self.deferred |= self._compute_intra_app_deferred(state)

    @staticmethod
    def _collect_cross_app_fks(state: ProjectState) -> list[FKField]:
        out: list[FKField] = []
        for (app, model_name), ms in state.models.items():
            for field_name, field in ms.fields.items():
                remote = getattr(field, "remote_field", None)
                if remote is None:
                    continue
                target = getattr(remote, "model", None)
                t_app, t_model = CycleBreaker._target_app_and_model(target)
                if not t_app or t_app == app:
                    continue
                out.append(FKField(app, model_name, field_name, t_app, t_model))
        return out

    @staticmethod
    def _target_app_and_model(ref: Any) -> tuple[str, str]:
        if isinstance(ref, str):
            # `settings.AUTH_USER_MODEL` and similar swappable references resolve
            # to e.g. "posthog.user" at migrate time. Match them here too.
            if ref.startswith("settings."):
                from django.conf import settings as dj_settings

                attr = ref.split(".", 1)[1]
                resolved = getattr(dj_settings, attr, None)
                if isinstance(resolved, str):
                    ref = resolved
            if "." in ref:
                a, m = ref.split(".", 1)
                return a.lower(), m.lower()
        meta = getattr(ref, "_meta", None)
        if meta is not None:
            return meta.app_label.lower(), meta.model_name.lower()
        return "", ""

    @staticmethod
    def _build_app_graph(fks: list[FKField]) -> nx.DiGraph:
        # Edges in apply-order direction: parent_app -> dependent_app
        # (an FK on dependent.X points at parent.Y, so parent must apply first).
        g: nx.DiGraph = nx.DiGraph()
        for fk in fks:
            g.add_edge(fk.to_app, fk.from_app)
        return g

    @staticmethod
    def _compute_cycle_apps(app_graph: nx.DiGraph) -> set[str]:
        out: set[str] = set()
        for comp in nx.strongly_connected_components(app_graph):
            if len(comp) > 1:
                out.update(comp)
        return out

    @staticmethod
    def _compute_apply_order(app_graph: nx.DiGraph, fks: list[FKField]) -> list[str]:
        """Topo over the condensation of `app_graph`; orderings within each SCC
        are picked to minimize the *number of deferred FK fields* (not edges)."""
        # Per-direction FK counts: (to_app, from_app) -> #fks. The app graph has
        # edges to->from (apply order), so this is the natural weight.
        weights: dict[tuple[str, str], int] = defaultdict(int)
        for fk in fks:
            weights[(fk.to_app, fk.from_app)] += 1

        condensed = nx.condensation(app_graph)
        order: list[str] = []
        for scc_idx in nx.topological_sort(condensed):
            members = sorted(condensed.nodes[scc_idx]["members"])
            if len(members) <= 1:
                order.extend(members)
                continue
            order.extend(CycleBreaker._best_inner_order(members, weights))
        return order

    @staticmethod
    def _best_inner_order(members: list[str], weights: dict[tuple[str, str], int]) -> list[str]:
        import itertools

        best: list[str] = members
        best_cost = float("inf")
        for perm in itertools.permutations(members):
            pos = {n: i for i, n in enumerate(perm)}
            cost = sum(w for (u, v), w in weights.items() if u in pos and v in pos and pos[u] > pos[v])
            if cost < best_cost:
                best_cost = cost
                best = list(perm)
        return best

    def _compute_intra_app_deferred(self, state: ProjectState) -> set[FKField]:
        """Per app, find intra-app FK cycles and defer back-edge fields.

        We never want our hand-built CreateModel order to reference a model that
        hasn't been created yet within the same migration's batch. For each
        app's intra-app FK graph, find SCCs and choose a per-SCC model ordering
        that minimizes the number of fields we have to lift into finalize_fks.
        """
        intra_fks_by_app: dict[str, list[FKField]] = defaultdict(list)
        for (app, model_name), ms in state.models.items():
            for fname, field in ms.fields.items():
                remote = getattr(field, "remote_field", None)
                if remote is None:
                    continue
                # The model-target (FK or M2M 'other side').
                t_app, t_model = self._target_app_and_model(getattr(remote, "model", None))
                if t_app == app and t_model and t_model != model_name:
                    intra_fks_by_app[app].append(FKField(app, model_name, fname, t_app, t_model))
                # The M2M through-table model (when explicit).
                through = getattr(remote, "through", None)
                if through is not None:
                    th_app, th_model = self._target_app_and_model(through)
                    if th_app == app and th_model and th_model != model_name:
                        intra_fks_by_app[app].append(FKField(app, model_name, fname, th_app, th_model))

        out: set[FKField] = set()
        for _app, fks in intra_fks_by_app.items():
            g: nx.DiGraph = nx.DiGraph()
            for fk in fks:
                g.add_edge(fk.to_model, fk.from_model)
            for scc in nx.strongly_connected_components(g):
                comp = sorted(scc)
                if len(comp) <= 1:
                    continue
                weights: dict[tuple[str, str], int] = defaultdict(int)
                for fk in fks:
                    if fk.from_model in scc and fk.to_model in scc:
                        weights[(fk.to_model, fk.from_model)] += 1
                inner_order = self._best_inner_order(comp, weights)
                pos = {n: i for i, n in enumerate(inner_order)}
                for fk in fks:
                    if fk.from_model in pos and fk.to_model in pos:
                        if pos[fk.to_model] >= pos[fk.from_model]:
                            out.add(fk)
        return out

    def _compute_deferred(self, fks: list[FKField], apply_order: list[str]) -> set[FKField]:
        pos = {a: i for i, a in enumerate(apply_order)}
        # An FK `from_app.X -> to_app.Y` works iff to_app applies before from_app.
        # to_app applies before from_app iff pos[to_app] < pos[from_app].
        # So an FK is "forward" (no defer) when pos[to_app] < pos[from_app].
        # Otherwise it's a back edge -> defer.
        return {fk for fk in fks if fk.to_app in pos and fk.from_app in pos and pos[fk.to_app] >= pos[fk.from_app]}

    def deferred_for_app(self, app: str) -> list[FKField]:
        return [fk for fk in self.deferred if fk.from_app == app]

    def deferred_field_keys_for_app(self, app: str) -> set[tuple[str, str]]:
        """{(model_name, field_name)} that this app's CreateModel should skip."""
        return {(fk.from_model, fk.field_name) for fk in self.deferred_for_app(app)}

    def cycle_break_edges(self, squasher: Squasher) -> list[tuple[str, str, str, str]]:
        """The specific `(from_app, from_name) -> (to_app, to_name)` dependency
        entries on old migrations whose presence creates the multi-app dep cycle.

        For each cross-app dep in the old set, if our chosen apply order puts
        `to_app` *after* `from_app`, that dep is a back edge — its redirect would
        carry into our squash and close a cycle. The fix is to remove *just that
        dependency entry* from the source file (leaving the file otherwise
        intact). Git restores it on uninstall.

        Returns a list of 4-tuples: (from_app, from_name, to_app, to_name).
        """
        pos = {a: i for i, a in enumerate(self.apply_order)}
        out: list[tuple[str, str, str, str]] = []
        for m in squasher.old.values():
            for dep in m.dependencies:
                if dep.app == m.ref.app:
                    continue
                if dep.app not in pos or m.ref.app not in pos:
                    continue
                if pos[dep.app] > pos[m.ref.app]:
                    out.append((m.ref.app, m.ref.name, dep.app, dep.name))
        return sorted(set(out))


class Emitter:
    """Produces SquashFile(s) for a single app from the final state.

    Returns either:
      - one SquashFile (0001_squashed_initial) for apps with no deferred FKs, or
      - two SquashFiles (0001_squashed_initial + 0002_finalize_fks) for apps
        that need to defer outgoing FKs to break a cross-app cycle.
    """

    # Stable across phases — content is just extensions + standalone early
    # models (both content-stable). Reused unchanged by stacked squashes.
    STUB_NAME = "0000_squash_stub"

    @property
    def _date_token(self) -> str:
        # Date suffix encodes the cutoff so layered phases never collide on
        # disk and grep-by-name reveals which phase produced a file.
        return self.squasher.cutoff.isoformat().replace("-", "_")

    @property
    def INITIAL_NAME(self) -> str:
        return f"0001_squash_{self._date_token}_initial"

    @property
    def FINALIZE_NAME(self) -> str:
        return f"0002_squash_{self._date_token}_finalize_fks"

    @property
    def SCHEMA_ADDONS_NAME(self) -> str:
        return f"0003_squash_{self._date_token}_schema_addons"

    # RunSQL ops in claimed migrations sometimes create indexes that aren't
    # declared in `Meta.indexes` (partial WHERE clauses, GIN with custom
    # opclasses, UNIQUE CONCURRENTLY). Our `CreateModel(options=...)` only
    # carries Meta.indexes, so these get dropped on the floor. Phase A forwards
    # the surviving RunSQL CREATE INDEX ops into a follow-up squash migration.
    _CREATE_INDEX_RE = re.compile(
        r'CREATE\s+(?:UNIQUE\s+)?INDEX(?:\s+CONCURRENTLY)?(?:\s+IF\s+NOT\s+EXISTS)?\s+"?([a-zA-Z0-9_]+)"?\s+ON\s+(?:public\.)?"?([a-zA-Z0-9_]+)"?',
        re.IGNORECASE,
    )
    _DROP_INDEX_RE = re.compile(
        r'DROP\s+INDEX(?:\s+CONCURRENTLY)?(?:\s+IF\s+EXISTS)?\s+"?([a-zA-Z0-9_]+)"?',
        re.IGNORECASE,
    )

    # Standalone (no FK in/out) models that must be created in the stub so they
    # exist before any other migration runs. Mostly to dodge races against work
    # that bin/migrate kicks off in parallel with `manage.py migrate` (e.g.
    # `migrate_clickhouse` reads `posthog_instancesetting` via get_instance_setting()).
    # Lowercase model names, per ModelState.name.lower().
    EARLY_MODELS_BY_APP: dict[str, frozenset[str]] = {
        "posthog": frozenset({"instancesetting"}),
    }

    # Django built-in apps that don't have squashes in the project but whose models
    # are FK-able. If any model in the current app has an FK to one of these apps,
    # the squash declares ("<app>", "__latest__") explicitly so the dep survives
    # canonical retirement (when replaces=[] is cleared and the ghost chain is gone).
    BUILTIN_FK_APPS: frozenset[str] = frozenset({"auth", "contenttypes"})

    def __init__(
        self,
        state: ProjectState,
        squasher: Squasher,
        app: str,
        cycle_breaker: CycleBreaker,
    ):
        self.state = state
        self.squasher = squasher
        self.app = app
        self.cycle_breaker = cycle_breaker

    def _models_in_app(self) -> list[Any]:
        return [ms for (app, _), ms in self.state.models.items() if app == self.app]

    def _create_model_op(self, ms: Any, skip_fields: set[str]) -> tuple[Any, list[Any], list[Any]]:
        """Build a CreateModel that omits `skip_fields` plus any index/constraint
        referencing those fields. Return the CreateModel plus deferred indexes
        and constraints to be re-added in finalize_fks.
        """
        fields = [(name, field) for name, field in ms.fields.items() if name not in skip_fields]
        options = dict(ms.options)

        all_indexes = options.get("indexes") or []
        kept_indexes: list[Any] = []
        deferred_indexes: list[Any] = []
        for idx in all_indexes:
            if self._index_or_constraint_references(idx, skip_fields):
                deferred_indexes.append(idx)
            else:
                kept_indexes.append(idx)
        if all_indexes:
            options["indexes"] = kept_indexes

        all_constraints = options.get("constraints") or []
        kept_constraints: list[Any] = []
        deferred_constraints: list[Any] = []
        for c in all_constraints:
            if self._index_or_constraint_references(c, skip_fields):
                deferred_constraints.append(c)
            else:
                kept_constraints.append(c)
        if all_constraints:
            options["constraints"] = kept_constraints
        # unique_together / index_together also tolerate field lists. Strip any
        # tuple that touches a deferred field. (We don't re-add these in
        # finalize_fks — the test workload doesn't depend on them post-cycle.)
        for legacy_key in ("unique_together", "index_together"):
            legacy = options.get(legacy_key)
            if not legacy:
                continue
            filtered = {tuple(t) for t in legacy if not any(f in skip_fields for f in t)}
            if filtered:
                options[legacy_key] = filtered
            else:
                options.pop(legacy_key, None)

        create = dj_migrations.CreateModel(
            name=ms.name,
            fields=fields,
            options=options,
            bases=ms.bases,
            managers=ms.managers,
        )
        return create, deferred_indexes, deferred_constraints

    @staticmethod
    def _index_or_constraint_references(thing: Any, field_names: set[str]) -> bool:
        """True iff the index/constraint mentions any of the `field_names`.

        Catches: .fields lists; CheckConstraint .condition / .check Q objects
        (including nested `field__lookup` references); UniqueConstraint
        .expressions. Match style for the Q repr is `'<field>'` or
        `'<field>__lookup'`.

        Also catches `<field>_id` style references — Django's idiomatic way to
        reference an FK's underlying column in indexes (`fields=["team_id"]`
        for an FK named `team`). Without this, an index on the deferred FK's
        column gets kept in `Meta.indexes` and Django tries to materialize it
        before the field is added in finalize_fks.
        """
        # Expand each deferred FK field name to also cover its `_id` column form.
        expanded = set(field_names)
        for f in field_names:
            expanded.add(f"{f}_id")

        fields = getattr(thing, "fields", None)
        if fields:
            for f in fields:
                if f.lstrip("-+") in expanded:
                    return True
        for attr in ("condition", "check", "expressions"):
            val = getattr(thing, attr, None)
            if val is None:
                continue
            text = repr(val)
            for f in expanded:
                pat = re.compile(r"['\"]" + re.escape(f) + r"(?:__|['\"])")
                if pat.search(text):
                    return True
                if f"F({f!r})" in text:
                    return True
        return False

    def _intra_app_fk_targets(self, ms: Any, skip_fields: set[str]) -> set[str]:
        """Return lowercase intra-app model names referenced by `ms`:
        - FK targets (`remote_field.model`)
        - M2M intermediate models (`remote_field.through`)
        - Base classes (`bases` for proxy / multi-table inheritance)
        All have to be created before `ms`'s `CreateModel` runs.
        """
        targets: set[str] = set()
        for fname, field in ms.fields.items():
            if fname in skip_fields:
                continue
            remote = getattr(field, "remote_field", None)
            if remote is None:
                continue
            t_app, t_model = CycleBreaker._target_app_and_model(getattr(remote, "model", None))
            if t_app == self.app and t_model and t_model != ms.name.lower():
                targets.add(t_model)
            through = getattr(remote, "through", None)
            if through is not None:
                t_app, t_model = CycleBreaker._target_app_and_model(through)
                if t_app == self.app and t_model and t_model != ms.name.lower():
                    targets.add(t_model)
        for base in ms.bases or ():
            b_app, b_model = CycleBreaker._target_app_and_model(base)
            if b_app == self.app and b_model and b_model != ms.name.lower():
                targets.add(b_model)
        return targets

    def _sort_models_topologically(self, models: list[Any], skip_fields_by_model: dict[str, set[str]]) -> list[Any]:
        by_name = {ms.name.lower(): ms for ms in models}
        graph: nx.DiGraph = nx.DiGraph()
        for ms in models:
            mname = ms.name.lower()
            graph.add_node(mname)
            skip = skip_fields_by_model.get(mname, set())
            for tgt in self._intra_app_fk_targets(ms, skip):
                if tgt in by_name:
                    graph.add_edge(tgt, mname)
        try:
            order = list(nx.topological_sort(graph))
        except nx.NetworkXUnfeasible:
            order = sorted(by_name)
        return [by_name[n] for n in order]

    def _cross_app_dependencies(self, skip_fields_by_model: dict[str, set[str]]) -> list[tuple[str, str]]:
        """Declare deps on foreign apps that this app's models reach via FK.

        - In-project foreign apps: dep on their latest-old (claimed) migration name,
          so the post-fold graph still has an edge in the right direction.
        - Django built-in apps (auth, contenttypes) and any other foreign app not
          tracked by the squasher: emit ("<app>", "__latest__") so the dep is
          declared explicitly rather than inherited via the replaces= ghost chain.
          This makes canonical retirement (empty replaces=[]) actually work.
        """
        latest_old = Snapshotter(self.squasher).latest_old_per_app()
        deps: set[tuple[str, str]] = set()
        for ms in self._models_in_app():
            mname = ms.name.lower()
            skip = skip_fields_by_model.get(mname, set())
            for fname, field in ms.fields.items():
                if fname in skip:
                    continue
                remote = getattr(field, "remote_field", None)
                if remote is None:
                    continue
                t_app, _ = CycleBreaker._target_app_and_model(getattr(remote, "model", None))
                if not t_app or t_app == self.app:
                    continue
                if t_app in latest_old:
                    deps.add((t_app, latest_old[t_app]))
                elif t_app in self.BUILTIN_FK_APPS:
                    deps.add((t_app, "__latest__"))
        return sorted(deps)

    def _replaces(self) -> list[tuple[str, str]]:
        """Claim every old migration for this app, including the transitive
        members of any squash already on disk. Install will strip `replaces` from
        those existing squashes so Django sees them as plain migrations — then
        our single fold removes them all from the graph cleanly.
        """
        out: list[tuple[str, str]] = []
        for m in self.squasher.old.values():
            if m.ref.app != self.app:
                continue
            out.append(m.ref.key)
            out.extend(r.key for r in m.replaces)
        return sorted(set(out))

    EXTENSION_OP_NAMES: frozenset[str] = frozenset(
        {
            "TrigramExtension",
            "BtreeGistExtension",
            "BtreeGinExtension",
            "CITextExtension",
            "HStoreExtension",
            "UnaccentExtension",
            "CryptoExtension",
            "CreateExtension",
        }
    )

    def _extension_preamble_ops(self) -> list[Any]:
        """Collect extension-creation operations from claimed migrations.

        These ops (TrigramExtension(), BtreeGistExtension(), CreateExtension('X'),
        and `RunSQL('CREATE EXTENSION …')`) are needed before any model that
        uses them. They live in old migrations our squash claims, but our
        CreateModel emission doesn't carry them over.
        """
        loader = MigrationLoader(connection=None, ignore_no_migrations=True)
        out: list[Any] = []
        seen: set[str] = set()
        for (app, name), m in sorted(loader.graph.nodes.items()):
            if app != self.app:
                continue
            if (app, name) not in {
                r.key for r in [migr.ref for migr in self.squasher.old.values() if migr.ref.app == self.app]
            }:
                continue
            for op in m.operations:
                kind = op.__class__.__name__
                if kind in self.EXTENSION_OP_NAMES:
                    sig = f"{kind}:{getattr(op, 'name', '')}"
                    if sig not in seen:
                        seen.add(sig)
                        out.append(op)
                elif kind == "RunSQL":
                    sql = op.sql if isinstance(op.sql, str) else str(op.sql)
                    if "CREATE EXTENSION" in sql.upper():
                        if sql not in seen:
                            seen.add(sql)
                            out.append(op)
        return out

    @staticmethod
    def _runsql_text(op: Any) -> str:
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

    def _final_state_index_names(self) -> set[str]:
        """Names already produced by final-state CreateModel — index/constraint
        objects in Meta. UniqueConstraints become unique indexes too, so a RunSQL
        re-creating one would fail with `relation already exists`.
        """
        out: set[str] = set()
        for ms in self._models_in_app():
            for collection in ("indexes", "constraints"):
                for thing in ms.options.get(collection) or []:
                    name = getattr(thing, "name", None)
                    if isinstance(name, str):
                        out.add(name)
        return out

    @staticmethod
    def _managed_table_names() -> set[str]:
        """DB table names for every model in INSTALLED_APPS that Django manages.
        Tables for `managed=False` models (posthog_person, posthog_group, etc.
        owned by personhog) are excluded — CREATE INDEX ops targeting them must
        be dropped from the squash output.
        """
        from django.apps import apps as dj_apps

        names: set[str] = set()
        for model in dj_apps.get_models():
            if not model._meta.managed:
                continue
            names.add(model._meta.db_table.lower())
        return names

    @staticmethod
    def _ensure_idempotent_create_index(sql: str) -> str:
        """Rewrite `CREATE INDEX ... ` to `CREATE INDEX IF NOT EXISTS ...` so
        forwarded RunSQL is safe when Django's own CreateModel already produced
        the same index (e.g. auto-named FK indexes, UniqueConstraints).
        """

        def fix(match: re.Match) -> str:
            head, ws, name_lead = match.group(1), match.group(2), match.group(3)
            if re.search(r"\bIF\s+NOT\s+EXISTS\b", head, re.IGNORECASE):
                return match.group(0)
            return f"{head} IF NOT EXISTS{ws}{name_lead}"

        return re.sub(
            r"(CREATE\s+(?:UNIQUE\s+)?INDEX(?:\s+CONCURRENTLY)?(?:\s+IF\s+NOT\s+EXISTS)?)(\s+)(\"?[a-zA-Z_])",
            fix,
            sql,
            flags=re.IGNORECASE,
        )

    def _collect_index_runsql_ops(self) -> list[Any]:
        """Return RunSQL ops from claimed migrations that CREATE indexes the
        final-state Meta doesn't already produce. Apply Create/Drop pair
        cancellation. Extension creates are excluded (handled by the stub).
        Forwarded SQL is rewritten to `CREATE INDEX IF NOT EXISTS` so it
        co-exists with Django's automatic FK indexes.
        """
        meta_index_names = self._final_state_index_names()
        managed_tables = self._managed_table_names()
        loader = MigrationLoader(connection=None, ignore_no_migrations=True)
        claimed_keys = {r.key for r in [migr.ref for migr in self.squasher.old.values() if migr.ref.app == self.app]}

        kept: list[Any | None] = []
        create_position: dict[str, int] = {}

        def walk(ops: list[Any]) -> None:
            for op in ops:
                kind = op.__class__.__name__
                if kind == "RunSQL":
                    sql_text = self._runsql_text(op)
                    if "CREATE EXTENSION" in sql_text.upper():
                        continue  # handled by stub
                    # Skip any RunSQL that mixes table/column DDL with index
                    # creation. Our squash's CreateModel + finalize_fks already
                    # produce those tables and columns from final-state walk;
                    # forwarding a CREATE TABLE / ALTER TABLE here would
                    # collide. We only forward *pure* index work.
                    sql_upper = sql_text.upper()
                    if any(kw in sql_upper for kw in ("CREATE TABLE", "ALTER TABLE", "DROP TABLE")):
                        continue
                    drop_match = self._DROP_INDEX_RE.search(sql_text)
                    if drop_match:
                        idx_name = drop_match.group(1)
                        prior = create_position.pop(idx_name, None)
                        if prior is not None:
                            kept[prior] = None  # cancel the earlier add
                        continue
                    create_match = self._CREATE_INDEX_RE.search(sql_text)
                    if not create_match:
                        continue
                    idx_name, table_name = create_match.group(1), create_match.group(2).lower()
                    if idx_name in meta_index_names:
                        continue  # CreateModel(options=...) already covers it
                    if table_name not in managed_tables:
                        continue  # target table isn't created by our squash (managed=False)
                    # Wrap CREATE INDEX with IF NOT EXISTS so it's safe to run
                    # after a CreateModel that may have auto-created an FK index
                    # with the same name.
                    sql_safe = self._ensure_idempotent_create_index(sql_text)
                    safe_op = dj_migrations.RunSQL(
                        sql=sql_safe,
                        reverse_sql=op.reverse_sql,
                        hints=op.hints,
                    )
                    kept.append(safe_op)
                    create_position[idx_name] = len(kept) - 1
                elif kind == "SeparateDatabaseAndState":
                    walk(list(op.database_operations))

        for (app, name), m in sorted(loader.graph.nodes.items()):
            if app != self.app or (app, name) not in claimed_keys:
                continue
            walk(list(m.operations))

        return [op for op in kept if op is not None]

    def _schema_addons_deps(self, prior_squash: str) -> list[tuple[str, str]]:
        """Deps for 0003_schema_addons: this app's prior squash (initial or
        finalize) plus every other claimed app's *leaf* squash — old RunSQL
        CREATE INDEX often targets tables now owned by a different app (model
        moves), so we depend on the latest squash file in each app. The leaf
        is finalize_fks when the app has cross-app deferred FKs, else initial.
        Picking initial when finalize_fks exists would race: the forwarded
        index could reference a deferred-FK column that finalize_fks hasn't
        added yet.
        """
        deps: set[tuple[str, str]] = {(self.app, prior_squash)}
        date_token = self._date_token
        for app in {m.ref.app for m in self.squasher.old.values()}:
            if app == self.app:
                continue
            # Match the post-emit naming convention; see INITIAL_NAME / FINALIZE_NAME.
            has_finalize = bool(self.cycle_breaker.deferred_for_app(app))
            leaf = f"0002_squash_{date_token}_finalize_fks" if has_finalize else f"0001_squash_{date_token}_initial"
            deps.add((app, leaf))
        return sorted(deps)

    def first_young_in_app(self) -> str | None:
        names = sorted(m.ref.name for m in self.squasher.young.values() if m.ref.app == self.app)
        return names[0] if names else None

    def build(self) -> list[SquashFile]:
        deferred_keys = self.cycle_breaker.deferred_field_keys_for_app(self.app)
        skip_by_model: dict[str, set[str]] = {}
        for model, field in deferred_keys:
            skip_by_model.setdefault(model, set()).add(field)

        early_names = self.EARLY_MODELS_BY_APP.get(self.app, frozenset())
        all_models_by_name = {ms.name.lower(): ms for ms in self._models_in_app()}
        # An "early" model only lands in the stub if it's standalone — no FKs,
        # no inbound references — otherwise we'd have to declare cross-app deps
        # on the stub, which defeats its purpose (the stub owns __first__).
        early_models: list[Any] = []
        for mname in sorted(early_names):
            ms = all_models_by_name.get(mname)
            if ms is None:
                continue
            assert not self._intra_app_fk_targets(ms, set()), (
                f"{self.app}.{mname} is in EARLY_MODELS_BY_APP but references other models; "
                f"only FK-less standalone models are safe to lift into the stub"
            )
            early_models.append(ms)
        early_model_names = {ms.name.lower() for ms in early_models}

        # 0000_squashed_stub: minimal migration that (1) owns __first__ in this
        # app, (2) carries non-model setup ops we'd otherwise lose — PostgreSQL
        # extensions — and (3) creates standalone models that need to exist before
        # the rest of `manage.py migrate` runs (e.g. posthog_instancesetting,
        # read by code firing in parallel from bin/migrate's migrate_clickhouse).
        stub_ops: list[Any] = list(self._extension_preamble_ops())
        for ms in early_models:
            create, _, _ = self._create_model_op(ms, set())
            stub_ops.append(create)
        stub = SquashFile(
            app=self.app,
            name=self.STUB_NAME,
            operations=stub_ops,
            dependencies=[],
            replaces=[],
        )

        rest_models = [ms for ms in self._models_in_app() if ms.name.lower() not in early_model_names]
        models = self._sort_models_topologically(rest_models, skip_by_model)
        initial_ops: list[Any] = []
        deferred_indexes: list[tuple[str, Any]] = []  # (model_name_lower, Index)
        deferred_constraints: list[tuple[str, Any]] = []  # (model_name_lower, Constraint)
        for ms in models:
            skip_fields = skip_by_model.get(ms.name.lower(), set())
            create, idxs, cons = self._create_model_op(ms, skip_fields)
            initial_ops.append(create)
            deferred_indexes.extend((ms.name.lower(), idx) for idx in idxs)
            deferred_constraints.extend((ms.name.lower(), c) for c in cons)
        # Initial's dependencies: stub + cross-app FK targets in the foreign-app
        # latest-old migration. The stub anchor means we're never __first__.
        initial_deps: list[tuple[str, str]] = [(self.app, self.STUB_NAME)]
        initial_deps.extend(self._cross_app_dependencies(skip_by_model))
        initial = SquashFile(
            app=self.app,
            name=self.INITIAL_NAME,
            operations=initial_ops,
            dependencies=initial_deps,
            replaces=self._replaces(),
        )

        # RunSQL-created indexes from claimed migrations (Phase A). Emitted as
        # a separate trailing 0003_schema_addons file — it can exist with or
        # without a 0002_finalize_fks.
        index_runsql_ops = self._collect_index_runsql_ops()

        deferred_fks = self.cycle_breaker.deferred_for_app(self.app)
        if not deferred_fks and not deferred_indexes and not deferred_constraints:
            if not index_runsql_ops:
                return [stub, initial]
            addons = SquashFile(
                app=self.app,
                name=self.SCHEMA_ADDONS_NAME,
                operations=index_runsql_ops,
                dependencies=self._schema_addons_deps(prior_squash=self.INITIAL_NAME),
                replaces=[],
                atomic=False,  # CREATE INDEX CONCURRENTLY can't run inside a transaction
            )
            return [stub, initial, addons]

        # Build a model_name -> ModelState map to look up each field's Field instance.
        models_by_name = {ms.name.lower(): ms for ms in self._models_in_app()}
        addfield_ops: list[Any] = []
        finalize_dep_apps: set[str] = set()
        for fk in deferred_fks:
            ms = models_by_name.get(fk.from_model)
            if ms is None:
                continue
            field = ms.fields.get(fk.field_name)
            if field is None:
                continue
            addfield_ops.append(
                dj_migrations.AddField(
                    model_name=fk.from_model,
                    name=fk.field_name,
                    field=field,
                )
            )
            finalize_dep_apps.add(fk.to_app)
        # Re-add any indexes/constraints we lifted out of the initial CreateModels.
        for model_name, idx in deferred_indexes:
            addfield_ops.append(dj_migrations.AddIndex(model_name=model_name, index=idx))
        for model_name, c in deferred_constraints:
            addfield_ops.append(dj_migrations.AddConstraint(model_name=model_name, constraint=c))

        # finalize_fks depends on this app's initial + every foreign app's
        # initial, so its target tables exist. We deliberately do NOT depend on
        # any young migration: deferred fields are used by young migrations, so
        # finalize_fks must run *before* them. The first-young's deps file gets
        # edited at install time to depend back on finalize_fks (and that gives
        # the chain a single leaf).
        finalize_deps: list[tuple[str, str]] = [(self.app, self.INITIAL_NAME)]
        finalize_deps.extend((a, self.INITIAL_NAME) for a in sorted(finalize_dep_apps))
        finalize = SquashFile(
            app=self.app,
            name=self.FINALIZE_NAME,
            operations=addfield_ops,
            dependencies=finalize_deps,
            replaces=[],
        )
        if not index_runsql_ops:
            return [stub, initial, finalize]
        addons = SquashFile(
            app=self.app,
            name=self.SCHEMA_ADDONS_NAME,
            operations=index_runsql_ops,
            dependencies=self._schema_addons_deps(prior_squash=self.FINALIZE_NAME),
            replaces=[],
            atomic=False,
        )
        return [stub, initial, finalize, addons]


class FileWriter:
    """Serializes SquashFile to a .py file via Django's MigrationWriter."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def write(self, sq: SquashFile) -> Path:
        replaces_local = list(sq.replaces)
        dependencies_local = list(sq.dependencies)
        operations_local = list(sq.operations)

        class GeneratedMigration(dj_migrations.Migration):
            initial = True
            dependencies = dependencies_local
            replaces = replaces_local
            operations = operations_local

        writer = MigrationWriter(GeneratedMigration(sq.name, sq.app))
        path = self.output_dir / sq.app / "migrations" / f"{sq.name}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        text = writer.as_string()
        if not sq.atomic:
            # MigrationWriter doesn't emit `atomic` even when False — inject it.
            text = text.replace("    initial = True\n", "    initial = True\n    atomic = False\n", 1)
        path.write_text(text)
        return path


def _run_plan(args: argparse.Namespace) -> None:
    tree = MigrationTree.load(REPO_ROOT)
    squasher = Squasher(tree, args.cutoff, include_prior_squashes=args.include_prior_squashes)
    rendered = TreeRenderer(squasher).render()
    text = yaml.safe_dump(rendered, sort_keys=False, default_flow_style=False, width=200)
    if args.output:
        args.output.write_text(text)
        sys.stderr.write(f"Wrote {args.output} ({len(text):,} bytes)\n")
    else:
        sys.stdout.write(text)


def _run_emit(args: argparse.Namespace) -> None:
    tree = MigrationTree.load(REPO_ROOT)
    squasher = Squasher(tree, args.cutoff, include_prior_squashes=args.include_prior_squashes)
    state = Snapshotter(squasher).final_state()
    cycle_breaker = CycleBreaker(state)

    sys.stderr.write(
        f"cycle apps: {sorted(cycle_breaker.cycle_apps) or '(none)'}\n"
        f"apply order: {' -> '.join(cycle_breaker.apply_order[:12])}{' ...' if len(cycle_breaker.apply_order) > 12 else ''}\n"
        f"deferred FK fields: {len(cycle_breaker.deferred)}\n"
    )
    for fk in sorted(cycle_breaker.deferred, key=lambda f: (f.from_app, f.from_model, f.field_name)):
        sys.stderr.write(f"  defer  {fk.from_app}.{fk.from_model}.{fk.field_name} -> {fk.to_app}.{fk.to_model}\n")

    # Cross-app dependency entries to surgically remove from old migration files
    # so Django's `replaces` redirect doesn't carry them into our squash.
    cycle_edges = cycle_breaker.cycle_break_edges(squasher)
    if cycle_edges:
        sys.stderr.write(f"\ncycle-break edge removals ({len(cycle_edges)}):\n")
        for frm_app, frm_name, to_app, to_name in cycle_edges:
            sys.stderr.write(f"  rewrite  {frm_app}.{frm_name}: drop dep ({to_app!r}, {to_name!r})\n")

    if args.app:
        apps = [args.app]
    else:
        apps = sorted({m.ref.app for m in squasher.old.values()})

    writer = FileWriter(args.output_dir)
    written: list[Path] = []
    # Retire manifest collected as we emit. Each replaced name maps to its owning
    # app; per-app we record both the pre-finalize leaf (where models are CREATED)
    # and the post-finalize leaf (where deferred FKs / indexes are wired). The
    # retire pass uses pre-finalize for cross-app references and post-finalize
    # for same-app references — using post-finalize cross-app would re-introduce
    # the cycle that finalize_fks itself depends on.
    retire_manifest: dict[str, Any] = {
        "cutoff": args.cutoff.isoformat(),
        "leaves": {},  # app -> post-finalize leaf name
        "initials": {},  # app -> pre-finalize (initial) squash name
        "replaced": {},  # "app/name" -> app  (every name claimed by a squash)
    }
    for app in apps:
        emitter = Emitter(state, squasher, app, cycle_breaker)
        squashes = emitter.build()
        # The initial squash is the second entry in `squashes` (after the stub).
        # If THAT has no operations, the app has no models to squash.
        initial = next((sq for sq in squashes if sq.name == emitter.INITIAL_NAME), None)
        if initial is None or not initial.operations:
            sys.stderr.write(f"skip {app}: no models in final state\n")
            continue
        for sq in squashes:
            path = writer.write(sq)
            written.append(path)
            sys.stderr.write(
                f"wrote {path}  ({len(sq.operations)} ops, replaces {len(sq.replaces)}, deps {len(sq.dependencies)})\n"
            )
        # Manifest entries
        finalize = next((sq for sq in squashes if sq.name == emitter.FINALIZE_NAME), None)
        addons = next((sq for sq in squashes if sq.name == emitter.SCHEMA_ADDONS_NAME), None)
        retire_manifest["initials"][app] = emitter.INITIAL_NAME
        if addons is not None:
            retire_manifest["leaves"][app] = emitter.SCHEMA_ADDONS_NAME
        elif finalize is not None:
            retire_manifest["leaves"][app] = emitter.FINALIZE_NAME
        else:
            retire_manifest["leaves"][app] = emitter.INITIAL_NAME
        for replaced_app, replaced_name in initial.replaces:
            retire_manifest["replaced"][f"{replaced_app}/{replaced_name}"] = replaced_app
    # Save cycle-break edge-removal list as a sidecar for `install` to act on.
    if cycle_edges:
        edges_file = args.output_dir / "CYCLE_EDGE_REMOVALS.txt"
        edges_file.write_text("\n".join(f"{fa}/{fn} -> {ta}/{tn}" for (fa, fn, ta, tn) in cycle_edges) + "\n")
        sys.stderr.write(f"\nwrote cycle-break edge-removal list to {edges_file}\n")

    # Save (app, first_young) entries that need a dep added so the latest
    # squash in the app (finalize_fks and/or schema_addons) runs before any
    # young migration in the same app. The install step looks up the actual
    # leaf via the manifest, so we don't store the squash name here.
    first_young_edits: list[tuple[str, str]] = []
    for app in apps:
        emitter = Emitter(state, squasher, app, cycle_breaker)
        leaf = retire_manifest["leaves"].get(app)
        if leaf in (None, emitter.INITIAL_NAME):
            continue  # plain initial chains in via replaces redirect already
        first_young = emitter.first_young_in_app()
        if first_young:
            first_young_edits.append((app, first_young))
    if first_young_edits:
        adds_file = args.output_dir / "FIRST_YOUNG_DEP_ADDITIONS.txt"
        adds_file.write_text("\n".join(f"{a}/{n}" for (a, n) in first_young_edits) + "\n")
        sys.stderr.write(f"wrote first-young dep-addition list to {adds_file}\n")

    import json as _json

    manifest_path = args.output_dir / "RETIRE_MANIFEST.json"
    manifest_path.write_text(_json.dumps(retire_manifest, indent=2, sort_keys=True) + "\n")
    sys.stderr.write(
        f"wrote retire manifest ({len(retire_manifest['replaced'])} replaced names, "
        f"{len(retire_manifest['leaves'])} apps) to {manifest_path}\n"
    )

    sys.stderr.write(f"\ntotal: {len(written)} files emitted to {args.output_dir}\n")


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

    apps_dirs = _resolve_app_migration_dirs()

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
    if manifest_path.exists():
        import json as _json

        app_leaves = _json.loads(manifest_path.read_text()).get("leaves", {}) or {}

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
        if leaf_name and leaf_name != Emitter.INITIAL_NAME:
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

    apps_dirs = _resolve_app_migration_dirs()

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


def _add_dependency_to_migration(path: Path, dep: tuple[str, str]) -> Path | None:
    """Add `(app, name)` as the first entry inside the migration's
    `dependencies` list. Returns the path if modified, else None.
    """
    import re

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
    import re

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
        if not MigrationTree._PRIOR_SQUASH_RE.search(p.stem):
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
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
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


def _resolve_app_migration_dirs() -> dict[str, Path]:
    """Map app_label -> on-disk migrations directory."""
    from django.apps import apps as django_apps

    out: dict[str, Path] = {}
    for cfg in django_apps.get_app_configs():
        candidate = Path(cfg.path) / "migrations"
        if candidate.is_dir():
            out[cfg.label] = candidate
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    subparsers = parser.add_subparsers(dest="command", required=False)

    def _add_phase_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--cutoff", type=date.fromisoformat, default=DEFAULT_CUTOFF)
        p.add_argument(
            "--include-prior-squashes",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="Treat existing nextgensquash output (stub/initial/finalize_fks/schema_addons) as old "
            "regardless of cutoff date, so a stacked phase-N can fold them into its own replaces list. "
            "Default on. Disable for a clean from-scratch (re-)squash that ignores prior phases.",
        )

    parser_plan = subparsers.add_parser("plan", help="Emit the YAML description of the proposed squash tree.")
    _add_phase_args(parser_plan)
    parser_plan.add_argument("--output", type=Path, default=None)

    parser_emit = subparsers.add_parser("emit", help="Emit real .py migration files for the squashed apps.")
    _add_phase_args(parser_emit)
    parser_emit.add_argument("--output-dir", type=Path, required=True)
    parser_emit.add_argument("--app", default=None, help="Only emit this app (testing).")

    parser_install = subparsers.add_parser("install", help="Copy emitted files into the real migration dirs.")
    parser_install.add_argument("--input-dir", type=Path, required=True)

    parser_uninstall = subparsers.add_parser(
        "uninstall", help="Remove installed squash files; restore max_migration.txt."
    )
    parser_uninstall.add_argument("--input-dir", type=Path, required=True)

    parser_retire = subparsers.add_parser(
        "retire",
        help="Canonical Django retirement: rewrite young-migration deps to squash leaves, "
        "empty replaces=[], and delete the replaced files on disk.",
    )
    parser_retire.add_argument("--input-dir", type=Path, required=True)

    # Backward-compat: bare invocation defaults to `plan`.
    parser.add_argument("--cutoff", type=date.fromisoformat, default=DEFAULT_CUTOFF)
    parser.add_argument("--include-prior-squashes", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    if args.command == "emit":
        _run_emit(args)
    elif args.command == "install":
        _run_install(args)
    elif args.command == "uninstall":
        _run_uninstall(args)
    elif args.command == "retire":
        _run_retire(args)
    else:
        _run_plan(args)


if __name__ == "__main__":
    main()
