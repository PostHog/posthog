from django.db import migrations, models

from posthog.migration_helpers import AddConstraintNotValid


class Migration(migrations.Migration):
    # The new check is wider than the old one, so every row passes it. A later migration validates it.
    dependencies = [
        ("replay_vision", "0124_replayscanner_free_only"),
    ]

    operations = [
        migrations.AlterField(
            model_name="replayobservation",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("running", "Running"),
                    ("succeeded", "Succeeded"),
                    ("failed", "Failed"),
                    ("ineligible", "Ineligible"),
                    ("cancelled", "Canceled"),
                ],
                default="pending",
                max_length=16,
            ),
        ),
        AddConstraintNotValid(
            model_name="replayobservation",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("completed_at__isnull", True), ("status__in", ["pending", "running"])),
                    models.Q(
                        ("completed_at__isnull", False),
                        ("status__in", ["succeeded", "failed", "ineligible", "cancelled"]),
                    ),
                    _connector="OR",
                ),
                name="rlo_completed_at_matches_status",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="replayobservation",
            name="replay_observation_completed_at_matches_status",
        ),
    ]
