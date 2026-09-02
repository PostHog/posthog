"""Plan per-app squashes over the old partition and render the plan YAML."""

from __future__ import annotations

import re
import functools
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

from django.db.migrations.loader import MigrationLoader  # noqa: E402
from django.db.migrations.state import ProjectState  # noqa: E402

import networkx as nx

from . import loading


@dataclass(frozen=False)
class DroppedRunPython:
    from_migration: loading.MigrationRef
    callable_name: str


@dataclass(frozen=False)
class ProposedSquash:
    app: str
    name: str
    replaces: list[loading.MigrationRef]
    dependencies: list[loading.MigrationRef]
    op_counts: dict[str, int]
    dropped_runpythons: list[DroppedRunPython]


class Squasher:
    """Plans a new migration tree given an old/young partition."""

    def __init__(
        self,
        tree: loading.MigrationTree,
        cutoff: date,
        include_prior_squashes: bool = True,
        min_young: int = 3,
    ):
        self.tree = tree
        self.cutoff = cutoff
        # Dated name matches `Emitter.INITIAL_NAME` — same value, different
        # entry point (plan/preview vs actual file emission).
        self.SQUASH_NAME = f"0001_squash_{cutoff.isoformat().replace('-', '_')}_initial"
        self.include_prior_squashes = include_prior_squashes
        self.old, self.young = tree.partition(cutoff, include_prior_squashes=include_prior_squashes)
        self._rebalance_min_young(min_young)
        self._pull_sql_referenced_young()
        self.migration_graph = self._build_migration_graph()
        self.app_graph = self._build_app_graph()
        self.squashes = self._plan_squashes()

    def _rebalance_min_young(self, min_young: int) -> None:
        """Move each app's newest old migrations to young until the app keeps
        `min_young` live migrations after its squash. A pure date cutoff makes
        the squash the tip of every dormant app, claiming names that in-flight
        branches and half-deployed environments still reference. Always keep at
        least the app's first migration folded so every app still squashes and
        the cross-app graph mechanics stay uniform, and never move a prior
        squash file (its replaces set must stay claimed).
        """
        if min_young <= 0:
            return
        young_counts: dict[str, int] = defaultdict(int)
        for m in self.young.values():
            young_counts[m.ref.app] += 1
        # A migration with a cross-app old dependent must stay folded: moving it
        # young leaves a claimed migration depending on a live young node, and
        # that edge weaves a CircularDependencyError through the replaces
        # redirects (seen with the surveys/feature_flags model-move pairs). The
        # date partition itself can never produce such an edge, so the tail
        # rule must not create one either.
        blocked = self._cross_app_depended_keys()
        for app, migs in loading.MigrationTree.group_by_app(self.old).items():
            chain = sorted(migs, key=lambda m: m.ref.name)
            movable = chain[1:]
            need = min_young - young_counts[app]
            for m in reversed(movable):
                if need <= 0:
                    break
                # SeparateDatabaseAndState = a cross-app state move. Its two
                # sides must fold together: splitting a pair across the
                # boundary leaves the model in both apps' snapshots (both
                # initials CREATE the table) or in neither (nothing does).
                is_state_move = any(op.kind == "SeparateDatabaseAndState" for op in m.operations)
                if m.replaces or m.ref.key in blocked or is_state_move:
                    break
                del self.old[m.ref.key]
                self.young[m.ref.key] = m
                need -= 1

    # nosemgrep: tuple-return-prefer-dataclass -- tuples serve as graph and dict keys here
    def _cross_app_depended_keys(self) -> set[tuple[str, str]]:
        """Old migrations that another app's old migration depends on."""
        out: set[tuple[str, str]] = set()
        for m in self.old.values():
            for dep in m.dependencies:
                if dep.app != m.ref.app and dep.key in self.old:
                    out.add(dep.key)
        return out

    # Quoted names may contain spaces ('ADD CONSTRAINT "unique group types for
    # project"'); capture the full quoted name, or a bare identifier.
    _SQL_CREATED_NAME_RES = (
        re.compile(r"ADD\s+CONSTRAINT\s+(?:\"([^\"]+)\"|([a-zA-Z0-9_]+))", re.IGNORECASE),
        re.compile(
            r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?(?:\"([^\"]+)\"|([a-zA-Z0-9_]+))",
            re.IGNORECASE,
        ),
    )
    # Ops whose DDL lives only in database_forwards, referencing a raw-SQL
    # constraint by name (posthog.migration_helpers probe-first helpers).
    _SQL_REFERENCING_OP_KINDS = frozenset({"ValidateConstraint", "ValidateForeignKey"})

    def _pull_sql_referenced_young(self) -> None:
        """Move a folded migration young when a young migration references a
        constraint or index its raw SQL creates. Emit forwards folded RunSQL
        DDL into schema_addons, which runs *after* the young chain — a young
        `ValidateForeignKey` (or RunSQL) naming such an object then fails on a
        fresh database because the object does not exist yet (seen with
        ai_observability 0039/0040). Contiguity: everything after the creator
        in its app moves young with it.
        """
        while True:
            # State-backed names land in the squash snapshot, so the initial
            # creates them and emit never forwards their SQL — no hazard.
            state_backed = {n for m in self.old.values() for op in m.operations for n in op.state_names}
            created: dict[str, loading.Migration] = {}
            for m in self.old.values():
                for op in m.operations:
                    if not op.sql:
                        continue
                    for rx in self._SQL_CREATED_NAME_RES:
                        for quoted, bare in rx.findall(op.sql):
                            name = quoted or bare
                            if name not in state_backed:
                                created[name] = m
            pull: dict[str, str] = {}  # app -> earliest creator name to move
            for y in self.young.values():
                for op in y.operations:
                    names: set[str] = set()
                    if op.kind in self._SQL_REFERENCING_OP_KINDS and op.target:
                        names.add(op.target)
                    if op.sql:
                        # Whole-token match: a bare identifier must not match
                        # inside a longer word or an unrelated name.
                        names.update(n for n in created if re.search(rf"\b{re.escape(n)}\b", op.sql) is not None)
                    for name in names & created.keys():
                        creator = created[name]
                        app = creator.ref.app
                        if app not in pull or creator.ref.name < pull[app]:
                            pull[app] = creator.ref.name
            if not pull:
                return
            blocked = self._cross_app_depended_keys()
            for app, from_name in pull.items():
                chain = sorted(loading.MigrationTree.group_by_app(self.old)[app], key=lambda m: m.ref.name)
                if chain[0].ref.name >= from_name:
                    raise RuntimeError(
                        f"young migration references SQL from {app}.{from_name}, but that is the app's "
                        "root migration and must stay folded — bump the cutoff instead"
                    )
                for m in chain:
                    if m.ref.name < from_name:
                        continue
                    is_state_move = any(op.kind == "SeparateDatabaseAndState" for op in m.operations)
                    if m.replaces or m.ref.key in blocked or is_state_move:
                        raise RuntimeError(
                            f"{m.ref} must move young (a young migration references SQL objects from "
                            f"{app}.{from_name}) but it is pinned folded (prior squash, cross-app old "
                            "dependent, or state move) — bump the cutoff past it instead"
                        )
                    del self.old[m.ref.key]
                    self.young[m.ref.key] = m

    @functools.cached_property
    def latest_old_per_app(self) -> dict[str, str]:
        """For each app with old migrations, the alphabetically-last (= numerically last) name."""
        out: dict[str, str] = {}
        for m in self.old.values():
            cur = out.get(m.ref.app)
            if cur is None or m.ref.name > cur:
                out[m.ref.app] = m.ref.name
        return out

    def _build_migration_graph(self) -> nx.DiGraph:
        """Migration-level DAG over the old set. Edges point from dependent to dependency."""
        g: nx.DiGraph = nx.DiGraph()
        for m in self.old.values():
            g.add_node(m.ref.key, app=m.ref.app)
            for dep in m.dependencies:
                if dep.key in self.old:
                    g.add_edge(m.ref.key, dep.key)
        return g

    def _build_app_graph(self) -> nx.DiGraph:
        """App-level condensation of the migration graph. Cycles here = cycles between apps."""
        g: nx.DiGraph = nx.DiGraph()
        for m in self.old.values():
            g.add_node(m.ref.app)
            for dep in m.dependencies:
                if dep.app != m.ref.app and dep.key in self.old:
                    g.add_edge(m.ref.app, dep.app)
        return g

    def _plan_one(self, app: str, migs: list[loading.Migration]) -> ProposedSquash:
        deps_apps: set[str] = set()
        op_counts: dict[str, int] = defaultdict(int)
        dropped: list[DroppedRunPython] = []
        replaces: list[loading.MigrationRef] = []

        for m in migs:
            replaces.append(m.ref)
            # Transitively claim any old squash's already-folded members so the
            # new squash represents the full historical name set.
            replaces.extend(m.replaces)
            for dep in m.dependencies:
                if dep.app != app and dep.key in self.old:
                    deps_apps.add(dep.app)
            for op in m.operations:
                op_counts[op.kind] += 1
                if op.kind in loading.DROP_OP_KINDS:
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
            dependencies=[loading.MigrationRef(a, self.SQUASH_NAME) for a in sorted(deps_apps)],
            op_counts=dict(op_counts),
            dropped_runpythons=dropped,
        )

    def _plan_squashes(self) -> list[ProposedSquash]:
        return [self._plan_one(app, migs) for app, migs in sorted(loading.MigrationTree.group_by_app(self.old).items())]

    # nosemgrep: tuple-return-prefer-dataclass -- tuples serve as graph and dict keys here
    def cross_app_edges(self) -> list[tuple[loading.MigrationRef, loading.MigrationRef]]:
        """Every (from_old, to_old) cross-app edge in the old set."""
        out: list[tuple[loading.MigrationRef, loading.MigrationRef]] = []
        for (frm_app, frm_name), (to_app, to_name) in self.migration_graph.edges:
            if frm_app != to_app:
                out.append((loading.MigrationRef(frm_app, frm_name), loading.MigrationRef(to_app, to_name)))
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

    # nosemgrep: tuple-return-prefer-dataclass -- tuples serve as graph and dict keys here
    def edges_inside_cycle(self, scc: list[str]) -> list[tuple[loading.MigrationRef, loading.MigrationRef]]:
        members = set(scc)
        return [(frm, to) for frm, to in self.cross_app_edges() if frm.app in members and to.app in members]

    @staticmethod
    def suggest_cut(edges: list[tuple[loading.MigrationRef, loading.MigrationRef]]) -> dict[str, Any]:
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
        old_by_app = loading.MigrationTree.group_by_app(s.old)
        young_by_app = loading.MigrationTree.group_by_app(s.young)
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

    def final_state(self) -> ProjectState:
        """ProjectState after applying all old migrations from all apps."""
        loader = MigrationLoader(connection=None, ignore_no_migrations=True)
        targets = list(self.squasher.latest_old_per_app.items())
        state = loader.project_state(targets, at_end=True)
        # `loader.project_state` produces ModelStates whose `options` may lack the
        # 'indexes'/'constraints' keys that downstream Django code expects.
        # Normalize here so CreateModel(...) and MigrationWriter both behave.
        for ms in state.models.values():
            ms.options.setdefault("indexes", [])
            ms.options.setdefault("constraints", [])
        self._check_single_table_owner(state)
        return state

    @staticmethod
    def _check_single_table_owner(state: ProjectState) -> None:
        """Fail when two managed models in the snapshot map to one table.

        A split SeparateDatabaseAndState pair leaves a moved model in both the
        giving and the receiving app's snapshot, and both initial squashes then
        CREATE the same table — a fresh migrate dies on `relation already
        exists` minutes in. Catch it at emit time instead.
        """
        owners: dict[str, tuple[str, str]] = {}
        for (app_label, model_name), ms in state.models.items():
            if not ms.options.get("managed", True) or ms.options.get("proxy", False):
                continue
            table = ms.options.get("db_table") or f"{app_label}_{model_name}"
            prior = owners.setdefault(table, (app_label, model_name))
            if prior != (app_label, model_name):
                raise RuntimeError(
                    f"table {table!r} is owned by both {prior[0]}.{prior[1]} and "
                    f"{app_label}.{model_name} in the snapshot state — a state-move "
                    "pair was split across the old/young boundary"
                )
