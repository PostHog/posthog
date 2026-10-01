from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0170_externaldatajob_phase"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="externaldatajob",
            index=models.Index(
                fields=["team", "workflow_run_id", "-created_at"],
                condition=models.Q(workflow_run_id__isnull=False),
                name="idx_extjob_team_wfrun_created",
            ),
        ),
    ]
