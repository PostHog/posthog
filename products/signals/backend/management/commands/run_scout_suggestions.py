"""Hand-trigger the pre-computed scout suggestion scan for one team, or print the plan.

`--team-id` runs the headless scan inline (bypassing the planner and its cap) and prints the
stored batch. `--plan` prints what the coordinator would dispatch on the next tick under the
current `signals-scout-suggestions` flag payload, without dispatching anything.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from asgiref.sync import async_to_sync

from posthog.models.scoping.manager import resolve_effective_team_id

from products.signals.backend.models import SignalScoutSuggestionSet
from products.signals.backend.scout_harness.suggestions import (
    enabled_skill_names,
    plan_suggestion_runs,
    read_suggestion_settings,
    reserved_scout_names,
    stamp_requested,
    visible_items,
)
from products.signals.backend.scout_harness.suggestions_runner import arun_scout_suggestions


class Command(BaseCommand):
    help = "Generate the suggested-scouts batch for one team now, or print the coordinator's plan."

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, default=None)
        parser.add_argument("--plan", action="store_true", help="Print the next tick's plan; dispatch nothing.")
        parser.add_argument("--show", action="store_true", help="Print the stored batch for --team-id; run nothing.")

    def handle(self, *args, **options):
        settings = read_suggestion_settings()
        if options["plan"]:
            planned = plan_suggestion_runs(settings)
            self.stdout.write(f"settings: {settings}")
            self.stdout.write(f"planned {len(planned)} team(s):")
            for run in planned:
                self.stdout.write(f"  team {run.team_id} (tier {run.tier})")
            return

        if options["team_id"] is None:
            raise CommandError("--team-id is required unless --plan is given")
        # The row and the planner state live on the canonical project, so a child-environment
        # id must resolve before the stamp or it strands a per-environment row.
        team_id = resolve_effective_team_id(options["team_id"])

        if not options["show"]:
            # Planner state, as a dispatched child would leave it: the coordinator does not redo
            # this team on its next tick.
            stamp_requested([team_id])
            result = async_to_sync(arun_scout_suggestions)(team_id, settings=settings, triggered_by="manual")
            self.stdout.write(
                self.style.SUCCESS(
                    f"team {team_id}: {result.status} in {result.runtime_s:.1f}s "
                    f"({result.suggestion_count} suggestions, task_run={result.task_run_id}, skip={result.skip_reason})"
                )
            )

        row = SignalScoutSuggestionSet.objects.for_team(team_id).first()
        if row is None:
            self.stdout.write("no stored batch")
            return
        self.stdout.write(f"status={row.status} generated_at={row.generated_at} fleet={row.fleet_snapshot}")
        for record in visible_items(
            row, enabled_skill_names=enabled_skill_names(team_id), reserved_names=reserved_scout_names(team_id)
        ):
            self.stdout.write(
                f"- [{record['kind']}/{record['confidence']}] {record['skill_name']}: {record['title']}"
                f"{' (gap)' if record.get('gap') else ''}"
            )
            self.stdout.write(f"    {record['why_here']}")
            if record.get("draft_body"):
                self.stdout.write(
                    f"    draft: {len(record['draft_body'])} chars; config={json.dumps(record['proposed_config'])}"
                )
