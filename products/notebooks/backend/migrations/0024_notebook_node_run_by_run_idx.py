from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY cannot run inside a transaction. Its own migration rather than 0021's, because
    # 0021 creates a table and adds a constraint and so has to stay atomic — and because a
    # non-concurrent build there would run while the AddField still held ACCESS EXCLUSIVE on
    # posthog_notebooknoderun, stopping every dispatch, callback, and status read on it.
    atomic = False

    dependencies = [
        ("notebooks", "0023_notebook_run"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="notebooknoderun",
            index=models.Index(
                fields=["notebook_run"],
                name="notebook_node_run_by_run_idx",
                condition=models.Q(notebook_run__isnull=False),
            ),
        ),
    ]
