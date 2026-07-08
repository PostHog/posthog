from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction

from products.early_access_features.backend.models import EarlyAccessFeature


class Command(BaseCommand):
    help = "Backfill an `api` waitlist survey for existing concept-stage ('Coming Soon') Early Access Features"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, default=None, help="Only process features for this team id")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Skip the coming-soon-waitlist-surveys feature flag gate (process all matching teams)",
        )
        parser.add_argument(
            "--really-run",
            action="store_true",
            help="Actually create surveys. Without this flag, runs in dry-run mode.",
        )

    def handle(self, *args, **options):
        # Imported here so the gate/creation helpers load with the app ready.
        from posthog.tasks.early_access_feature import (
            coming_soon_waitlist_surveys_enabled,
            ensure_waitlist_survey_for_feature,
        )

        team_id = options["team_id"]
        force = options["force"]
        really_run = options["really_run"]

        if not really_run:
            self.stdout.write(self.style.WARNING("Dry run — pass --really-run to create surveys."))

        features = EarlyAccessFeature.objects.select_related("feature_flag", "team").filter(
            stage=EarlyAccessFeature.Stage.CONCEPT
        )
        if team_id is not None:
            features = features.filter(team_id=team_id)

        created = 0
        skipped = 0
        # The gate is a network flag eval — cache it per team so teams with several
        # concept features don't repeat the identical call.
        gate_cache: dict[int, bool] = {}
        for feature in features.iterator():
            if feature.payload and feature.payload.get("survey_id"):
                skipped += 1
                continue
            if not feature.feature_flag:
                skipped += 1
                continue
            if not force:
                if feature.team_id not in gate_cache:
                    gate_cache[feature.team_id] = coming_soon_waitlist_surveys_enabled(feature.team)
                if not gate_cache[feature.team_id]:
                    skipped += 1
                    continue

            if not really_run:
                self.stdout.write(f"[dry-run] would create survey for '{feature.name}' (team {feature.team_id})")
                created += 1
                continue

            try:
                with transaction.atomic():
                    survey = ensure_waitlist_survey_for_feature(feature)
            except IntegrityError:
                # Collided with the live post_save signal creating the same survey —
                # skip this feature and keep going; a re-run picks it up.
                self.stdout.write(
                    self.style.WARNING(f"'{feature.name}': survey creation raced, skipping (re-run to retry)")
                )
                skipped += 1
                continue
            if survey is not None:
                created += 1
                self.stdout.write(self.style.SUCCESS(f"Created survey {survey.id} for '{feature.name}'"))
            else:
                skipped += 1

        verb = "Would create" if not really_run else "Created"
        self.stdout.write(self.style.SUCCESS(f"{verb} {created} survey(s); skipped {skipped}."))
