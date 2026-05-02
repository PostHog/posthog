import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1134_insightviewed_insight_lva_idx"),
        ("tasks", "0031_task_github_user_integration"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskrun",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                db_index=False,
                help_text="The user who initiated this run.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="initiated_task_runs",
                to="posthog.user",
            ),
        ),
    ]
