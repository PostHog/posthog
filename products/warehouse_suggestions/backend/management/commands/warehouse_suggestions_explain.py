from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from ...logic.job import explain_team, is_eligible


class Command(BaseCommand):
    help = "Print a team's read window, eligibility, and each suggestion kind's candidates and rejections."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team", type=int, required=True, help="Team id to explain.")

    def handle(self, *args: Any, **options: Any) -> None:
        context, results = explain_team(options["team"], today=timezone.now().date())
        reads = context.reads
        self.stdout.write(
            f"window {reads.window.start}..{reads.window.end}: {reads.days_with_data} days with data, "
            f"{reads.view_readers} view readers, {reads.view_reads} view reads, "
            f"eligible={is_eligible(reads, context.rules.eligibility)}"
        )
        for kind, result in results.items():
            self.stdout.write(f"\n{kind}: {len(result.drafts)} candidates")
            if result.skipped_reason:
                self.stdout.write(f"  skipped: {result.skipped_reason}")
            for draft in sorted(result.drafts, key=lambda draft: draft.score, reverse=True):
                self.stdout.write(f"  + {draft.payload.subject_name} score={draft.score:.2f} {draft.score_inputs}")
            for rejection in result.rejections:
                name = context.inventory.name_of(rejection.subject) or rejection.subject.id
                self.stdout.write(f"  - {name}: {rejection.reason}")
