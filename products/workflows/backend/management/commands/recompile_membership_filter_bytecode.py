import copy
from collections.abc import Iterator
from typing import Any

from django.core.management.base import BaseCommand

from posthog.cdp.filters import compile_filters_bytecode

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


class Command(BaseCommand):
    help = (
        "Recompile filter bytecode for workflows and hog functions so constant-list membership "
        "(operator 'exact'/'in' with two or more values) inherits type coercion. Such filters used to "
        "compile to the strict IN opcode, which never matched a numeric property (e.g. a survey rating "
        "sent as a number) against a list of string literals. The compiler now lowers them to a "
        "type-coercing equality chain; this recompiles already-stored rows so the fix takes effect "
        "without an edit-and-save. Idempotent — only rows whose bytecode actually changes are written. "
        "internal_destination hog functions are system-managed and skipped unless --include-internal. "
        "Default dry-run; pass --live-run to apply."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-id", default=None, type=int, help="Limit to a specific team ID")
        parser.add_argument("--live-run", action="store_true", help="Apply changes (default is dry-run)")
        parser.add_argument(
            "--include-internal",
            action="store_true",
            help="Also recompile internal_destination hog functions (system-managed; skipped by default)",
        )

    def handle(self, *args, **options):
        live_run = options.get("live_run", False)
        team_id = options.get("team_id")
        include_internal = options.get("include_internal", False)
        mode = "LIVE RUN" if live_run else "DRY RUN"
        self.stdout.write(f"Starting recompile_membership_filter_bytecode ({mode})")
        if team_id:
            self.stdout.write(f"Filtering to team_id={team_id}")

        flows_changed = self._handle_hog_flows(team_id, live_run)
        functions_changed = self._handle_hog_functions(team_id, live_run, include_internal)

        verb = "recompiled" if live_run else "to recompile"
        self.stdout.write(
            self.style.SUCCESS(
                f"Completed ({mode}): {flows_changed} workflow(s) and {functions_changed} hog function(s) {verb}"
            )
        )
        if not live_run and (flows_changed or functions_changed):
            self.stdout.write(self.style.NOTICE("Run with --live-run to apply changes"))

    def _recompile_filters(self, filters: Any, team) -> bool:
        """Recompile filters['bytecode'] in place. Returns True if the bytecode changed.

        Compilation already succeeded when the row was saved, so a failure here is unexpected; skip the
        filter rather than abort the whole backfill."""
        if not isinstance(filters, dict):
            return False
        before = filters.get("bytecode")
        try:
            compile_filters_bytecode(filters, team)  # mutates filters in place
        except Exception as e:
            self.stderr.write(f"  skipped a filter for team {team.id}: {e}")
            return False
        return filters.get("bytecode") != before

    def _iter_action_filter_dicts(self, actions: Any) -> Iterator[dict]:
        """Yield every filters dict embedded in a hog flow's actions JSON (trigger, conditional_branch
        conditions, and wait_until_condition)."""
        if not isinstance(actions, list):
            return
        for action in actions:
            if not isinstance(action, dict):
                continue
            config = action.get("config") or {}
            if not isinstance(config, dict):
                continue
            if isinstance(config.get("filters"), dict):
                yield config["filters"]
            for condition in config.get("conditions") or []:
                if isinstance(condition, dict) and isinstance(condition.get("filters"), dict):
                    yield condition["filters"]
            single_condition = config.get("condition")
            if isinstance(single_condition, dict) and isinstance(single_condition.get("filters"), dict):
                yield single_condition["filters"]

    def _handle_hog_flows(self, team_id, live_run) -> int:
        flows = HogFlow.objects.select_related("team")
        if team_id:
            flows = flows.filter(team_id=team_id)

        changed = 0
        for flow in flows.iterator():
            actions = copy.deepcopy(flow.actions)
            # Recompile every embedded filter — don't short-circuit, or a workflow with multiple
            # filters (e.g. a trigger filter and a branch condition) would leave the later ones on
            # the old bytecode.
            row_changed = False
            for filters in self._iter_action_filter_dicts(actions):
                if self._recompile_filters(filters, flow.team):
                    row_changed = True
            if not row_changed:
                continue
            changed += 1
            self.stdout.write(
                f"  {'Recompiling' if live_run else 'Would recompile'} workflow id={flow.id} "
                f"team_id={flow.team_id} status={flow.status}"
            )
            if live_run:
                # .update() avoids bumping updated_at / firing save signals for a backfill.
                HogFlow.objects.filter(pk=flow.pk).update(actions=actions)
        return changed

    def _handle_hog_functions(self, team_id, live_run, include_internal) -> int:
        functions = HogFunction.objects.select_related("team").filter(deleted=False)
        if team_id:
            functions = functions.filter(team_id=team_id)
        if not include_internal:
            functions = functions.exclude(type="internal_destination")

        changed = 0
        for function in functions.iterator():
            if not isinstance(function.filters, dict):
                continue
            filters = copy.deepcopy(function.filters)
            if not self._recompile_filters(filters, function.team):
                continue
            changed += 1
            self.stdout.write(
                f"  {'Recompiling' if live_run else 'Would recompile'} hog function id={function.id} "
                f"team_id={function.team_id} type={function.type}"
            )
            if live_run:
                HogFunction.objects.filter(pk=function.pk).update(filters=filters)
        return changed
