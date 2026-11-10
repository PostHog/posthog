from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("error_tracking", "0046_errortrackingsuppressionrule_built_in"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="errortrackingsuppressionrule",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(built_in_key__isnull=False),
                        fields=("built_in_key", "team"),
                        name="et_supp_rule_built_in_key_uniq",
                    ),
                )
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="et_supp_rule_built_in_key_uniq",
                    table_name="posthog_errortrackingsuppressionrule",
                    columns="(built_in_key, team_id) WHERE built_in_key IS NOT NULL",
                    unique=True,
                )
            ],
        )
    ]
