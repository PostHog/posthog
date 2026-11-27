from django.core.management.base import BaseCommand

from products.workflows.backend.facade.writes import backfill_conversion_goals


class Command(BaseCommand):
    help = (
        "Fill HogFlowConversionGoal from every workflow's live conversion and from its revisions, so the "
        "event matcher knows the goals of runs that started before workflow saves recorded them. "
        "Idempotent. Default dry-run; pass --live-run to write."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-id", default=None, type=int, help="Limit to a specific team ID")
        parser.add_argument("--batch-size", default=500, type=int)
        parser.add_argument("--live-run", action="store_true", help="Write the goals (default is dry-run)")

    def handle(self, *args, **options):
        mode = "LIVE RUN" if options["live_run"] else "DRY RUN"
        self.stdout.write(f"Starting backfill_hog_flow_conversion_goals ({mode})")
        result = backfill_conversion_goals(
            team_id=options["team_id"], batch_size=options["batch_size"], live_run=options["live_run"]
        )
        self.stdout.write(f"  {result.workflows_read} workflows read")
        self.stdout.write(f"  {result.revisions_read} revisions read")
        self.stdout.write(
            self.style.SUCCESS(
                f"Completed ({mode}): {result.goals_found} goal(s) found, duplicates and stored ones skipped"
            )
        )
        if not options["live_run"]:
            self.stdout.write(self.style.NOTICE("Run with --live-run to write"))
