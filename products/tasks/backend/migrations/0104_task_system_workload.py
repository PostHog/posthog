from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tasks", "0103_validate_task_single_principal")]

    operations = [
        migrations.AddField(
            model_name="task",
            name="system_workload",
            field=models.CharField(
                blank=True,
                choices=[("report_canvas", "Report canvas")],
                editable=False,
                help_text="Trusted workload executed by a system-owned task.",
                max_length=32,
                null=True,
            ),
        )
    ]
