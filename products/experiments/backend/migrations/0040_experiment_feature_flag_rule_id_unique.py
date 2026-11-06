from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("experiments", "0039_experiment_dormant_v2_analysis_columns")]

    operations = [
        # A partial unique constraint compiles to a partial unique index, which Django's
        # AddConstraint builds under an ACCESS EXCLUSIVE lock. Build the index concurrently
        # instead and record only the constraint in Django's state.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="experiment",
                    constraint=models.UniqueConstraint(
                        fields=["feature_flag_rule_id"],
                        condition=models.Q(feature_flag_rule_id__isnull=False),
                        name="posthog_experiment_feature_flag_rule_id_uniq",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="posthog_experiment_feature_flag_rule_id_uniq",
                    table_name="posthog_experiment",
                    columns="(feature_flag_rule_id)",
                    unique=True,
                    where="WHERE feature_flag_rule_id IS NOT NULL",
                ),
            ],
        ),
    ]
