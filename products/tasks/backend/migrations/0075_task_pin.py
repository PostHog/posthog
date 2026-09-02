import django.utils.timezone
import django.db.models.deletion
from django.db import migrations, models

import posthog.uuidt


class Migration(migrations.Migration):
    dependencies = [("tasks", "0074_task_session")]

    operations = [
        migrations.CreateModel(
            name="TaskPin",
            fields=[
                (
                    "id",
                    models.UUIDField(default=posthog.uuidt.uuid7, editable=False, primary_key=True, serialize=False),
                ),
                ("pinned_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "task",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="tasks.task"),
                ),
                (
                    "user",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.user",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_task_pin",
                "indexes": [models.Index(fields=["user", "-pinned_at"], name="task_pin_user_pinned_idx")],
                "constraints": [models.UniqueConstraint(fields=("user", "task"), name="task_pin_user_task_unique")],
            },
        ),
    ]
