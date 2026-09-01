from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("surveys", "0005_migrate_product_analytics_models"),
    ]

    operations = [
        # List path: survey reads are team-scoped and sorted newest-first. Without this index the
        # team-scoped sort falls back to a scan and sort of the team's surveys.
        SafeAddIndexConcurrently(
            model_name="survey",
            index=models.Index(fields=["team", "-created_at"], name="survey_team_created_idx"),
        ),
        # SDK payload path: every client fetches only running surveys (started, not stopped, not
        # archived), ordered by launch time. A partial index keeps this narrow set ordered.
        SafeAddIndexConcurrently(
            model_name="survey",
            index=models.Index(
                fields=["team", "start_date", "created_at", "id"],
                name="survey_running_payload_idx",
                condition=models.Q(archived=False, end_date__isnull=True),
            ),
        ),
    ]
