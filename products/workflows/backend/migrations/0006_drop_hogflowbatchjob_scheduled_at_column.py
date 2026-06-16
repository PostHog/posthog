from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0005_remove_hogflowbatchjob_scheduled_at"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                migrations.RunSQL(
                    sql='ALTER TABLE "workflows_hogflowbatchjob" DROP COLUMN IF EXISTS "scheduled_at"',
                    reverse_sql='ALTER TABLE "workflows_hogflowbatchjob" ADD COLUMN "scheduled_at" timestamptz NULL',
                ),
            ],
        ),
    ]
