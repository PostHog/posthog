from django.core.management.base import BaseCommand

from products.early_access_features.backend.models import EarlyAccessFeature


class Command(BaseCommand):
    help = "End the waitlist survey of Early Access Features that already left the concept stage"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, default=None, help="Only process features for this team id")
        parser.add_argument(
            "--really-run",
            action="store_true",
            help="Actually close surveys. Without this flag, runs in dry-run mode.",
        )

    def handle(self, *args, **options):
        # Imported here so the helper loads with the app ready.
        from posthog.tasks.early_access_feature import close_waitlist_survey_for_feature

        team_id = options["team_id"]
        really_run = options["really_run"]

        if not really_run:
            self.stdout.write(self.style.WARNING("Dry run — pass --really-run to close surveys."))

        features = (
            EarlyAccessFeature.objects.select_related("team")
            .exclude(stage=EarlyAccessFeature.Stage.CONCEPT)
            .filter(payload__has_key="survey_id")
        )
        if team_id is not None:
            features = features.filter(team_id=team_id)

        closed = 0
        skipped = 0
        for feature in features.iterator():
            if not really_run:
                self.stdout.write(f"[dry-run] would close survey for '{feature.name}' (team {feature.team_id})")
                closed += 1
                continue

            survey = close_waitlist_survey_for_feature(feature)
            if survey is not None:
                closed += 1
                self.stdout.write(self.style.SUCCESS(f"Closed survey {survey.id} for '{feature.name}'"))
            else:
                skipped += 1

        verb = "Would close" if not really_run else "Closed"
        self.stdout.write(self.style.SUCCESS(f"{verb} {closed} survey(s); skipped {skipped}."))
