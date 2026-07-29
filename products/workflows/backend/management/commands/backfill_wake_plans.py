"""
Derive wake plans for `wait_until_condition` steps on flows saved before the field existed.

Until a flow is next saved, its waits carry no plan, and the executor keeps polling them (it can't
prove how they wake, so it fails closed). This populates them without touching anything else, so the
scheduling path actually engages.

Dry by default. Run it, read the per-flow verdicts, and only then apply — the SCHEDULABLE lines are
the ones worth eyeballing, since those are the waits that will stop being polled.
"""

from typing import Any, Optional

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

import structlog

from posthog.cdp.filters import compile_filters_expr
from posthog.models import Team

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.services.wake_plan import analyze_wait_condition

logger = structlog.get_logger(__name__)


def derive_plan(config: dict, team: Team) -> tuple[Optional[dict], str]:
    """Return (plan, verdict) for one wait's config. Mirrors the serializer, but reports why."""
    filters = (config.get("condition") or {}).get("filters")
    if not filters:
        return None, "NO_CONDITION"

    try:
        plan = analyze_wait_condition(compile_filters_expr(filters, team), team.id)
    except Exception as e:
        return (
            {"streams": [], "timers": [], "unsupported_reason": f"analysis failed ({type(e).__name__})"},
            f"ERROR {type(e).__name__}",
        )

    stored = {"streams": plan.streams, "timers": plan.timers, "unsupported_reason": plan.unsupported_reason}
    if plan.unsupported_reason:
        return stored, f"POLLING {plan.unsupported_reason}"
    if plan.timers:
        return stored, f"SCHEDULABLE {len(plan.timers)} timer(s)"
    return stored, f"STREAM_ONLY {','.join(plan.streams) or 'no streams'}"


class Command(BaseCommand):
    help = "Backfill wake plans onto wait_until_condition steps of existing workflows"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--apply", action="store_true", help="Write the plans (default is a dry run)")
        parser.add_argument("--team-id", type=int, help="Limit to one team")
        parser.add_argument("--flow-id", type=str, help="Limit to one flow")
        parser.add_argument(
            "--status",
            default="active",
            help="Flow status to include, or 'all' (default: active)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        flows = HogFlow.objects.all()
        if options["status"] != "all":
            flows = flows.filter(status=options["status"])
        if options["team_id"]:
            flows = flows.filter(team_id=options["team_id"])
        if options["flow_id"]:
            flows = flows.filter(id=options["flow_id"])

        counts: dict[str, int] = {}
        changed_flows = 0
        waits_seen = 0

        for flow in flows.select_related("team").iterator(chunk_size=100):
            if not isinstance(flow.actions, list):
                continue

            touched = False
            for action in flow.actions:
                if not isinstance(action, dict) or action.get("type") != "wait_until_condition":
                    continue
                config = action.get("config")
                if not isinstance(config, dict):
                    continue

                waits_seen += 1
                plan, verdict = derive_plan(config, flow.team)
                counts[verdict.split(" ")[0]] = counts.get(verdict.split(" ")[0], 0) + 1

                # Only report a change when the stored value would actually differ, so re-runs are
                # quiet and the apply pass touches the minimum number of rows.
                if config.get("wake_plan") != plan:
                    config["wake_plan"] = plan
                    touched = True

                self.stdout.write(f"team={flow.team_id} flow={flow.id} action={action.get('id')} :: {verdict}")

            if not touched:
                continue
            changed_flows += 1
            if options["apply"]:
                with transaction.atomic():
                    # actions only: never let a backfill rewrite anything else about the flow.
                    HogFlow.objects.filter(pk=flow.pk).update(actions=flow.actions)

        self.stdout.write("")
        self.stdout.write(f"wait steps examined: {waits_seen}")
        for verdict, n in sorted(counts.items()):
            self.stdout.write(f"  {verdict}: {n}")
        self.stdout.write(f"flows needing an update: {changed_flows}")
        if not options["apply"]:
            self.stdout.write(self.style.WARNING("dry run - nothing written. Re-run with --apply."))
        else:
            self.stdout.write(self.style.SUCCESS(f"updated {changed_flows} flow(s)"))

        if counts.get("ERROR"):
            raise CommandError(f"{counts['ERROR']} wait step(s) failed analysis - investigate before applying")
