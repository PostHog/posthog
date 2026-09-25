import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0132_retitle_untitled_imported_chats"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="taskcommentactivity",
                    name="task",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="tasks.task",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql='ALTER TABLE "posthog_task_comment_activity" ALTER COLUMN "task_id" DROP NOT NULL;',
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
