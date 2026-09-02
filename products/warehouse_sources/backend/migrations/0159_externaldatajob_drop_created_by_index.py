import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

from posthog.migration_helpers import DropIndexConcurrently


class Migration(migrations.Migration):
    # DROP INDEX CONCURRENTLY cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("warehouse_sources", "0158_migrate_shopify_job_inputs_to_auth_method"),
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
                        db_index=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                )
            ],
            database_operations=[
                # The state operation on its own would emit a plain DROP INDEX under ACCESS
                # EXCLUSIVE, which blocks reads and writes on a table that takes a steady
                # insert rate. The index is implicit, created by the foreign key rather than
                # by a Django Index, so it has no model_name + Index the safe helpers take.
                DropIndexConcurrently(
                    index_name="posthog_externaldatajob_created_by_id_570bace7",
                    table_name="posthog_externaldatajob",
                    columns="(created_by_id)",
                )
            ],
        ),
    ]
