import uuid

import django.db.models.deletion
from django.db import migrations, models


def backfill_activity(apps, schema_editor):
    Task = apps.get_model("tasks", "Task")
    Activity = apps.get_model("tasks", "TaskActivity")
    Activity.objects.bulk_create(
        [
            Activity(
                team_id=r["team_id"],
                user_id=r["created_by_id"],
                task_id=r["id"],
                kind="created",
                activity_at=r["created_at"],
            )
            for r in Task.objects.exclude(created_by_id=None)
            .values("id", "team_id", "created_by_id", "created_at")
            .iterator(chunk_size=1000)
        ],
        batch_size=1000,
        ignore_conflicts=True,
    )
    selects = [
        "SELECT gen_random_uuid(), team_id, author_id, task_id, id, 'message', created_at, NULL FROM posthog_task_thread_message WHERE author_id IS NOT NULL",
        "SELECT gen_random_uuid(), team_id, mentioned_user_id, task_id, message_id, 'mention', created_at, NULL FROM posthog_task_thread_message_mention",
        "SELECT gen_random_uuid(), m.team_id, t.created_by_id, m.task_id, m.id, 'awaiting_input', m.created_at, NULL FROM posthog_task_thread_message m JOIN posthog_task t ON t.id=m.task_id WHERE m.event='turn_complete' AND t.created_by_id IS NOT NULL",
    ]
    for select in selects:
        schema_editor.execute(
            f"INSERT INTO posthog_task_activity (id,team_id,user_id,task_id,message_id,kind,activity_at,read_at) {select} ON CONFLICT (team_id,user_id,task_id) DO UPDATE SET message_id=EXCLUDED.message_id,kind=EXCLUDED.kind,activity_at=EXCLUDED.activity_at WHERE posthog_task_activity.activity_at <= EXCLUDED.activity_at"
        )


class Migration(migrations.Migration):
    dependencies = [("tasks", "0062_sandbox_custom_image_base_reference")]
    operations = [
        migrations.CreateModel(
            name="TaskActivity",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("created", "Created"),
                            ("mention", "Mention"),
                            ("message", "Message"),
                            ("awaiting_input", "Awaiting input"),
                        ],
                        max_length=32,
                    ),
                ),
                ("activity_at", models.DateTimeField()),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                (
                    "message",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="activity_rows",
                        to="tasks.taskthreadmessage",
                    ),
                ),
                (
                    "task",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="tasks.task"),
                ),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.team",
                    ),
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
            options={"db_table": "posthog_task_activity"},
        ),
        migrations.AddConstraint(
            model_name="taskactivity",
            constraint=models.UniqueConstraint(fields=("team", "user", "task"), name="task_activity_user_task_unique"),
        ),
        migrations.AddIndex(
            model_name="taskactivity",
            index=models.Index(fields=["team", "user", "activity_at", "id"], name="task_activity_feed_idx"),
        ),
        migrations.RunPython(backfill_activity, migrations.RunPython.noop),
    ]
