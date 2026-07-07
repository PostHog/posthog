from django.db import migrations
from django.db.models.functions import Lower

from products.tasks.backend.mentions import extract_mention_emails

BATCH_SIZE = 1000


def backfill_thread_message_mentions(apps, schema_editor):
    TaskThreadMessage = apps.get_model("tasks", "TaskThreadMessage")
    TaskThreadMessageMention = apps.get_model("tasks", "TaskThreadMessageMention")
    User = apps.get_model("posthog", "User")

    last_pk = None
    while True:
        batch_qs = TaskThreadMessage.objects.order_by("pk").select_related("team")
        if last_pk is not None:
            batch_qs = batch_qs.filter(pk__gt=last_pk)
        batch = list(batch_qs[:BATCH_SIZE])
        if not batch:
            break
        last_pk = batch[-1].pk

        rows = []
        for message in batch:
            emails = extract_mention_emails(message.content)
            if not emails:
                continue
            member_ids = (
                User.objects.annotate(_email_lower=Lower("email"))
                .filter(organizations__id=message.team.organization_id, _email_lower__in=list(emails))
                .values_list("pk", flat=True)
                .distinct()
            )
            rows.extend(
                TaskThreadMessageMention(
                    team_id=message.team_id,
                    message_id=message.pk,
                    task_id=message.task_id,
                    mentioned_user_id=user_id,
                    created_at=message.created_at,
                )
                for user_id in member_ids
                if user_id != message.author_id
            )
        if rows:
            TaskThreadMessageMention.objects.bulk_create(rows, batch_size=BATCH_SIZE, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0049_taskthreadmessagemention"),
    ]

    operations = [
        migrations.RunPython(backfill_thread_message_mentions, migrations.RunPython.noop, elidable=True),
    ]
