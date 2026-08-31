from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("subscriptions", "0005_outcome_observation_immutability"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="pulserun",
            index=models.Index(
                fields=["team", "subscription_id", "-created_at"],
                name="sub_pulse_run_history_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="artifact",
            index=models.Index(
                fields=["updated_at"],
                condition=models.Q(status="publication_unknown", kind="draft_pr"),
                name="sub_pulse_art_pub_unknown_idx",
            ),
        ),
    ]
