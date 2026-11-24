from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from products.tasks.backend.facade import api as tasks_facade

_SKIP_REASONS = {
    "mode_unknown": "the sweep flag could not be read",
    "still_enforced": "the profile still enforces",
    "workflow_gone": "the workflow is no longer running",
    "moved_on": "the task has a newer run or the run changed",
}


class Command(BaseCommand):
    help = (
        "Set cloud runs that the stale run sweep ended back to in progress, once their profile no longer "
        "enforces in the tasks-stale-run-sweep flag. Reopens a run only while it is its task's newest run "
        "and its workflow is still running. Stops if Temporal can't be reached. Sends no events or "
        "notifications. Safe to rerun."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--profile", required=True, help="Task profile key, or none for tasks with no profile")
        parser.add_argument("--hours", type=int, default=24, help="Only runs the sweep ended in the last N hours")
        parser.add_argument("--team-id", type=int, metavar="ID", help="Only runs in this team")
        parser.add_argument(
            "--skip-workflow-check",
            action="store_true",
            help="Also reopen a run whose workflow Temporal no longer reports as running",
        )
        parser.add_argument("--dry-run", action="store_true", help="Count the runs without writing")

    def handle(self, *args: Any, **options: Any) -> None:
        counts = {
            row.outcome: row.count
            for row in tasks_facade.reopen_swept_task_runs(
                profile=options["profile"],
                hours=options["hours"],
                team_id=options["team_id"],
                check_workflows=not options["skip_workflow_check"],
                dry_run=options["dry_run"],
            )
        }
        for outcome, reason in _SKIP_REASONS.items():
            if counts.get(outcome):
                self.stdout.write(f"Skipped {counts[outcome]} runs: {reason}")
        verb = "Would reopen" if options["dry_run"] else "Reopened"
        self.stdout.write(f"{verb} {counts.get('reopened', 0)} runs in all")
