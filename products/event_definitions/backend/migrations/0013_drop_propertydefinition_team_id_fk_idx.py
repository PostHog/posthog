import django.db.models.deletion
from django.db import migrations, models

from posthog.migration_helpers import DropIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index drops cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("event_definitions", "0012_alter_eventdefinition_project_and_more"),
    ]

    operations = [
        # Django's automatic ForeignKey index. posthog_pro_team_id_eac36d_idx on
        # (team_id, type, is_numerical) leads with team_id, so it serves every read this index served.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="propertydefinition",
                    name="team",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="property_definitions",
                        related_query_name="team",
                        to="posthog.team",
                    ),
                ),
            ],
            database_operations=[
                DropIndexConcurrently(
                    index_name="posthog_propertydefinition_team_id_b7abe702",
                    table_name="posthog_propertydefinition",
                    columns="(team_id)",
                ),
            ],
        ),
    ]
