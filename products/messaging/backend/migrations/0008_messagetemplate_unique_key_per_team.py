from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("messaging", "0007_messagetemplate_code_managed_fields"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="messagetemplate",
                    constraint=models.UniqueConstraint(
                        fields=("team", "key"),
                        condition=models.Q(("deleted", False), ("key__isnull", False)),
                        name="unique_message_template_key_per_team",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="unique_message_template_key_per_team",
                    table_name="posthog_messagetemplate",
                    columns='("team_id", "key")',
                    unique=True,
                    where='WHERE (NOT "deleted" AND "key" IS NOT NULL)',
                ),
            ],
        ),
    ]
