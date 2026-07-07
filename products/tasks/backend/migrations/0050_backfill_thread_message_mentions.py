from django.db import migrations

from products.tasks.backend.mentions import resolve_mentioned_user_ids

BATCH_SIZE = 1000


def backfill_thread_message_mentions(apps, schema_editor):
    TaskThreadMessage = apps.get_model("tasks", "TaskThreadMessage")
    TaskThreadMessageMention = apps.get_model("tasks", "TaskThreadMessageMention")
    User = apps.get_model("posthog", "User")

    last_pk = None
    while True:
        batch_qs = TaskThreadMessage.objects.order_by("pk")
        if last_pk is not None:
            batch_qs = batch_qs.filter(pk__gt=last_pk)
        batch = list(batch_qs[:BATCH_SIZE])
        if not batch:
            break
        last_pk = batch[-1].pk

        rows = [
            TaskThreadMessageMention(
                team_id=message.team_id,
                message_id=message.pk,
                task_id=message.task_id,
                mentioned_user_id=user_id,
                created_at=message.created_at,
            )
            for message in batch
            for user_id in resolve_mentioned_user_ids(
                User, message.content, team_id=message.team_id, author_id=message.author_id
            )
        ]
        if rows:
            TaskThreadMessageMention.objects.bulk_create(rows, batch_size=BATCH_SIZE, ignore_conflicts=True)


class Migration(migrations.Migration):
    atomic = False  # Batched backfill; each bulk_create commits independently and reruns are idempotent.

    dependencies = [
        ("tasks", "0049_taskthreadmessagemention"),
    ]

    operations = [
        migrations.RunPython(backfill_thread_message_mentions, migrations.RunPython.noop, elidable=True),
    ]
