from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("subscriptions", "0005_proactive_recommendation_outcome"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="proactivepreparedartifact",
            index=models.Index(
                fields=["updated_at", "id"],
                condition=models.Q(adopted_at__isnull=True),
                name="subs_artifact_reconcile_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="proactiverecommendationoutcome",
            index=models.Index(
                fields=["updated_at", "id"],
                condition=models.Q(status="pending", due_at__isnull=False),
                name="subs_outcome_dispatch_idx",
            ),
        ),
    ]
