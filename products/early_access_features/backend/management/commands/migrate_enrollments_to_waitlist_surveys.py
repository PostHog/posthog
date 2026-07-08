from django.core.management.base import BaseCommand

from products.early_access_features.backend.models import EarlyAccessFeature
from products.surveys.backend.models import Survey


class Command(BaseCommand):
    help = (
        "Migrate legacy 'Get notified' registrations (the $feature_enrollment/<flag> person property) "
        "into each concept-stage feature's linked waitlist survey as `survey sent` responses, so the "
        "survey is the single waitlist per feature. Skips people who already responded to the survey."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, default=None, help="Only process features for this team id")
        parser.add_argument(
            "--really-run",
            action="store_true",
            help="Actually capture the survey responses. Without this flag, runs in dry-run mode.",
        )

    def handle(self, *args, **options):
        # Imported here so HogQL and the analytics client load with the app ready.
        import posthoganalytics

        from posthog.hogql import ast
        from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS, LimitContext
        from posthog.hogql.query import execute_hogql_query

        from posthog.tasks.early_access_feature import capture_event

        team_id = options["team_id"]
        really_run = options["really_run"]

        if not really_run:
            self.stdout.write(self.style.WARNING("Dry run — pass --really-run to capture survey responses."))

        features = EarlyAccessFeature.objects.select_related("feature_flag", "team").filter(
            stage=EarlyAccessFeature.Stage.CONCEPT, feature_flag__isnull=False
        )
        if team_id is not None:
            features = features.filter(team_id=team_id)

        total_migrated = 0
        for feature in features.iterator():
            survey = Survey.objects.filter(
                team=feature.team, linked_flag=feature.feature_flag, type=Survey.SurveyType.API
            ).first()
            if survey is None:
                self.stdout.write(f"'{feature.name}': no linked waitlist survey, skipping")
                continue
            question_id = (survey.questions or [{}])[0].get("id")

            # People who registered interest the old way and have an email on their person.
            enrolled = execute_hogql_query(
                """
                SELECT
                    properties.email AS email,
                    argMax(pdi.distinct_id, created_at) AS distinct_id
                FROM persons
                WHERE properties[{enrollment_key}] = 'true'
                AND notEmpty(properties.email)
                GROUP BY properties.email
                LIMIT {limit}
                """,
                placeholders={
                    "enrollment_key": ast.Constant(value=f"$feature_enrollment/{feature.feature_flag.key}"),
                    "limit": ast.Constant(value=MAX_SELECT_RETURNED_ROWS),
                },
                team=feature.team,
                limit_context=LimitContext.QUERY_ASYNC,
            ).results

            if not enrolled:
                self.stdout.write(f"'{feature.name}': no legacy registrations to migrate")
                continue

            # People who already responded to the survey (from any surface) — don't duplicate them.
            responded = execute_hogql_query(
                """
                SELECT DISTINCT lower(JSONExtractString(properties, '$survey_response')) AS email
                FROM events
                WHERE event = 'survey sent'
                AND JSONExtractString(properties, '$survey_id') = {survey_id}
                LIMIT {limit}
                """,
                placeholders={
                    "survey_id": ast.Constant(value=str(survey.id)),
                    "limit": ast.Constant(value=MAX_SELECT_RETURNED_ROWS),
                },
                team=feature.team,
                limit_context=LimitContext.QUERY_ASYNC,
            ).results
            responded_emails = {row[0] for row in responded if row and row[0]}

            migrated = 0
            for email, distinct_id in enrolled:
                if not email or email.lower() in responded_emails:
                    continue
                if really_run:
                    properties = {
                        "$survey_id": str(survey.id),
                        "$survey_response": email,
                        "feature_flag_key": feature.feature_flag.key,
                        "migrated_from_enrollment": True,
                    }
                    if question_id:
                        properties[f"$survey_response_{question_id}"] = email
                    capture_event("survey sent", distinct_id=distinct_id, properties=properties)
                migrated += 1

            total_migrated += migrated
            verb = "would migrate" if not really_run else "migrated"
            self.stdout.write(
                f"'{feature.name}': {verb} {migrated} of {len(enrolled)} legacy registrations "
                f"({len(responded_emails)} already responded)"
            )

        if really_run:
            posthoganalytics.flush()
        verb = "Would migrate" if not really_run else "Migrated"
        self.stdout.write(self.style.SUCCESS(f"{verb} {total_migrated} registration(s) into waitlist surveys."))
