from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("event_definitions", "0010_propertydefinition_warehouse_origin"),
    ]

    operations = [
        SafeRemoveIndexConcurrently(
            model_name="schemapropertygroup",
            name="schema_pg_team_name_idx",
        ),
    ]
