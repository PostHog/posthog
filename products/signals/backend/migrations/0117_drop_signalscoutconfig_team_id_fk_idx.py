import django.db.models.deletion
from django.db import migrations, models

from posthog.migration_helpers import DropIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index drops cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("signals", "0116_signalscoutconfig_write_scopes"),
    ]

    operations = [
        # Django's automatic ForeignKey index. `unique_scout_config_per_team_skill` on
        # (team, skill_name) and `scout_config_source_idx` on (team, source_product,
        # source_id) both lead with team_id, so this index serves no read.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="signalscoutconfig",
                    name="team",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="signal_scout_configs",
                        to="posthog.team",
                    ),
                ),
            ],
            database_operations=[
                DropIndexConcurrently(
                    index_name="signals_signalscoutconfig_team_id_f5c45cf6",
                    table_name="signals_signalscoutconfig",
                    columns="(team_id)",
                ),
            ],
        ),
    ]
