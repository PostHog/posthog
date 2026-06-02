from django.db import migrations


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("event_definitions", "0008_drop_eventproperty_proj_property_coalesce_idx"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveIndex(
                    model_name="eventproperty",
                    name="posthog_eve_proj_id_22de03_idx",
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS posthog_eve_proj_id_22de03_idx",
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
