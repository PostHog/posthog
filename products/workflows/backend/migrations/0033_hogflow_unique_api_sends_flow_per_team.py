from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("workflows", "0032_teamworkflowsconfig_default_email_integration_id"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                CreateIndexConcurrently(
                    index_name="unique_api_sends_flow_per_team",
                    table_name="posthog_hogflow",
                    columns="(team_id)",
                    unique=True,
                    where="WHERE origin_product = 'api_sends'",
                ),
            ],
            state_operations=[
                migrations.AddConstraint(
                    model_name="hogflow",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("origin_product", "api_sends")),
                        fields=("team",),
                        name="unique_api_sends_flow_per_team",
                    ),
                ),
            ],
        ),
    ]
