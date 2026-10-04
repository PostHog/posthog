from django.db import migrations

from posthog.migration_helpers import DropForeignKey


class Migration(migrations.Migration):
    """Take Link out of Django's state. The table stays until a later drop.

    Django stops cascading into a table it cannot see, so its foreign keys go in the same
    migration.
    """

    dependencies = [
        ("links", "0002_alter_link_team"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="Link"),
            ],
            database_operations=[
                DropForeignKey("posthog_link", column=["created_by_id", "team_id"]),
            ],
        ),
    ]
