from django.db import migrations


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("event_definitions", "0005_eventdefinition_rename_promoted_to_primary"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveIndex(
                    model_name="eventproperty",
                    name="posthog_eve_team_id_26dbfb_idx",
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS posthog_eve_team_id_26dbfb_idx",
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
