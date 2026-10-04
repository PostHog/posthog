from django.db import migrations

from posthog.migration_helpers import DropForeignKey


class Migration(migrations.Migration):
    """Take LiveDebuggerBreakpoint out of Django's state. The table stays until a later drop.

    Django stops cascading into a table it cannot see, so its foreign key goes in the same
    migration.
    """

    dependencies = [
        ("live_debugger", "0002_alter_livedebuggerbreakpoint_team"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="LiveDebuggerBreakpoint"),
            ],
            database_operations=[
                DropForeignKey("posthog_livedebuggerbreakpoint", column="team_id"),
            ],
        ),
    ]
