from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY so building the index does not take an ACCESS EXCLUSIVE lock on
    # posthog_task_sandbox_session. Concurrent index work cannot run in a transaction,
    # so the migration is non-atomic.
    atomic = False

    dependencies = [
        ("tasks", "0116_drop_task_session_storage_key_like_index"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="sandboxsession",
            index=models.Index(
                fields=["ended_at", "ttl_expires_at"],
                condition=models.Q(
                    ("client_provenance", "posthog_desktop"),
                    ("origin_product__in", ["user_created", "loop"]),
                    ("user_attributed_at__isnull", False),
                ),
                name="sandbox_session_billable_idx",
            ),
        ),
    ]
