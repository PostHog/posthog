from django.db import migrations

from posthog.migration_helpers import DropForeignKey


class Migration(migrations.Migration):
    """Drop the foreign key on posthog_duckgresserver.team_id, which nothing owns any more.

    posthog/migrations/1242 took the `team` field out of Django state and left the column, so
    old releases could keep reading it. The foreign key to posthog_team stayed too, and no
    later migration removes it. The model has since moved to this app and scopes by
    organization instead, so no field names that column.

    A parent delete stops cascading into a relation Django cannot see. The constraint is
    DEFERRABLE INITIALLY DEFERRED with NO ACTION, so a team delete finishes its whole cascade
    and Postgres then rejects the transaction at COMMIT. The delete can never succeed while
    the team has rows here.

    The column stays. Only the constraint goes.
    """

    dependencies = [
        ("managed_warehouse", "0006_alter_managedwarehousesourcejob_created_by"),
    ]

    operations = [
        DropForeignKey("posthog_duckgresserver", column="team_id"),
    ]
