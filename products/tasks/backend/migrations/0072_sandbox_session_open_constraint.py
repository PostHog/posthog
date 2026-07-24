from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tasks", "0071_task_session")]

    operations = [
        migrations.AddConstraint(
            model_name="sandboxsession",
            constraint=models.UniqueConstraint(
                condition=models.Q(ended_at__isnull=True),
                fields=("task_run",),
                name="sandbox_session_one_open_per_run",
            ),
        ),
    ]
