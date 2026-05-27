from django.db import migrations


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("event_definitions", "0007_drop_eventproperty_team_id_fk_idx"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveIndex(
                    model_name="eventproperty",
                    name="posthog_eve_proj_id_26dbfb_idx",
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS posthog_eve_proj_id_26dbfb_idx",
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
