from django.contrib.postgres.indexes import GinIndex
from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY can't run inside a transaction.
    atomic = False

    dependencies = [
        ("user_interviews", "0007_userinterview_classifications"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="userinterview",
                    index=GinIndex(fields=["classifications"], name="user_interview_classif_gin"),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="user_interview_classif_gin",
                    table_name="user_interviews_userinterview",
                    columns="(classifications)",
                    using="gin",
                ),
            ],
        ),
    ]
