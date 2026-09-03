from django.db import migrations, models
from django.utils import timezone as django_timezone


class Migration(migrations.Migration):
    # Adds the Python-level default so rows created after this point are stamped at creation. It
    # changes no stored data and emits no DDL (Django applies `default` in `Model.__init__`, not in
    # the database), so it runs after the 0092 backfill without clobbering the seeded values.
    dependencies = [("tasks", "0092_backfill_task_last_activity_at")]

    operations = [
        migrations.AlterField(
            model_name="task",
            name="last_activity_at",
            field=models.DateTimeField(blank=True, default=django_timezone.now, null=True),
        ),
    ]
