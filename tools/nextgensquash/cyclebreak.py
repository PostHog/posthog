"""Field-level FK cycle analysis over the final state: apply order and the deferred-FK set."""

from __future__ import annotations

import itertools
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from django.db.migrations.state import ProjectState  # noqa: E402

import networkx as nx

from . import planning


@dataclass(frozen=True)
class FKField:
    """A concrete cross-app foreign-key field in the final state."""

    from_app: str
    from_model: str  # lowercase
    field_name: str
    to_app: str
    to_model: str
    # False for MTI parent links and primary-key FKs: lifting one into
    # finalize_fks would leave the CreateModel without a primary key, so these
    # may never defer — the apply order must place their target first.
    deferrable: bool = True

    @property
    # nosemgrep: tuple-return-prefer-dataclass -- tuples serve as graph and dict keys here
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
    def _is_deferrable(field: Any) -> bool:
        remote = getattr(field, "remote_field", None)
        if getattr(field, "primary_key", False):
            return False
        if remote is not None and getattr(remote, "parent_link", False):
            return False
        return True

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
                out.append(
                    FKField(app, model_name, field_name, t_app, t_model, deferrable=CycleBreaker._is_deferrable(field))
                )
        return out

    @staticmethod
    # nosemgrep: tuple-return-prefer-dataclass -- tuples serve as graph and dict keys here
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
        # Non-deferrable edges (MTI parent links) get a weight no combination of
        # ordinary edges can outvote, so the ordering always honors them.
        weights: dict[tuple[str, str], int] = defaultdict(int)
        for fk in fks:
            weights[(fk.to_app, fk.from_app)] += 1 if fk.deferrable else 1_000_000

        condensed = nx.condensation(app_graph)
        order: list[str] = []
        for scc_idx in nx.topological_sort(condensed):
            members = sorted(condensed.nodes[scc_idx]["members"])
            if len(members) <= 1:
                order.extend(members)
                continue
            order.extend(CycleBreaker._best_inner_order(members, weights))
        return order

    # Exhaustive permutation search is factorial; beyond this SCC size, fall
    # back to the greedy heuristic. The FK-level app SCC hit 21 members in
    # Aug 2026, where exhaustive search does not return.
    _EXACT_ORDER_LIMIT = 8

    @staticmethod
    def _order_cost(seq: list[str], weights: dict[tuple[str, str], int]) -> int:
        pos = {n: i for i, n in enumerate(seq)}
        return sum(w for (u, v), w in weights.items() if u in pos and v in pos and pos[u] > pos[v])

    @staticmethod
    def _best_inner_order(members: list[str], weights: dict[tuple[str, str], int]) -> list[str]:
        if len(members) <= CycleBreaker._EXACT_ORDER_LIMIT:
            best: list[str] = members
            best_cost = float("inf")
            for perm in itertools.permutations(members):
                cost = CycleBreaker._order_cost(list(perm), weights)
                if cost < best_cost:
                    best_cost = cost
                    best = list(perm)
            return best
        return CycleBreaker._greedy_inner_order(members, weights)

    @staticmethod
    def _greedy_inner_order(members: list[str], weights: dict[tuple[str, str], int]) -> list[str]:
        """Weighted feedback-arc heuristic: place the node whose pending inbound
        weight (edges that would become back edges) minus outbound weight is
        smallest, then refine with adjacent swaps. Deterministic via name
        tiebreak. Order quality only affects how many FK fields get deferred to
        finalize_fks, never correctness."""
        remaining = set(members)
        order: list[str] = []
        while remaining:
            # nosemgrep: tuple-return-prefer-dataclass -- tuples serve as graph and dict keys here
            def placement_cost(n: str) -> tuple[int, int, str]:
                in_w = sum(w for (u, v), w in weights.items() if v == n and u != n and u in remaining)
                out_w = sum(w for (u, v), w in weights.items() if u == n and v != n and v in remaining)
                return (in_w - out_w, in_w, n)

            nxt = min(remaining, key=placement_cost)
            order.append(nxt)
            remaining.remove(nxt)

        for _ in range(len(order) ** 2):
            improved = False
            for i in range(len(order) - 1):
                cand = [*order[:i], order[i + 1], order[i], *order[i + 2 :]]
                if CycleBreaker._order_cost(cand, weights) < CycleBreaker._order_cost(order, weights):
                    order = cand
                    improved = True
            if not improved:
                break
        return order

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
                deferrable = self._is_deferrable(field)
                # The model-target (FK or M2M 'other side').
                t_app, t_model = self._target_app_and_model(getattr(remote, "model", None))
                if t_app == app and t_model and t_model != model_name:
                    intra_fks_by_app[app].append(FKField(app, model_name, fname, t_app, t_model, deferrable=deferrable))
                # The M2M through-table model (when explicit).
                through = getattr(remote, "through", None)
                if through is not None:
                    th_app, th_model = self._target_app_and_model(through)
                    if th_app == app and th_model and th_model != model_name:
                        intra_fks_by_app[app].append(
                            FKField(app, model_name, fname, th_app, th_model, deferrable=deferrable)
                        )

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
                        weights[(fk.to_model, fk.from_model)] += 1 if fk.deferrable else 1_000_000
                inner_order = self._best_inner_order(comp, weights)
                pos = {n: i for i, n in enumerate(inner_order)}
                for fk in fks:
                    if fk.from_model in pos and fk.to_model in pos:
                        if pos[fk.to_model] >= pos[fk.from_model]:
                            if not fk.deferrable:
                                raise RuntimeError(
                                    f"intra-app model order leaves non-deferrable FK {fk.key} as a back edge"
                                )
                            out.add(fk)
        return out

    def _compute_deferred(self, fks: list[FKField], apply_order: list[str]) -> set[FKField]:
        pos = {a: i for i, a in enumerate(apply_order)}
        # An FK `from_app.X -> to_app.Y` works iff to_app applies before from_app.
        # to_app applies before from_app iff pos[to_app] < pos[from_app].
        # So an FK is "forward" (no defer) when pos[to_app] < pos[from_app].
        # Otherwise it's a back edge -> defer.
        back = {fk for fk in fks if fk.to_app in pos and fk.from_app in pos and pos[fk.to_app] >= pos[fk.from_app]}
        undeferrable = sorted(str(fk.key) for fk in back if not fk.deferrable)
        if undeferrable:
            raise RuntimeError(
                "apply order leaves non-deferrable FK fields (MTI parent links / PK FKs) "
                f"as back edges — the squash cannot break these cycles: {undeferrable}"
            )
        return back

    def deferred_for_app(self, app: str) -> list[FKField]:
        # Sorted so emitted operation order is deterministic across runs
        # (self.deferred is a set).
        return sorted((fk for fk in self.deferred if fk.from_app == app), key=lambda fk: fk.key)

    # nosemgrep: tuple-return-prefer-dataclass -- tuples serve as graph and dict keys here
    def deferred_field_keys_for_app(self, app: str) -> set[tuple[str, str]]:
        """{(model_name, field_name)} that this app's CreateModel should skip."""
        return {(fk.from_model, fk.field_name) for fk in self.deferred_for_app(app)}

    # nosemgrep: tuple-return-prefer-dataclass -- tuples serve as graph and dict keys here
    def cycle_break_edges(self, squasher: planning.Squasher) -> list[tuple[str, str, str, str]]:
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
