from django.db import migrations


class Migration(migrations.Migration):
    """Drop the orphaned replay_vision_visionaction and replay_vision_visionactionrun tables.

    Migration 0086 removed VisionAction and VisionActionRun from Django's model state with
    SeparateDatabaseAndState and left both physical tables in place. It passed no
    database_operations, so the tables kept every foreign key they had, including
    visionaction.team_id and visionactionrun.team_id which both reference posthog_team.

    Django no longer knows the two tables exist, so a cascade delete never removes their rows.
    Every FK on them is DEFERRABLE INITIALLY DEFERRED, so a Team delete runs its whole cascade
    and then fails at COMMIT with a ForeignKeyViolation. That makes team and organization
    deletion impossible, and the failing transaction holds SELECT FOR UPDATE on posthog_team
    while it runs, which blocks any concurrent insert that needs FOR KEY SHARE on the same team
    row.

    This is the second phase from safe-django-migrations.md "Dropping Tables". Dropping each
    table also drops its foreign keys, which is what unblocks the cascade.

    visionactionrun is dropped first because it references visionaction.

    Irreversible: the row data is gone. The reverse is a no-op rather than a bogus CREATE TABLE,
    so unapplying this leaves both tables absent, which no code reads or writes.
    """

    dependencies = [
        ("replay_vision", "0092_replayobservationview"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                DROP TABLE IF EXISTS "replay_vision_visionactionrun";
                DROP TABLE IF EXISTS "replay_vision_visionaction";
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
