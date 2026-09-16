import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

from posthog.migration_helpers import DropForeignKey, DropIndexConcurrently


class Migration(migrations.Migration):
    # DROP INDEX CONCURRENTLY cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("warehouse_sources", "0163_externaldataschema_auto_disabled_at"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="externaldatajob",
                    name="created_by",
                    field=models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        db_index=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        to=settings.AUTH_USER_MODEL,
                    ),
                )
            ],
            database_operations=[
                # Without the index below, the FK check on a user delete would seq-scan this table,
                # so the constraint has to go with it. Both operations are idempotent, so a
                # bin/migrate retry after a lost lock race re-runs them safely.
                DropForeignKey("posthog_externaldatajob", column="created_by_id"),
                # The state operation on its own would emit a plain DROP INDEX under ACCESS
                # EXCLUSIVE, which blocks reads and writes on a table that takes a steady
                # insert rate. The index is implicit, created by the foreign key rather than
                # by a Django Index, so it has no model_name + Index the safe helpers take.
                DropIndexConcurrently(
                    index_name="posthog_externaldatajob_created_by_id_570bace7",
                    table_name="posthog_externaldatajob",
                    columns="(created_by_id)",
                ),
            ],
        ),
    ]
