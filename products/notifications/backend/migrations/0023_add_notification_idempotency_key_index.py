from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("notifications", "0022_add_notification_idempotency_key"),
    ]

    operations = [
        CreateIndexConcurrently(
            index_name="notification_event_idempotency_key_uniq",
            table_name="notifications_notificationevent",
            columns="(idempotency_key)",
            unique=True,
        ),
    ]
