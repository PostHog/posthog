import json

from django.core.management.base import BaseCommand

from products.signals.backend.artefact_schemas import task_run_identifier_for_legacy_relationship
from products.signals.backend.models import SignalReportArtefact, SignalReportTask
from products.signals.backend.task_run_artefacts import append_task_run_artefact


class Command(BaseCommand):
    help = (
        "Backfill `task_run` log artefacts from existing SignalReportTask rows, so the work tied to "
        "a report (research / implementation / repo-selection runs) shows up in its artefact timeline. "
        "Idempotent: skips any report that already has a task_run artefact referencing the same task."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, default=None, help="Only backfill tasks for this team.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created without writing anything.",
        )

    def _already_backfilled(self, report_id: str, task_id: str) -> bool:
        # `content` is a TextField; the cheap __contains pre-filter narrows to rows that mention the
        # task id, then we parse-confirm so a coincidental substring match can't cause a false skip.
        candidates = SignalReportArtefact.objects.filter(
            report_id=report_id,
            type=SignalReportArtefact.ArtefactType.TASK_RUN,
            content__contains=task_id,
        )
        for artefact in candidates:
            try:
                if json.loads(artefact.content).get("task_id") == task_id:
                    return True
            except (json.JSONDecodeError, ValueError):
                continue
        return False

    def handle(self, *args, **options):
        team_id = options["team_id"]
        dry_run = options["dry_run"]

        report_tasks = SignalReportTask.objects.all().order_by("created_at")
        if team_id is not None:
            report_tasks = report_tasks.filter(team_id=team_id)

        created = 0
        skipped = 0
        for report_task in report_tasks.iterator():
            # Labelled legacy rows are signals-pipeline runs (`signals` / relationship label);
            # unlabelled rows collapse to the generic `tasks` / `agent_run` identifiers — the same
            # mapping `SignalReport.associated_task_runs` fakes for these rows at read time.
            product, task_type = task_run_identifier_for_legacy_relationship(report_task.relationship)

            task_id = str(report_task.task_id)
            report_id = str(report_task.report_id)
            if self._already_backfilled(report_id, task_id):
                skipped += 1
                continue

            if dry_run:
                self.stdout.write(
                    f"[dry-run] would create task_run artefact for report {report_id} "
                    f"(task {task_id}, {product}/{task_type})"
                )
                created += 1
                continue

            artefact = append_task_run_artefact(
                team_id=report_task.team_id,
                report_id=report_id,
                product=product,
                type=task_type,
                task_id=task_id,
            )
            # Backdate to when the task actually ran (the artefact is created now, but the run
            # happened when its SignalReportTask was recorded). `.update()` bypasses auto_now(_add)
            # so the log stays chronologically correct.
            SignalReportArtefact.objects.filter(pk=artefact.pk).update(created_at=report_task.created_at)
            created += 1

        verb = "would create" if dry_run else "created"
        self.stdout.write(
            self.style.SUCCESS(f"Done: {verb} {created} task_run artefact(s), skipped {skipped} (already present).")
        )
