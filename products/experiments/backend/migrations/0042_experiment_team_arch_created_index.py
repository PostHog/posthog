from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("experiments", "0041_alter_experimentmetricsrecalculation_trigger"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="experiment",
            index=models.Index(fields=["team", "archived", "-created_at"], name="experiment_team_arch_created"),
        ),
    ]
