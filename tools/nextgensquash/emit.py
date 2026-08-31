"""Emit stub/initial/finalize_fks/schema_addons squash files for each app from the final state."""

from __future__ import annotations

import re
import sys
from dataclasses import (
    dataclass,
    field as dc_field,
)
from pathlib import Path
from typing import Any

from django.db import migrations as dj_migrations  # noqa: E402
from django.db.migrations.loader import MigrationLoader  # noqa: E402
from django.db.migrations.state import ProjectState  # noqa: E402
from django.db.migrations.writer import MigrationWriter  # noqa: E402

import networkx as nx

from . import cyclebreak, planning


@dataclass
class SquashFile:
    app: str
    name: str
    operations: list[Any]
    dependencies: list[tuple[str, str]]
    replaces: list[tuple[str, str]]
    atomic: bool = True
    run_before: list[tuple[str, str]] = dc_field(default_factory=list)


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

    # The stub owns ("<app>", "__first__"). Third-party migrations already
    # applied on live DBs resolve swappable deps (AUTH_USER_MODEL, swapped
    # OAuth models) to exactly that sentinel, and check_consistent_history
    # then demands the stub be applied — its squash exemption only fires for
    # nodes with a non-empty `replaces`. Claim the app's ROOT node so the
    # exemption applies and check_replacements stamps the stub. Two rules:
    # the claim MUST be parentless (a mid-chain claim weaves stub and initial
    # into a CircularDependencyError, because remove_replaced_nodes re-parents
    # the claimed node's neighbours onto both replacement nodes), and it must
    # be a node that exists in the EMIT-TIME graph — the loader substitutes
    # the historical 0284 squash for the ancient names it replaces, so
    # "0001_initial" is not a node on a clean tree. Only swappable-target
    # apps need this; today that is posthog alone.
    STUB_CLAIMS_BY_APP: dict[str, tuple[tuple[str, str], ...]] = {
        "posthog": (("posthog", "0001_initial_squashed_0284_improved_caching_state_idx"),),
    }

    def __init__(
        self,
        state: ProjectState,
        squasher: planning.Squasher,
        app: str,
        cycle_breaker: cyclebreak.CycleBreaker,
    ):
        self.state = state
        self.squasher = squasher
        self.app = app
        self.cycle_breaker = cycle_breaker
        # RunSQL ops from claimed migrations that the squash neither reproduces
        # via CreateModel nor forwards to schema_addons. Populated by
        # _collect_index_runsql_ops; emit writes them to DROPPED_RUNSQL.txt so
        # every drop is auditable instead of silent.
        self.dropped_runsql: list[str] = []

    def _models_in_app(self) -> list[Any]:
        return [ms for (app, _), ms in self.state.models.items() if app == self.app]

    def _create_model_op(
        self, ms: Any, skip_fields: set[str]
    ) -> tuple[Any, list[Any], list[Any], list[tuple[str, Any]]]:
        """Build a CreateModel that omits `skip_fields` plus any index/constraint
        referencing those fields. Return the CreateModel plus deferred indexes,
        constraints, and (option_key, full_value) unique_together/index_together
        entries — all to be re-added in finalize_fks.
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
        # tuple that touches a deferred field from the CreateModel; finalize_fks
        # restores the full value via Alter*Together once the fields exist.
        expanded_skip = set(skip_fields) | {f"{f}_id" for f in skip_fields}
        deferred_together: list[tuple[str, Any]] = []
        for legacy_key in ("unique_together", "index_together"):
            legacy = options.get(legacy_key)
            if not legacy:
                continue
            full = {tuple(t) for t in legacy}
            filtered = {t for t in full if not any(f in expanded_skip for f in t)}
            if filtered != full:
                deferred_together.append((legacy_key, full))
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
        return create, deferred_indexes, deferred_constraints, deferred_together

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
            t_app, t_model = cyclebreak.CycleBreaker._target_app_and_model(getattr(remote, "model", None))
            if t_app == self.app and t_model and t_model != ms.name.lower():
                targets.add(t_model)
            through = getattr(remote, "through", None)
            if through is not None:
                t_app, t_model = cyclebreak.CycleBreaker._target_app_and_model(through)
                if t_app == self.app and t_model and t_model != ms.name.lower():
                    targets.add(t_model)
        for base in ms.bases or ():
            b_app, b_model = cyclebreak.CycleBreaker._target_app_and_model(base)
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
        latest_old = planning.Snapshotter(self.squasher).latest_old_per_app()
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
                t_app, _ = cyclebreak.CycleBreaker._target_app_and_model(getattr(remote, "model", None))
                if not t_app or t_app == self.app:
                    continue
                if t_app in latest_old:
                    deps.add((t_app, latest_old[t_app]))
                elif t_app in self.BUILTIN_FK_APPS:
                    deps.add((t_app, "__latest__"))
                else:
                    # A silent drop here mis-orders the graph on fresh DBs: the
                    # squash's CreateModel would carry an FK whose target app
                    # has no dependency edge. Fail loudly; extend
                    # BUILTIN_FK_APPS or EXCLUDED_APPS handling deliberately.
                    raise RuntimeError(
                        f"{self.app}.{mname}.{fname} FKs into app {t_app!r}, which the squash "
                        f"neither claims (no old migrations) nor special-cases (BUILTIN_FK_APPS)"
                    )
        return sorted(deps)

    def _carried_run_before(self) -> list[tuple[str, str]]:
        """Preserve run_before guarantees of claimed migrations whose target is
        outside the old set (third-party or young) — e.g. posthog.0745 must run
        before oauth2_provider.0001 because the oauth2_provider models are
        swapped into posthog. Folding drops the attribute silently otherwise;
        MigrationWriter doesn't serialize run_before, so FileWriter injects it.
        """
        out: set[tuple[str, str]] = set()
        for m in self.squasher.old.values():
            if m.ref.app != self.app:
                continue
            for rb in m.run_before:
                if rb.key not in self.squasher.old_keys:
                    out.add(rb.key)
        return sorted(out)

    def _third_party_dependencies(self) -> list[tuple[str, str]]:
        """Report (never emit) deps of claimed migrations into apps this repo
        does not manage — e.g. posthog.0886 -> social_django.0010_uid_db_index.

        Do NOT carry these onto the squash: a third-party app whose own
        migrations hang off ("posthog", "__first__") (swappable AUTH_USER_MODEL)
        would then be forced BEFORE the initial that creates posthog_user, and
        its user-FK CREATE TABLE breaks on a fresh DB. The historical dep only
        guarded a RunPython the squash drops anyway; install's cycle-edge
        removal strips it from the source file so the loader's parent-edge
        inheritance can't resurrect it. This list feeds the emit log so every
        such drop stays visible.
        """
        managed_apps = {m.ref.app for m in self.squasher.tree.migrations.values()}
        best: dict[str, str] = {}
        for m in self.squasher.old.values():
            if m.ref.app != self.app:
                continue
            for dep in m.dependencies:
                if dep.app in managed_apps or dep.app == "__setting__":
                    continue
                if dep.name.startswith("__"):
                    continue  # __first__/__latest__ sentinels; the FK walk covers these
                cur = best.get(dep.app)
                if cur is None or dep.name > cur:
                    best[dep.app] = dep.name
        return sorted(best.items())

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
        # Names the stub claims belong to exactly one replacement node.
        stub_claims = set(self.STUB_CLAIMS_BY_APP.get(self.app, ()))
        return sorted(set(out) - stub_claims)

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
                # isinstance, not class-name match: CreateIndexConcurrently and
                # friends subclass RunSQL and must not slip past.
                elif isinstance(op, dj_migrations.RunSQL):
                    sql = op.sql if isinstance(op.sql, str) else str(op.sql)
                    if "CREATE EXTENSION" in sql.upper():
                        if sql not in seen:
                            seen.add(sql)
                            out.append(op)
        return out

    # Stateless constraint ops from posthog.migration_helpers: their DDL exists
    # only in database_forwards (state_forwards is a no-op), so a from-state
    # CreateModel loses it. Forward them verbatim into schema_addons — all are
    # idempotent (skip when the constraint already exists / is validated).
    STATELESS_CONSTRAINT_OP_NAMES: frozenset[str] = frozenset(
        {"AddForeignKeyNotValid", "ValidateForeignKey", "ValidateConstraint"}
    )

    def _stateless_constraint_ops(self) -> list[Any]:
        loader = MigrationLoader(connection=None, ignore_no_migrations=True)
        claimed_keys = {migr.ref.key for migr in self.squasher.old.values() if migr.ref.app == self.app}
        out: list[Any] = []

        def walk(ops: list[Any]) -> None:
            for op in ops:
                if op.__class__.__name__ in self.STATELESS_CONSTRAINT_OP_NAMES:
                    out.append(op)
                elif isinstance(op, dj_migrations.SeparateDatabaseAndState):
                    walk(list(op.database_operations))

        for (app, name), m in sorted(loader.graph.nodes.items()):
            if app != self.app or (app, name) not in claimed_keys:
                continue
            walk(list(m.operations))
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

        def walk(mig_name: str, ops: list[Any]) -> None:
            for op in ops:
                # isinstance, not class-name match: CreateIndexConcurrently /
                # DropIndexConcurrently subclass RunSQL, and a name match let
                # their index SQL vanish without a trace (lost partial index on
                # posthog_dashboardtile in the Aug 2026 tree).
                if isinstance(op, dj_migrations.RunSQL):
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
                        self.dropped_runsql.append(f"{self.app}.{mig_name} [table-ddl]: {sql_text[:160]}")
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
                        self.dropped_runsql.append(f"{self.app}.{mig_name} [unrecognized]: {sql_text[:160]}")
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
                elif isinstance(op, dj_migrations.SeparateDatabaseAndState):
                    walk(mig_name, list(op.database_operations))

        for (app, name), m in sorted(loader.graph.nodes.items()):
            if app != self.app or (app, name) not in claimed_keys:
                continue
            walk(name, list(m.operations))

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
        # Emit skips claimed apps with no models left in the final state (all
        # moved away, e.g. llm_analytics) — no squash file exists for them, so
        # no dep may point at one.
        apps_with_models = {a for (a, _) in self.state.models}
        for app in {m.ref.app for m in self.squasher.old.values()}:
            if app == self.app or app not in apps_with_models:
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
            create, _, _, _ = self._create_model_op(ms, set())
            stub_ops.append(create)
        configured_claims = self.STUB_CLAIMS_BY_APP.get(self.app, ())
        stub_claims = [key for key in configured_claims if key in self.squasher.old_keys]
        if len(stub_claims) != len(configured_claims):
            # An empty-replaces stub fails check_consistent_history on every
            # live DB; that must never happen silently.
            missing = sorted(set(configured_claims) - set(stub_claims))
            raise RuntimeError(f"stub claim(s) not in the old partition for {self.app}: {missing}")
        stub = SquashFile(
            app=self.app,
            name=self.STUB_NAME,
            operations=stub_ops,
            dependencies=[],
            replaces=stub_claims,
        )

        rest_models = [ms for ms in self._models_in_app() if ms.name.lower() not in early_model_names]
        models = self._sort_models_topologically(rest_models, skip_by_model)
        initial_ops: list[Any] = []
        deferred_indexes: list[tuple[str, Any]] = []  # (model_name_lower, Index)
        deferred_constraints: list[tuple[str, Any]] = []  # (model_name_lower, Constraint)
        deferred_togethers: list[tuple[str, str, Any]] = []  # (model_name_lower, option_key, full_value)
        for ms in models:
            skip_fields = skip_by_model.get(ms.name.lower(), set())
            create, idxs, cons, togethers = self._create_model_op(ms, skip_fields)
            initial_ops.append(create)
            deferred_indexes.extend((ms.name.lower(), idx) for idx in idxs)
            deferred_constraints.extend((ms.name.lower(), c) for c in cons)
            deferred_togethers.extend((ms.name.lower(), key, full) for key, full in togethers)
        # Initial's dependencies: stub + cross-app FK targets in the foreign-app
        # latest-old migration. The stub anchor means we're never __first__.
        initial_deps: list[tuple[str, str]] = [(self.app, self.STUB_NAME)]
        initial_deps.extend(self._cross_app_dependencies(skip_by_model))
        for tp_app, tp_name in self._third_party_dependencies():
            sys.stderr.write(f"note: {self.app} drops third-party dep ({tp_app}, {tp_name}) — see docstring\n")
        initial_deps = sorted(set(initial_deps))
        initial = SquashFile(
            app=self.app,
            name=self.INITIAL_NAME,
            operations=initial_ops,
            dependencies=initial_deps,
            replaces=self._replaces(),
            run_before=self._carried_run_before(),
        )

        # RunSQL-created indexes plus stateless constraint DDL from claimed
        # migrations (Phase A). Emitted as a separate trailing
        # 0003_schema_addons file — it can exist with or without a
        # 0002_finalize_fks.
        addon_ops = self._collect_index_runsql_ops() + self._stateless_constraint_ops()

        deferred_fks = self.cycle_breaker.deferred_for_app(self.app)
        if not deferred_fks and not deferred_indexes and not deferred_constraints and not deferred_togethers:
            if not addon_ops:
                return [stub, initial]
            addons = SquashFile(
                app=self.app,
                name=self.SCHEMA_ADDONS_NAME,
                operations=addon_ops,
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
        # Restore the full unique_together / index_together sets now that every
        # deferred field exists.
        for model_name, key, full in deferred_togethers:
            if key == "unique_together":
                addfield_ops.append(dj_migrations.AlterUniqueTogether(name=model_name, unique_together=full))
            else:
                addfield_ops.append(dj_migrations.AlterIndexTogether(name=model_name, index_together=full))

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
        if not addon_ops:
            return [stub, initial, finalize]
        addons = SquashFile(
            app=self.app,
            name=self.SCHEMA_ADDONS_NAME,
            operations=addon_ops,
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
        if sq.run_before:
            # MigrationWriter doesn't serialize run_before either.
            entries = "".join(f'        ("{a}", "{n}"),\n' for a, n in sq.run_before)
            text = text.replace(
                "    initial = True\n",
                f"    initial = True\n\n    run_before = [\n{entries}    ]\n",
                1,
            )
        path.write_text(text)
        return path
