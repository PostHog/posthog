from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("workflows", "0043_sandbox_sender_state")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="hogflowbatchjob",
            index=models.Index(fields=["hog_flow", "-created_at"], name="hogflowbatchjob_flow_recent"),
        ),
    ]
