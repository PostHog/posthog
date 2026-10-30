"""Build one person's ranked inbox list and print it.

The local loop for the pools and the prompt: `--dry-run` calls the model but stores no row and records no event.
"""

from django.core.management.base import BaseCommand, CommandError

from posthog.models import Team, User

from products.signals.backend.personal_ranking.logic import build_personal_ranking


class Command(BaseCommand):
    help = "Build the personal inbox ranking of one user in one project, and print the ranked list."

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--user-id", type=int, required=True)
        parser.add_argument("--focus", type=str, default=None, help="Free text the ranking puts first.")
        parser.add_argument("--limit", type=int, default=None, help="The entries that get a next step.")
        parser.add_argument("--dry-run", action="store_true", help="Call the model, but store nothing.")

    def handle(self, *args, **options):
        team = Team.objects.filter(id=options["team_id"]).first()
        user = User.objects.filter(id=options["user_id"]).first()
        if team is None or user is None:
            raise CommandError("Unknown team or user.")
        build = build_personal_ranking(
            team, user, focus=options["focus"], dry_run=options["dry_run"], limit=options["limit"]
        )
        self.stdout.write(
            f"status: {build.status}, personalized: {build.personalized}, fallback_reason: {build.fallback_reason}"
        )
        self.stdout.write(
            f"candidates: {len(build.candidates)}, tokens: {build.tokens_in}/{build.tokens_out}, "
            f"latency_ms: {build.latency_ms}, ranking_id: {build.ranking_id}"
        )
        by_ref = {candidate.ref: candidate for candidate in build.candidates}
        for entry in build.entries:
            candidate = by_ref[entry.ref]
            self.stdout.write(
                f"\n{entry.rank}. [{entry.tier}] {candidate.title} ({candidate.report_id}, by {entry.ranked_by})"
            )
            self.stdout.write(f"   {entry.reason}")
            if entry.next_step:
                self.stdout.write(f"   next: {entry.next_step}")
        for fold in build.folded:
            self.stdout.write(
                f"\nfolded {by_ref[fold.ref].report_id} into {by_ref[fold.into].report_id}: {fold.reason}"
            )
