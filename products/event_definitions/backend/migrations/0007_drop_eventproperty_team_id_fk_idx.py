import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Drop posthog_eventproperty_team_id_be898eaa — auto-FK on team, ~143 GB.

    Bare (team_id) is a strict prefix of every (team_id, X) composite — adds no read value.
    Suppressed permanently via db_index=False on the team FK in the model state.
    """

    atomic = False

    dependencies = [
        ("event_definitions", "0006_drop_eventproperty_team_property_bloated_idx"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="eventproperty",
                    name="team",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS posthog_eventproperty_team_id_be898eaa",
                    reverse_sql="""
                        CREATE INDEX CONCURRENTLY IF NOT EXISTS posthog_eventproperty_team_id_be898eaa
                        ON posthog_eventproperty (team_id)
                    """,
                ),
            ],
        ),
    ]
